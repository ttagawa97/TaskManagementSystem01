from unittest.mock import patch
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


class PageTests(TestCase):
    def setUp(self):
        from accounts.models import User
        self.user = User.objects.create(username="page-user", display_name="画面確認", must_change_password=False)
        self.client.force_login(self.user)
    def test_localized_home_and_timezone(self):
        response = self.client.get('/')
        self.assertContains(response, 'lang="ja"')
        self.assertContains(response, '日本時間')
        self.assertContains(response, 'ダッシュボード')
        self.assertEqual(timezone.get_current_timezone_name(), 'Asia/Tokyo')

    def test_dashboard_lists_projects_and_assigned_tickets(self):
        from projects import services as project_services
        from projects.models import TicketStatus, TicketType
        from tickets import services as ticket_services
        self.user.is_system_admin = True
        self.user.save(update_fields=['is_system_admin'])
        project = project_services.create_project(self.user, 'Dashboard project', '', [self.user.pk])
        ticket_services.save_ticket(self.user, project.pk, {
            'title':'My assigned ticket', 'description_markdown':'',
            'status_id':TicketStatus.objects.get(project=project, builtin_code='open').pk,
            'type_id':TicketType.objects.filter(project=project).first().pk,
            'priority':'medium', 'assignee_id':self.user.pk, 'start_date':None, 'due_date':None,
        })
        response = self.client.get('/')
        self.assertContains(response, f'href="/projects/{project.pk}/tickets"')
        self.assertContains(response, 'My assigned ticket')
        self.assertEqual(response.context['assigned_ticket_count'], 1)
        project_screen = self.client.get(f'/projects/{project.pk}/tickets')
        self.assertContains(project_screen, 'href="/"')
        self.assertContains(project_screen, f'href="/projects/{project.pk}/settings"')

    def test_dashboard_updates_cover_created_current_and_past_assignments(self):
        from accounts.models import User
        from projects import services as project_services
        from projects.models import TicketStatus, TicketType
        from tickets import services as ticket_services
        system = User.objects.create(username='dashboard-system', display_name='システム', is_system_admin=True,
                                     must_change_password=False)
        manager = User.objects.create(username='dashboard-manager', display_name='管理者', must_change_password=False)
        project = project_services.create_project(system, 'Visible project', '', [manager.pk])
        project_services.add_member(system, project.pk, self.user.pk)
        status = TicketStatus.objects.get(project=project, builtin_code='open')
        ticket_type = TicketType.objects.filter(project=project).first()
        common = {'description_markdown':'', 'status_id':status.pk, 'type_id':ticket_type.pk,
                  'priority':'medium', 'start_date':None, 'due_date':None}

        created_by_me = ticket_services.save_ticket(self.user, project.pk,
            common | {'title':'作成チケット', 'assignee_id':manager.pk})
        formerly_assigned = ticket_services.save_ticket(manager, project.pk,
            common | {'title':'過去担当チケット', 'assignee_id':self.user.pk})
        ticket_services.save_ticket(manager, project.pk,
            common | {'title':'過去担当チケット', 'assignee_id':manager.pk}, formerly_assigned.pk)
        currently_assigned = ticket_services.save_ticket(manager, project.pk,
            common | {'title':'現在担当チケット', 'assignee_id':self.user.pk})
        unrelated = ticket_services.save_ticket(manager, project.pk,
            common | {'title':'無関係チケット', 'assignee_id':manager.pk})
        outsider = User.objects.create(username='dashboard-outsider', display_name='外部ユーザー', must_change_password=False)
        hidden_project = project_services.create_project(system, 'Hidden project', '', [outsider.pk])
        hidden_status = TicketStatus.objects.get(project=hidden_project, builtin_code='open')
        hidden_type = TicketType.objects.filter(project=hidden_project).first()
        invisible = ticket_services.save_ticket(outsider, hidden_project.pk,
            common | {'title':'閲覧不可プロジェクト', 'status_id':hidden_status.pk,
                      'type_id':hidden_type.pk, 'assignee_id':outsider.pk})

        response = self.client.get('/')
        event_ids = {event.ticket_context_id for event in response.context['update_events']}
        self.assertIn(created_by_me.pk, event_ids)
        self.assertIn(formerly_assigned.pk, event_ids)
        self.assertIn(currently_assigned.pk, event_ids)
        self.assertNotIn(unrelated.pk, event_ids)
        self.assertNotIn(invisible.pk, event_ids)
        self.assertContains(response, '過去担当チケット')
        self.assertContains(response, '更新者')

    def test_unknown_route_is_safe_404(self):
        response = self.client.get('/missing/')
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'ページが見つかりません', status_code=404)

    def test_post_to_readonly_routes_is_rejected(self):
        for url in ['/', '/health/']:
            self.assertEqual(self.client.post(url).status_code, 405)


class DatabaseHealthTests(TestCase):
    def test_health_failure_does_not_leak_details(self):
        with patch('core.views.connection.cursor', side_effect=DatabaseError('SECRET_DB_DETAILS')):
            response = self.client.get('/health/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'unavailable'})
        self.assertNotContains(response, 'SECRET_DB_DETAILS', status_code=503)

    def test_health_uses_postgresql(self):
        from django.db import connection
        self.assertEqual(connection.vendor, 'postgresql')
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
