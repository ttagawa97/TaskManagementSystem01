import django.db.models.deletion
import django.core.validators
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('tickets', '0002_comment'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='comment', name='body_markdown',
            field=models.TextField(blank=True, validators=[django.core.validators.MaxLengthValidator(100000)]),
        ),
        migrations.CreateModel(
            name='Attachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('wiki_page_id', models.BigIntegerField(blank=True, null=True)),
                ('original_filename', models.CharField(max_length=255)),
                ('storage_key', models.CharField(max_length=255, unique=True)),
                ('media_type', models.CharField(default='application/octet-stream', max_length=255)),
                ('size_bytes', models.PositiveBigIntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('comment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='tickets.comment')),
                ('ticket', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='tickets.ticket')),
                ('uploader', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='uploaded_attachments', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'attachments', 'ordering': ['created_at', 'id']},
        ),
        migrations.AddConstraint(
            model_name='attachment',
            constraint=models.CheckConstraint(
                condition=(models.Q(ticket__isnull=False, comment__isnull=True, wiki_page_id__isnull=True)
                    | models.Q(ticket__isnull=True, comment__isnull=False, wiki_page_id__isnull=True)
                    | models.Q(ticket__isnull=True, comment__isnull=True, wiki_page_id__isnull=False)),
                name='attachment_single_owner'),
        ),
    ]
