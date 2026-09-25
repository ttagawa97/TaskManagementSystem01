from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command, CommandError
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone
from .models import AuditEvent, User
from . import services

PASSWORD = 'Test-Only!Pebble6720'
NEW_PASSWORD = 'Test-Only!River8901'


def ready_user(username, admin=False):
    user = User(username=username, display_name=username, is_system_admin=admin, must_change_password=False)
    user.set_password(PASSWORD)
    user.save()
    return user


class AccountTests(TestCase):
    def setUp(self):
        self.admin = ready_user('admin', True)
        self.user = ready_user('member')

    def signin(self, user=None, password=PASSWORD):
        return self.client.post('/auth/login', {'username': (user or self.admin).username, 'password': password})

    def test_login_logout_and_authentication_boundary(self):
        self.assertRedirects(self.client.get('/'), '/auth/login')
        self.assertEqual(self.client.post('/users/new', {}).status_code, 401)
        self.assertEqual(self.signin().status_code, 302)
        self.assertContains(self.client.get('/'), '日本時間')
        self.assertContains(self.client.get('/users'), 'ユーザー管理')
        self.assertEqual(self.client.get('/auth/logout').status_code, 405)
        self.client.post('/auth/logout')
        self.assertRedirects(self.client.get('/users'), '/auth/login')

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/auth/login', {'username': 'admin', 'password': PASSWORD}).status_code, 403)
        client.force_login(self.admin)
        self.assertEqual(client.post('/users/new', {}).status_code, 403)

    def test_regular_user_cannot_manage(self):
        self.signin(self.user)
        for url in ['/users', '/users/new', f'/users/{self.admin.pk}', f'/users/{self.admin.pk}/reset-password']:
            self.assertEqual(self.client.get(url).status_code, 403)
            if url != '/users':
                self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_create_change_and_no_plaintext_retention(self):
        self.signin()
        response = self.client.post('/users/new', {'username': 'new-user', 'display_name': '<script>bad</script>', 'is_active': ''})
        self.assertEqual(response.status_code, 201)
        self.assertIn('no-store', response['Cache-Control'])
        raw = response.context['temporary_password']
        created = User.objects.get(username='new-user')
        self.assertTrue(created.is_active)
        self.assertTrue(created.check_password(raw))
        self.assertContains(response, '&lt;script&gt;', status_code=201)
        self.assertAlmostEqual((created.temporary_password_expires_at-timezone.now()).total_seconds(), 72*3600, delta=5)
        self.client.post('/auth/logout')
        self.signin(created, raw)
        self.assertRedirects(self.client.get('/'), '/auth/password/change')
        self.assertEqual(self.client.post('/users/new', {}).status_code, 403)
        response = self.client.post('/auth/password/change', {'old_password': raw, 'new_password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD})
        self.assertRedirects(response, '/')
        created.refresh_from_db()
        self.assertFalse(created.must_change_password)
        self.assertIsNone(created.temporary_password_expires_at)
        self.assertTrue(created.check_password(NEW_PASSWORD))
        logs = str(list(AuditEvent.objects.values()))
        for secret in [raw, NEW_PASSWORD, created.password]:
            self.assertNotIn(secret, logs)
        self.assertEqual(list(AuditEvent.objects.values_list('action', flat=True)), ['create', 'password_change'])

    def test_expired_temporary_password_and_existing_session(self):
        created, raw = services.create_user(self.admin, {'username':'temporary', 'display_name':'temporary'})
        self.signin(created, raw)
        User.objects.filter(pk=created.pk).update(temporary_password_expires_at=timezone.now())
        response = self.client.post('/auth/password/change', {'old_password': raw, 'new_password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.signin(created, raw).status_code, 401)
        target, new_raw = services.reset_password(self.admin, created.pk)
        self.assertFalse(target.check_password(raw))
        self.assertEqual(self.signin(target, new_raw).status_code, 302)

    def test_inactive_unknown_and_disabled_existing_session(self):
        unknown = User.objects.get(username='unknown')
        self.assertFalse(unknown.has_usable_password())
        self.assertFalse(unknown.is_active)
        self.assertTrue(unknown.is_special)
        self.assertEqual(self.signin(unknown).status_code, 401)
        self.signin(self.user)
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertRedirects(self.client.get('/'), '/auth/login')
        self.assertEqual(self.signin(self.user).status_code, 401)

    def test_absolute_session_expiry_survives_activity_and_password_change(self):
        self.signin()
        expiry = self.client.session.get_expiry_date()
        self.assertAlmostEqual((expiry-timezone.now()).total_seconds(), 86400, delta=5)
        self.client.get('/users')
        self.client.post('/auth/password/change', {'old_password': PASSWORD, 'new_password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD})
        self.assertEqual(self.client.session.get_expiry_date(), expiry)
        with patch('django.utils.timezone.now', return_value=expiry+timedelta(seconds=1)):
            self.assertRedirects(self.client.get('/'), '/auth/login')

    def test_password_validation(self):
        self.signin(self.user)
        for new in ['short', '12345678901234', '0r968ji9ufj6', PASSWORD]:
            response = self.client.post('/auth/password/change', {'old_password': PASSWORD, 'new_password': new, 'confirm_password': new})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post('/auth/password/change', {'old_password': PASSWORD, 'new_password': NEW_PASSWORD, 'confirm_password': 'different'}).status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_reset_invalidates_other_sessions_and_is_confirmation(self):
        other = Client()
        other.post('/auth/login', {'username': self.user.username, 'password': PASSWORD})
        self.signin()
        before = self.user.password
        self.assertContains(self.client.get(f'/users/{self.user.pk}/reset-password'), '初期化の確認')
        self.user.refresh_from_db()
        self.assertEqual(before, self.user.password)
        response = self.client.post(f'/users/{self.user.pk}/reset-password')
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(other.get('/'), '/auth/login')
        self.assertEqual(self.client.get(f'/users/{self.user.pk}/reset-password').context.get('temporary_password'), None)

    def test_last_admin_and_mass_assignment(self):
        self.signin()
        data = {'username':'admin', 'display_name':'変更', 'is_active':'', 'is_special':'on'}
        self.assertEqual(self.client.post(f'/users/{self.admin.pk}', data).status_code, 409)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_system_admin)
        self.assertTrue(self.admin.is_active)
        self.assertFalse(self.admin.is_special)
        self.assertEqual(AuditEvent.objects.count(), 0)
        ready_user('second', True)
        self.assertEqual(self.client.post(f'/users/{self.admin.pk}', data).status_code, 302)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_system_admin)
        self.assertEqual(self.client.get('/users').status_code, 403)
        self.assertEqual(AuditEvent.objects.get().changes['is_system_admin'], {'before': True, 'after': False})

    def test_duplicate_reserved_id_and_validation(self):
        self.signin()
        for username, status in [('admin',409), ('unknown',409), ('bad name',400), ('',400)]:
            response = self.client.post('/users/new', {'username':username,'display_name':'name'})
            self.assertEqual(response.status_code, status)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_audit_failure_rolls_back_change(self):
        with patch('accounts.services.record', side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):
                services.edit_user(self.admin, self.user.pk, {'username': 'changed', 'display_name':'changed', 'is_system_admin':False})
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'member')

    def test_stale_actor_cannot_mutate(self):
        User.objects.filter(pk=self.admin.pk).update(is_system_admin=False)
        with self.assertRaises(PermissionDenied):
            services.reset_password(self.admin, self.user.pk)

    def test_pagination_and_unavailable_operations(self):
        User.objects.bulk_create([User(username=f'bulk{i}', display_name=f'bulk{i}') for i in range(51)])
        self.signin()
        self.assertEqual(len(self.client.get('/users').context['page']), 50)
        self.assertEqual(len(self.client.get('/users?page=2').context['page']), 3)
        self.assertEqual(self.client.post(f'/users/{self.user.pk}/deactivate').status_code, 404)
        self.assertEqual(self.client.delete(f'/users/{self.user.pk}').status_code, 405)


class InitialAdminTests(TestCase):
    def test_command_and_no_overwrite(self):
        output = StringIO()
        with patch('builtins.input', side_effect=['first-admin', '初期管理者']), patch('accounts.management.commands.create_initial_admin.getpass', return_value=PASSWORD):
            call_command('create_initial_admin', stdout=output)
        user = User.objects.get(username='first-admin')
        self.assertTrue(user.is_system_admin)
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotIn(PASSWORD, output.getvalue())
        self.assertEqual(AuditEvent.objects.get().metadata, {'source':'initial_admin_command'})
        with self.assertRaises(CommandError):
            call_command('create_initial_admin', stdout=output)
        self.assertEqual(User.objects.filter(is_special=False).count(), 1)


class ConcurrentAdminTests(TransactionTestCase):
    def test_concurrent_demotions_leave_one_admin(self):
        admins = [ready_user('admin-one', True), ready_user('admin-two', True)]
        def demote(pk):
            close_old_connections()
            try:
                actor = User.objects.get(pk=pk)
                services.edit_user(actor, pk, {'username': actor.username, 'display_name': actor.display_name, 'is_system_admin':False})
                return 'ok'
            except services.Conflict:
                return 'conflict'
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(demote, [u.pk for u in admins]))
        self.assertCountEqual(results, ['ok', 'conflict'])
        self.assertEqual(User.objects.filter(is_active=True, is_system_admin=True).count(), 1)
        self.assertEqual(AuditEvent.objects.count(), 1)
