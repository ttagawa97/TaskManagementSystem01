"""Create local secrets once, without printing or overwriting them."""
import os
from pathlib import Path
import secrets

target = Path(__file__).resolve().parent.parent / '.env.development'
content = '\n'.join([
    'POSTGRES_DB=taskmanagement',
    'POSTGRES_USER=taskmanagement',
    f'POSTGRES_PASSWORD={secrets.token_hex(32)}',
    f'DJANGO_SECRET_KEY={secrets.token_hex(48)}',
    '',
])
try:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print('既存の開発設定を保持しました。')
else:
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
    print('開発設定を作成しました。秘密値は表示しません。')
