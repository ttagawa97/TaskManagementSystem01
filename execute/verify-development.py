"""Verify the approved local development environment, including restart persistence."""
from pathlib import Path
import subprocess
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ['docker', 'compose', '--env-file', str(ROOT / '.env.development'),
           '-f', str(ROOT / 'compose.development.yaml')]


def run(*args):
    return subprocess.check_output([*COMPOSE, *args], cwd=ROOT, text=True).strip()


def shell(code):
    return run('exec', '-T', 'app', 'python', 'manage.py', 'shell', '-c', code)


def http_checks():
    for path, needle in [('/', 'タスク管理'), ('/health/', '"ok"'), ('/static/core/app.css', '#F8FAFC')]:
        with urllib.request.urlopen('http://127.0.0.1:8000' + path, timeout=10) as response:
            assert response.status == 200
            assert needle in response.read().decode()


http_checks()
assert run('port', 'app', '8000') == '127.0.0.1:8000'
probe = 'p1_' + uuid.uuid4().hex
imports = 'from django.contrib.contenttypes.models import ContentType; from pathlib import Path; '
try:
    shell(imports + f"ContentType.objects.create(app_label='{probe}', model='persistence_probe'); Path('/media/{probe}').write_text('{probe}')")
    run('restart')
    run('up', '-d', '--wait', '--wait-timeout', '90')
    shell(imports + f"assert ContentType.objects.filter(app_label='{probe}', model='persistence_probe').count()==1; assert Path('/media/{probe}').read_text()=='{probe}'")
    http_checks()
    print('PASS: HTTP home, CSS, DB health, loopback binding, DB and image volume persistence after restart')
finally:
    shell(imports + f"ContentType.objects.filter(app_label='{probe}', model='persistence_probe').delete(); Path('/media/{probe}').unlink(missing_ok=True)")

print(shell("import platform, django, psycopg; from django.db import connection; print('Python', platform.python_version(), 'Django', django.get_version(), 'psycopg', psycopg.__version__); print('PostgreSQL', connection.pg_version)"))
