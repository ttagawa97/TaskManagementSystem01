from django.db import migrations


def create_unknown(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.using(schema_editor.connection.alias).get_or_create(username='unknown', defaults={
        'display_name': 'unknown', 'password': '!', 'is_active': False,
        'is_system_admin': False, 'is_special': True, 'must_change_password': False,
    })


class Migration(migrations.Migration):
    dependencies = [('accounts', '0001_initial')]
    operations = [migrations.RunPython(create_unknown, migrations.RunPython.noop)]
