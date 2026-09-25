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
        self.assertEqual(timezone.get_current_timezone_name(), 'Asia/Tokyo')

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
