from getpass import getpass
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from accounts.services import create_user


class Command(BaseCommand):
    help = '初回のみ、ID・表示名・非表示パスワードを対話入力して管理者を作成します。'

    def handle(self, *args, **options):
        from accounts.models import User
        if User.objects.filter(is_special=False).exists():
            raise CommandError('初期管理者は作成済みです。')
        try:
            username = input('ユーザーID: ').strip()
            display_name = input('表示名: ').strip()
            password = getpass('初期パスワード（12文字以上）: ')
            if password != getpass('初期パスワード（確認）: '):
                raise CommandError('パスワードが一致しません。')
            create_user(None, {'username': username, 'display_name': display_name}, initial_password=password)
        except (EOFError, KeyboardInterrupt):
            raise CommandError('作成を中止しました。') from None
        except ValidationError as exc:
            raise CommandError('; '.join(exc.messages)) from None
        self.stdout.write(self.style.SUCCESS('初期管理者を作成しました。72時間以内にログインし、パスワードを変更してください。'))
