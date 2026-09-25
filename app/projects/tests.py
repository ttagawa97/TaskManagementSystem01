from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, connection, close_old_connections
from django.test import TestCase, TransactionTestCase, Client
from accounts.models import User, AuditEvent
from accounts.services import Conflict
from .models import Project, Membership, TicketStatus, TicketType
from . import services


def user(name, admin=False):
    return User.objects.create(username=name, display_name=name, is_system_admin=admin, must_change_password=False)


class ProjectTests(TestCase):
    def setUp(self):
        self.system = user('system', True)
        self.manager = user('manager')
        self.member = user('member')
        self.outsider = user('outsider')
        self.project = services.create_project(self.system, 'Project A', 'Description', [self.manager.pk])
        services.add_member(self.system, self.project.pk, self.member.pk)
        self.base = f'/projects/{self.project.pk}'
        self.client.force_login(self.system)

    def test_create_initialization_and_idempotence(self):
        self.assertEqual(self.project.memberships.filter(is_project_admin=True).count(), 1)
        self.assertEqual(TicketStatus.objects.filter(project=self.project).count(), 4)
        self.assertEqual(list(TicketType.objects.filter(project=self.project).values_list('name', flat=True)), services.TYPES)
        item = TicketType.objects.filter(project=self.project).first()
        services.save_master(self.system, self.project.pk, 'types', 'renamed', False, item.pk)
        before = AuditEvent.objects.count()
        with transaction.atomic():
            services.lock_users()
            services.initialize_masters(self.system, self.project)
        self.assertEqual(AuditEvent.objects.count(), before)
        self.assertEqual(TicketType.objects.filter(project=self.project).count(), 4)
        response = self.client.post('/projects/new', {'name':'New', 'description':'', 'admins':[self.manager.pk, self.member.pk]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Project.objects.get(name='New').memberships.filter(is_project_admin=True).count(), 2)

    def test_missing_or_invalid_initial_admin_rolls_back(self):
        inactive = user('inactive')
        inactive.is_active = False
        inactive.save()
        for ids in [[], [inactive.pk], [User.objects.get(username='unknown').pk]]:
            with self.assertRaises(ValidationError):
                services.create_project(self.system, 'Bad', '', ids)
        self.assertFalse(Project.objects.filter(name='Bad').exists())
        self.assertEqual(self.client.post('/projects/new', {'name':'Missing'}).status_code, 400)

    def test_visibility_and_member_authorization(self):
        self.client.force_login(self.outsider)
        self.assertNotContains(self.client.get('/projects'), 'Project A')
        for suffix in ['', '/members', '/statuses', '/types']:
            self.assertEqual(self.client.get(self.base+suffix).status_code, 404)
        self.client.force_login(self.member)
        self.assertContains(self.client.get('/projects'), 'Project A')
        self.assertEqual(self.client.get(self.base).status_code, 200)
        self.assertEqual(self.client.post('/projects/new', {}).status_code, 403)
        self.assertEqual(self.client.post(self.base+'/edit', {}).status_code, 403)
        self.assertEqual(self.client.post(self.base+'/members', {'user':self.outsider.pk}).status_code, 403)
        self.assertEqual(self.client.post(self.base+'/statuses/new', {'name':'custom'}).status_code, 403)
        self.assertEqual(self.client.post(self.base+'/archive').status_code, 403)

    def test_nonmember_system_admin_can_manage_masters(self):
        self.assertFalse(self.project.memberships.filter(user=self.system).exists())
        response = self.client.post(self.base+'/statuses/new', {'name':'調査中','is_active':'on'})
        self.assertEqual(response.status_code, 302)
        status = TicketStatus.objects.get(project=self.project, name='調査中')
        self.assertIsNone(status.builtin_code)
        self.assertEqual(self.client.get(self.base+'/statuses').status_code, 200)
        response = self.client.post(f'{self.base}/statuses/{status.pk}', {'name':'保留'})
        self.assertEqual(response.status_code, 302)
        status.refresh_from_db()
        self.assertFalse(status.is_active)
        self.client.post(f'{self.base}/statuses/{status.pk}', {'name':'保留','is_active':'on'})
        status.refresh_from_db()
        self.assertTrue(status.is_active)

    def test_manager_can_add_member_and_manage_but_not_assign_role_or_edit_basic(self):
        self.client.force_login(self.manager)
        response = self.client.post(self.base+'/members', {'user':self.outsider.pk,'is_project_admin':'on'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Membership.objects.get(project=self.project, user=self.outsider).is_project_admin)
        self.assertEqual(self.client.post(f'{self.base}/members/{self.outsider.pk}/role', {'is_project_admin':'on'}).status_code, 403)
        self.assertEqual(self.client.post(self.base+'/edit', {'name':'bad'}).status_code, 403)
        self.assertEqual(self.client.post(self.base+'/types/new', {'name':'Test','is_active':'on'}).status_code, 302)

    def test_last_project_admin_and_audit(self):
        count = AuditEvent.objects.count()
        response = self.client.post(f'{self.base}/members/{self.manager.pk}/role', {})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(AuditEvent.objects.count(), count)
        self.client.post(f'{self.base}/members/{self.member.pk}/role', {'is_project_admin':'on'})
        self.assertEqual(self.client.post(f'{self.base}/members/{self.manager.pk}/role', {}).status_code, 302)
        event = AuditEvent.objects.filter(action='role_change').last()
        self.assertEqual(event.project_id, self.project.pk)
        self.assertEqual(event.changes['is_project_admin'], {'before':True, 'after':False})
        self.assertEqual(event.actor_id, self.system.pk)

    def test_masters_protect_builtins_and_duplicate_names(self):
        status = TicketStatus.objects.filter(project=self.project).first()
        for data in [{'name':'renamed','is_active':'on'}, {'name':status.name}]:
            self.assertEqual(self.client.post(f'{self.base}/statuses/{status.pk}', data).status_code, 409)
        self.assertEqual(self.client.post(self.base+'/statuses/new', {'name':status.name,'is_active':'on'}).status_code, 409)
        item = TicketType.objects.filter(project=self.project).first()
        self.assertEqual(self.client.post(f'{self.base}/types/{item.pk}', {'name':'changed'}).status_code, 302)
        self.assertEqual(self.client.delete(f'{self.base}/types/{item.pk}').status_code, 405)

    def test_cross_project_master_and_member_ids(self):
        other = services.create_project(self.system, 'Project B', '', [self.outsider.pk])
        item = TicketType.objects.filter(project=other).first()
        self.assertEqual(self.client.post(f'{self.base}/types/{item.pk}', {'name':'attack'}).status_code, 404)
        self.assertEqual(self.client.post(f'{self.base}/members/{self.outsider.pk}/role', {'is_project_admin':'on'}).status_code, 404)
        item.refresh_from_db()
        self.assertEqual(item.name, 'タスク')

    def test_archive_blocks_all_management_and_restore_allows_changes(self):
        self.assertContains(self.client.get(self.base+'/archive'), '確認')
        self.project.refresh_from_db()
        self.assertFalse(self.project.is_archived)
        self.assertEqual(self.client.post(self.base+'/archive').status_code, 302)
        self.project.refresh_from_db()
        self.assertIsNotNone(self.project.archived_at)
        item = TicketType.objects.filter(project=self.project).first()
        attempts = [('/edit', {'name':'changed','description':''}), ('/members', {'user':self.outsider.pk}),
            (f'/members/{self.member.pk}/role', {'is_project_admin':'on'}),
            ('/statuses/new', {'name':'custom','is_active':'on'}), (f'/types/{item.pk}', {'name':'changed'})]
        count = AuditEvent.objects.count()
        for suffix,data in attempts:
            self.assertEqual(self.client.post(self.base+suffix,data).status_code, 409)
        self.assertEqual(AuditEvent.objects.count(),count)
        for suffix in ['', '/members', '/statuses', '/types']:
            self.assertEqual(self.client.get(self.base+suffix).status_code,200)
        self.assertNotContains(self.client.get(self.base+'/members'), '追加する参加者')
        self.assertNotContains(self.client.get(self.base+'/types'), '編集・無効化')
        self.assertEqual(self.client.post(self.base+'/unarchive').status_code,302)
        self.assertEqual(self.client.post(self.base+'/edit', {'name':'After','description':''}).status_code,302)

    def test_service_archive_checks_cannot_be_bypassed(self):
        services.archive_project(self.system,self.project.pk,True)
        for operation in [lambda:services.edit_project(self.system,self.project.pk,'bad',''),
                          lambda:services.add_member(self.system,self.project.pk,self.outsider.pk),
                          lambda:services.change_role(self.system,self.project.pk,self.member.pk,True),
                          lambda:services.save_master(self.system,self.project.pk,'types','bad')]:
            with self.assertRaises(Conflict):
                operation()

    def test_audit_failure_rolls_back_entire_project_creation(self):
        count = AuditEvent.objects.count()
        original = services.record
        def fail_on_status(actor,obj,*args):
            if isinstance(obj,TicketStatus):
                raise RuntimeError('audit failure')
            original(actor,obj,*args)
        with patch('projects.services.record',side_effect=fail_on_status):
            with self.assertRaises(RuntimeError):
                services.create_project(self.system,'Rollback','',[self.manager.pk])
        self.assertFalse(Project.objects.filter(name='Rollback').exists())
        self.assertEqual(AuditEvent.objects.count(),count)

    def test_stale_manager_cannot_mutate(self):
        services.change_role(self.system,self.project.pk,self.member.pk,True)
        services.change_role(self.system,self.project.pk,self.manager.pk,False)
        with self.assertRaises(PermissionDenied):
            services.save_master(self.manager,self.project.pk,'types','bad')

    def test_csrf_reserved_users_and_p4_routes(self):
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.system)
        self.assertEqual(secure.post(self.base+'/archive').status_code,403)
        self.assertEqual(self.client.post(self.base+'/members', {'user':User.objects.get(username='unknown').pk}).status_code,400)
        self.assertEqual(self.client.delete(f'{self.base}/members/{self.member.pk}').status_code,404)
        self.assertEqual(self.client.post(f'{self.base}/members/{self.member.pk}/unassign-open-tickets').status_code,404)

    def test_description_escaping_and_pagination(self):
        services.edit_project(self.system,self.project.pk,'Project A','<script>alert(1)</script>')
        self.assertContains(self.client.get(self.base),'&lt;script&gt;')
        Project.objects.bulk_create([Project(name=f'P{i}',created_by=self.system) for i in range(51)])
        self.assertEqual(len(self.client.get('/projects').context['page']),50)
        self.assertEqual(len(self.client.get('/projects?page=2').context['page']),2)


class ConcurrentProjectTests(TransactionTestCase):
    def test_concurrent_admin_removals_preserve_one(self):
        system=user('system',True)
        managers=[user('one'),user('two')]
        project=services.create_project(system,'Concurrent','',[u.pk for u in managers])
        barrier=Barrier(2)
        def remove(pk):
            close_old_connections()
            try:
                actor=User.objects.get(pk=system.pk)
                barrier.wait(timeout=10)
                services.change_role(actor,project.pk,pk,False)
                return 'ok'
            except Conflict:
                return 'conflict'
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(remove,[u.pk for u in managers]))
        self.assertCountEqual(results,['ok','conflict'])
        self.assertEqual(Membership.objects.filter(project=project,is_project_admin=True).count(),1)
