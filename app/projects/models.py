from django.conf import settings
from django.db import models


class Project(models.Model):
    name = models.CharField('プロジェクト名', max_length=200)
    description = models.TextField('説明', blank=True, max_length=10000)
    is_archived = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'projects'


class Membership(models.Model):
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    is_project_admin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'memberships'
        constraints = [models.UniqueConstraint(fields=['project', 'user'], name='unique_project_member')]


class Master(models.Model):
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    name = models.CharField('名称', max_length=100)
    is_active = models.BooleanField('有効', default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['sort_order', 'id']


class TicketStatus(Master):
    builtin_code = models.CharField(max_length=20, null=True)

    class Meta(Master.Meta):
        db_table = 'ticket_statuses'
        constraints = [models.UniqueConstraint(fields=['project', 'name'], name='unique_status_name'),
                       models.UniqueConstraint(fields=['project', 'builtin_code'], name='unique_builtin_status')]


class TicketType(Master):
    class Meta(Master.Meta):
        db_table = 'ticket_types'
        constraints = [models.UniqueConstraint(fields=['project', 'name'], name='unique_type_name')]
