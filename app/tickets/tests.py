from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import connection, close_old_connections
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.utils import timezone
from tempfile import TemporaryDirectory
from accounts.models import User, AuditEvent
from accounts.services import Conflict
from projects import services as projects
from projects.models import TicketStatus, TicketType
from projects.tests import user
from . import services
from .models import Attachment, Comment, Ticket
from .markdown import render_markdown


class TicketTests(TestCase):
    def setUp(self):
        self.system = user('system', True)
        self.manager = user('manager')
        self.member = user('member')
        self.other = user('other')
        self.project = projects.create_project(self.system, 'Alpha', '', [self.manager.pk])
        projects.add_member(self.system, self.project.pk, self.member.pk)
        self.foreign = projects.create_project(self.system, 'Secret', '', [self.other.pk])
        self.data = dict(title='チケット', description_markdown='**説明**', status_id=TicketStatus.objects.get(project=self.project,builtin_code='open').pk,
            type_id=TicketType.objects.filter(project=self.project).first().pk, priority='medium', assignee_id=self.member.pk, start_date=None, due_date=None)
        self.ticket = services.save_ticket(self.member,self.project.pk,self.data)
        self.base = f'/tickets/{self.ticket.pk}'
        self.new = f'/projects/{self.project.pk}/tickets/new'
        self.client.force_login(self.member)

    def post_data(self, **changes):
        return {k: '' if v is None else v for k,v in (self.data | changes).items()}

    def test_crud_audit_and_creator_immutable(self):
        search_page=self.client.get('/tickets')
        self.assertContains(search_page,'チケット検索')
        self.assertNotContains(search_page,'<h1>チケット検索</h1>',html=True)
        self.assertNotContains(search_page,'全チケット一覧')
        self.assertNotContains(search_page,'自分の担当チケット</a>')
        dashboard=self.client.get('/')
        self.assertContains(dashboard,'/tickets?assignee_id=')
        self.assertContains(dashboard,'担当者を自分に指定してチケット検索')
        response=self.client.post(self.new,self.post_data(title='新規'))
        self.assertRedirects(response,f'/projects/{self.project.pk}/tickets')
        created=Ticket.objects.get(title='新規')
        self.assertEqual(created.creator_id,self.member.pk)
        editor=self.client.get(f'/tickets/{created.pk}')
        self.assertContains(editor,'ticket-editor-card')
        self.assertContains(editor,'<h1>新規</h1>',html=True)
        self.assertNotContains(editor,'Alpha / チケット一覧')
        self.assertContains(editor,'name="title" value="新規"')
        self.assertContains(editor,'id="id_description_markdown"')
        self.assertContains(editor,'rows="6"')
        self.assertContains(editor,'id="description-preview-button"')
        self.assertContains(editor,'id="markdown-preview-dialog"')
        self.assertNotContains(editor,'id="markdown-preview" class="markdown-body"')
        self.assertContains(editor,f'class="button" href="/projects/{self.project.pk}/tickets">キャンセル</a>',html=False)
        self.assertNotContains(editor,'チケット一覧へ戻る')
        self.assertRedirects(self.client.post(self.base+'/edit',self.post_data(title='更新')),
                             f'/projects/{self.project.pk}/tickets')
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.title,'更新')
        self.assertEqual(self.ticket.creator_id,self.member.pk)
        event=AuditEvent.objects.filter(entity_type='ticket',entity_id=self.ticket.pk,action='update').get()
        self.assertEqual(event.changes['title'],{'before':'チケット','after':'更新'})
        self.assertEqual(event.ticket_context_id,self.ticket.pk)
        self.assertRedirects(self.client.post(self.base+'/comments',{'body_markdown':'削除後も監査に残すコメント'}),self.base)
        self.assertContains(self.client.get(self.base+'/delete'),'復元できません')
        self.assertTrue(Ticket.objects.filter(pk=self.ticket.pk).exists())
        self.assertEqual(self.client.post(self.base+'/delete').status_code,302)
        comment_event=AuditEvent.objects.get(entity_type='comment',action='delete',ticket_context_id=self.ticket.pk)
        self.assertEqual(comment_event.entity_snapshot['body_markdown'],'削除後も監査に残すコメント')
        event=AuditEvent.objects.get(entity_type='ticket',entity_id=self.ticket.pk,action='delete')
        self.assertEqual(event.changes['description_markdown'],{'before':'**説明**','after':None})
        self.assertEqual(self.client.get(self.base).status_code,404)

    def test_ticket_comment_records_author_and_renders_markdown(self):
        editor=self.client.get(self.base)
        self.assertContains(editor,'class="card ticket-comments"')
        self.assertContains(editor,'<h1>チケット</h1>',html=True)
        self.assertContains(editor,'class="ticket-editor-meta"')
        self.assertContains(editor,'作成日')
        self.assertContains(editor,'作成者')
        self.assertContains(editor,'<dd>member</dd>',html=True)
        self.assertLess(editor.content.index('<h1>チケット</h1>'.encode()),editor.content.index(b'class="ticket-editor-meta"'))
        self.assertContains(editor,'id="comment-preview-button"')
        self.assertContains(editor,'rows="3"')
        self.assertLess(editor.content.index(b'id="comment-form"'),editor.content.index(b'class="card ticket-comments"'))
        response=self.client.post(self.base+'/comments',{'body_markdown':'**引き継ぎ内容**','author_id':self.other.pk})
        self.assertRedirects(response,self.base)
        comment=Comment.objects.get(ticket=self.ticket)
        self.assertEqual(comment.author_id,self.member.pk)
        self.assertEqual(comment.author_snapshot['display_name'],'member')
        self.member.display_name='変更後の表示名'
        self.member.save(update_fields=['display_name'])
        detail=self.client.get(self.base)
        self.assertContains(detail,'member')
        self.assertContains(detail,'<strong>引き継ぎ内容</strong>',html=True)
        event=AuditEvent.objects.get(entity_type='comment',entity_id=comment.pk)
        self.assertEqual(event.actor_id,self.member.pk)
        self.assertEqual(event.ticket_context_id,self.ticket.pk)
        self.assertEqual(event.ticket_context_id,self.ticket.pk)

    def test_comment_requires_project_access_content_and_writable_ticket(self):
        self.assertEqual(self.client.post(self.base+'/comments',{'body_markdown':'   '}).status_code,400)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.base+'/comments',{'body_markdown':'hidden'}).status_code,404)
        self.client.force_login(self.member)
        projects.archive_project(self.system,self.project.pk,True)
        self.assertEqual(self.client.post(self.base+'/comments',{'body_markdown':'blocked'}).status_code,409)

    def test_comment_accepts_any_file_type_and_downloads_only_with_project_access(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(self.base+'/comments', {
                'body_markdown': '',
                'attachments': [SimpleUploadedFile('handoff.pdf', b'%PDF arbitrary'),
                                SimpleUploadedFile('plan.docx', b'office bytes')],
            })
            self.assertEqual(response.status_code, 302)
            comment = Comment.objects.get(ticket=self.ticket)
            attachments = list(comment.attachments.order_by('original_filename'))
            self.assertEqual([a.original_filename for a in attachments], ['handoff.pdf', 'plan.docx'])
            event = AuditEvent.objects.get(entity_type='comment', entity_id=comment.pk, action='create')
            self.assertEqual(len(event.entity_snapshot['attachments']), 2)
            download = self.client.get(f'/attachments/{attachments[0].pk}/content')
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download['Content-Type'], 'application/octet-stream')
            self.assertIn('attachment;', download['Content-Disposition'])
            self.assertEqual(download['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(b''.join(download.streaming_content), b'%PDF arbitrary')
            foreign_client = Client()
            foreign_client.force_login(self.other)
            self.assertEqual(foreign_client.get(f'/attachments/{attachments[0].pk}/content').status_code, 404)
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(self.base+'/delete')
            self.assertFalse(default_storage.exists(attachments[0].storage_key))
            deleted = AuditEvent.objects.get(entity_type='comment', entity_id=comment.pk, action='delete')
            self.assertEqual(len(deleted.entity_snapshot['attachments']), 2)

    def test_comment_upload_requires_content_and_enforces_size_and_count(self):
        empty = self.client.post(self.base+'/comments', {'body_markdown': ''})
        self.assertEqual(empty.status_code, 400)
        too_large = self.client.post(self.base+'/comments', {
            'body_markdown': '', 'attachments': [SimpleUploadedFile('large.bin', b'x'*(10*1024*1024+1))],
        })
        self.assertEqual(too_large.status_code, 400)
        too_many = self.client.post(self.base+'/comments', {
            'body_markdown': '', 'attachments': [SimpleUploadedFile(f'{i}.bin', b'x') for i in range(11)],
        })
        self.assertEqual(too_many.status_code, 400)

    def test_delete_permission_and_nonparticipant_admin(self):
        projects.add_member(self.system,self.project.pk,self.other.pk)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.base+'/edit',self.post_data()).status_code,302)
        self.assertEqual(self.client.post(self.base+'/delete').status_code,403)
        self.client.force_login(self.system)
        self.assertEqual(self.client.post(self.new,self.post_data(title='admin-created')).status_code,302)
        self.assertEqual(self.client.post(self.base+'/delete').status_code,302)

    def test_outsider_cannot_access_or_discover(self):
        self.client.force_login(self.other)
        for url in [self.base,self.base+'/edit',self.base+'/delete',self.new,f'/projects/{self.project.pk}/tickets']:
            self.assertEqual(self.client.get(url).status_code,404)
        for url in [self.base+'/edit',self.base+'/delete',self.new]:
            self.assertEqual(self.client.post(url,self.post_data()).status_code,404)
        self.assertNotContains(self.client.get('/tickets'),'Alpha')
        self.assertEqual(self.client.get('/tickets',{'project_id':self.project.pk}).status_code,400)

    def test_archive_blocks_all_mutations(self):
        projects.archive_project(self.system,self.project.pk,True)
        for url in [self.new,self.base+'/edit',self.base+'/delete']:
            self.assertEqual(self.client.post(url,self.post_data()).status_code,409)
        self.assertContains(self.client.get(self.base),'閲覧専用')
        self.assertNotContains(self.client.get(self.base),'class="button"')
        self.assertContains(self.client.get('/'),'チケット')
        with self.assertRaises(Conflict):
            services.save_ticket(self.member,self.project.pk,self.data,self.ticket.pk)
        with self.assertRaises(Conflict):
            services.delete_ticket(self.member,self.ticket.pk)
        projects.archive_project(self.system,self.project.pk,False)
        self.assertEqual(self.client.post(self.base+'/edit',self.post_data()).status_code,302)

    def test_cross_project_and_invalid_assignee_rejected(self):
        inactive=user('inactive');inactive.is_active=False;inactive.save()
        for changes in [dict(status_id=TicketStatus.objects.filter(project=self.foreign).first().pk),
                        dict(type_id=TicketType.objects.filter(project=self.foreign).first().pk),
                        dict(assignee_id=self.other.pk),dict(assignee_id=inactive.pk),
                        dict(assignee_id=User.objects.get(username='unknown').pk)]:
            self.assertEqual(self.client.post(self.new,self.post_data(**changes)).status_code,400)
            with self.assertRaises(ValidationError):
                services.save_ticket(self.member,self.project.pk,self.data | changes)

    def test_inactive_master_can_only_be_retained(self):
        custom=projects.save_master(self.system,self.project.pk,'statuses','追加')
        services.save_ticket(self.member,self.project.pk,self.data | {'status_id':custom.pk},self.ticket.pk)
        projects.save_master(self.system,self.project.pk,'statuses','追加',False,custom.pk)
        projects.save_master(self.system,self.project.pk,'types','タスク',False,self.data['type_id'])
        self.assertEqual(self.client.post(self.base+'/edit',self.post_data(status_id=custom.pk,title='保持')).status_code,302)
        self.assertEqual(self.client.post(self.new,self.post_data(status_id=custom.pk)).status_code,400)
        with self.assertRaises(ValidationError):
            services.save_ticket(self.member,self.project.pk,self.data | {'status_id':custom.pk})

    def test_validation_dates_lengths_and_immutable_fields(self):
        for values in [dict(title=' '),dict(title='a'*201),dict(description_markdown='a'*100001),dict(priority='other'),dict(start_date='2026-09-29',due_date='2026-09-28'),dict(start_date='bad')]:
            self.assertEqual(self.client.post(self.new,self.post_data(**values)).status_code,400)
        for field in ['project_id','creator_id','parent_id']:
            self.assertEqual(self.client.post(self.new,self.post_data(**{field: self.foreign.pk})).status_code,400)
        self.assertEqual(self.client.post(self.new,self.post_data(start_date='2026-09-28',due_date='2026-09-28')).status_code,302)
        self.assertEqual(self.client.post(self.new,self.post_data(start_date='2026-09-28')).status_code,302)
        self.assertEqual(self.client.get(self.new).context['form'].initial['status_id'],self.data['status_id'])

    def test_audit_failure_rolls_back_create_edit_delete(self):
        count=Ticket.objects.count()
        with patch('tickets.services.record',side_effect=RuntimeError('audit failed')):
            for operation in [lambda:services.save_ticket(self.member,self.project.pk,self.data),
                lambda:services.save_ticket(self.member,self.project.pk,self.data|{'title':'bad'},self.ticket.pk),
                lambda:services.delete_ticket(self.member,self.ticket.pk)]:
                with self.assertRaises(RuntimeError): operation()
        self.assertEqual(Ticket.objects.count(),count)
        self.ticket.refresh_from_db();self.assertEqual(self.ticket.title,'チケット')

    def test_search_and_or_partial_literal_and_mine(self):
        services.save_ticket(self.member,self.project.pk,self.data|{'title':'第二','description_markdown':'needle words','priority':'high','assignee_id':self.manager.pk})
        self.assertEqual(self.client.get('/tickets',{'q':'needle words'}).context['page'].paginator.count,1)
        self.assertEqual(self.client.get('/tickets',{'q':'needle missing'}).context['page'].paginator.count,0)
        self.assertEqual(self.client.get('/tickets',{'q':'%'}).context['page'].paginator.count,0)
        self.assertEqual(self.client.get('/tickets',{'priority':['high','medium']}).context['page'].paginator.count,2)
        self.assertEqual(self.client.get('/tickets',{'priority':['high','medium'],'q':'needle'}).context['page'].paginator.count,1)
        self.assertEqual(self.client.get('/').context['assigned_ticket_count'],1)
        self.assertEqual(self.client.get('/tickets/mine',{'assignee_id':self.manager.pk}).context['page'][0].pk,self.ticket.pk)
        closed=TicketStatus.objects.get(project=self.project,builtin_code='closed')
        services.save_ticket(self.member,self.project.pk,self.data|{'status_id':closed.pk},self.ticket.pk)
        self.assertEqual(self.client.get('/').context['assigned_ticket_count'],1)

    def test_search_dropdown_retains_multiple_selections(self):
        response = self.client.get('/tickets', {'priority':['high','medium']})
        self.assertContains(response, 'class="search-dropdown"', count=5)
        self.assertContains(response, 'name="priority" value="high" checked')
        self.assertContains(response, 'name="priority" value="medium" checked')
        self.assertNotContains(response, '<select')
        self.assertContains(response, 'ticket-search.js')
        self.assertContains(response, '/static/core/app.css?v=20260930-ticket-popup-preview-3')
        self.assertEqual(response.context['page'].paginator.count, 1)

    def test_project_list_is_fixed_while_personal_list_crosses_projects(self):
        other_project=projects.create_project(self.system,'Beta','',[self.manager.pk])
        projects.add_member(self.system,other_project.pk,self.member.pk)
        other_status=TicketStatus.objects.get(project=other_project,builtin_code='open')
        other_type=TicketType.objects.filter(project=other_project).first()
        services.save_ticket(self.member,other_project.pk,self.data|{'title':'別プロジェクト','status_id':other_status.pk,
            'type_id':other_type.pk,'assignee_id':self.member.pk})

        personal=self.client.get('/tickets/mine')
        self.assertEqual(personal.context['page'].paginator.count,2)
        self.assertContains(personal,'プロジェクト')
        for field_name, model in [('status_id',TicketStatus),('type_id',TicketType)]:
            choices=list(personal.context['form'].fields[field_name].choices)
            labels=[label for _,label in choices]
            expected=set(model.objects.filter(project__in=[self.project,other_project]).values_list('name',flat=True))
            self.assertEqual(set(labels),expected)
            self.assertEqual(len(labels),len(set(labels)))
            self.assertFalse(any(self.project.name in label or other_project.name in label for label in labels))
        open_id=next(value for value,label in personal.context['form'].fields['status_id'].choices if label=='未対応')
        same_status=self.client.get('/tickets/mine',{'status_id':open_id})
        self.assertEqual(same_status.context['page'].paginator.count,2)
        scoped=self.client.get(f'/projects/{self.project.pk}/tickets')
        self.assertEqual(scoped.context['page'].paginator.count,1)
        self.assertContains(scoped,'<h1>Alpha</h1>',html=True)
        self.assertNotContains(scoped,'<h1>チケット検索</h1>',html=True)
        self.assertNotContains(scoped,'/projects</a> / Alpha',html=False)
        self.assertNotContains(scoped,f' / {self.project.name} · <a href="/projects/{self.project.pk}/settings"',html=False)
        self.assertNotContains(scoped,'label for="id_project_id"')
        self.assertEqual(self.client.get(f'/projects/{self.project.pk}/tickets',{'project_id':other_project.pk}).status_code,400)

    def test_pagination_preserves_filters_and_stable_order(self):
        Ticket.objects.bulk_create([Ticket(project=self.project,creator=self.member,**self.data) for _ in range(104)])
        Ticket.objects.update(updated_at=timezone.now())
        response=self.client.get('/tickets',{'q':'チケット','page_size':50})
        self.assertEqual(len(response.context['page']),50)
        ids=[t.pk for t in response.context['page']]
        self.assertEqual(ids,sorted(ids,reverse=True))
        self.assertContains(response,'page_size=50&amp;page=2')
        self.assertEqual(len(self.client.get('/tickets?page=3').context['page']),5)
        for value in ['101','0','-1','x']:
            self.assertEqual(self.client.get('/tickets',{'page_size':value}).status_code,400)

    def test_title_header_cycles_sort_and_preserves_filters(self):
        services.save_ticket(self.member,self.project.pk,self.data|{'title':'Sort-Z'})
        services.save_ticket(self.member,self.project.pk,self.data|{'title':'Sort-A'})
        initial=self.client.get('/tickets',{'q':'Sort','page_size':10})
        self.assertEqual(initial.status_code,200)
        self.assertNotContains(initial,'aria-label="昇順"')
        self.assertIn('q=Sort&page_size=10&sort_by=title&sort_order=asc',initial.context['sort_urls']['title'])

        ascending=self.client.get('/tickets',{'q':'Sort','page_size':10,'sort_by':'title','sort_order':'asc'})
        self.assertEqual([ticket.title for ticket in ascending.context['page']],['Sort-A','Sort-Z'])
        self.assertContains(ascending,'aria-label="昇順"')
        self.assertContains(ascending,'name="sort_by" value="title"')
        self.assertContains(ascending,'name="sort_order" value="asc"')
        self.assertIn('sort_by=title&sort_order=asc',ascending.context['query'])
        self.assertIn('q=Sort&page_size=10&sort_by=title&sort_order=desc',ascending.context['sort_urls']['title'])

        descending=self.client.get('/tickets',{'q':'Sort','page_size':10,'sort_by':'title','sort_order':'desc'})
        self.assertEqual([ticket.title for ticket in descending.context['page']],['Sort-Z','Sort-A'])
        self.assertContains(descending,'aria-label="降順"')
        self.assertIn('q=Sort&page_size=10',descending.context['sort_urls']['title'])
        self.assertNotIn('sort_by',descending.context['sort_urls']['title'])
        self.assertEqual(self.client.get('/tickets',{'sort_by':'title','sort_order':'sideways'}).status_code,400)

    def test_every_ticket_column_can_be_sorted(self):
        response=self.client.get('/tickets')
        sortable=['id','title','project','status','type','priority','assignee','start_date','due_date','updated_at']
        html=response.content.decode()
        for field in sortable:
            self.assertIn(f'sort_by={field}&amp;sort_order=asc',html)
            sorted_response=self.client.get('/tickets',{'sort_by':field,'sort_order':'asc'})
            self.assertEqual(sorted_response.status_code,200,field)
            self.assertEqual(sorted_response.context['sort_by'],field)
            self.assertContains(sorted_response,'aria-label="昇順"')

    def test_markdown_preview_matches_detail_and_is_safe(self):
        text='**bold**\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n![img](https://example.com/a.png)'
        html=render_markdown(text)
        self.assertIn('<strong>bold</strong>',html)
        self.assertNotIn('<script',html)
        self.assertNotIn('href="javascript:',html)
        self.assertNotIn('<img',html)
        response=self.client.post('/markdown/preview',{'text':text})
        self.assertEqual(response.json()['html'],html)
        self.assertEqual(self.client.get('/markdown/preview').status_code,405)
        self.assertEqual(self.client.post('/markdown/preview',{'text':'a'*100001}).status_code,400)

    def test_csrf_auth_password_gate_and_methods(self):
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.member)
        for url in [self.new,self.base+'/edit',self.base+'/delete','/markdown/preview']:
            self.assertEqual(secure.post(url,self.post_data()).status_code,403)
        self.client.logout()
        self.assertEqual(self.client.post(self.new,self.post_data()).status_code,401)
        self.assertEqual(self.client.post('/markdown/preview',{'text':'a'}).status_code,401)
        self.member.must_change_password=True
        from datetime import timedelta
        self.member.temporary_password_expires_at=timezone.now()+timedelta(hours=1);self.member.save()
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(self.new,self.post_data()).status_code,403)
        self.assertEqual(self.client.post('/markdown/preview',{'text':'a'}).status_code,403)

    def test_stale_actor_cannot_write(self):
        self.member.is_active=False;self.member.save()
        with self.assertRaises(PermissionDenied):
            services.save_ticket(self.member,self.project.pk,self.data,self.ticket.pk)


class ConcurrentTicketTests(TransactionTestCase):
    def test_archive_and_create_are_serialized(self):
        admin=user('admin',True)
        project=projects.create_project(admin,'Concurrent','',[admin.pk])
        data=dict(title='race',description_markdown='',status_id=TicketStatus.objects.get(project=project,builtin_code='open').pk,
                  type_id=TicketType.objects.filter(project=project).first().pk,priority='medium',assignee_id=None,start_date=None,due_date=None)
        barrier=Barrier(2)
        def run(operation):
            close_old_connections()
            try:
                actor=User.objects.get(pk=admin.pk)
                barrier.wait(timeout=10)
                if operation=='archive': projects.archive_project(actor,project.pk,True)
                else: services.save_ticket(actor,project.pk,data)
                return operation
            except Conflict: return 'conflict'
            finally: connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(run,['archive','create']))
        self.assertIn('archive',results)
        if 'create' in results:
            create=AuditEvent.objects.get(entity_type='ticket',action='create')
            archive=AuditEvent.objects.get(entity_type='project',action='archive')
            self.assertLess(create.pk,archive.pk)
        else: self.assertFalse(Ticket.objects.exists())
        project.refresh_from_db();self.assertTrue(project.is_archived)
