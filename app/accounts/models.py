from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class User(AbstractBaseUser):
    username = models.CharField('ユーザーID', max_length=150, unique=True, validators=[UnicodeUsernameValidator()])
    display_name = models.CharField('表示名', max_length=150)
    password = models.CharField(max_length=128, db_column='password_hash')
    is_active = models.BooleanField(default=True)
    is_system_admin = models.BooleanField('システム管理者', default=False)
    is_special = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=True)
    temporary_password_expires_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = BaseUserManager()
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['display_name']

    class Meta:
        db_table = 'users'
        constraints = [models.CheckConstraint(
            condition=(Q(is_special=True, username='unknown', is_active=False, is_system_admin=False)
                       | (Q(is_special=False) & ~Q(username='unknown'))), name='reserved_unknown')]

    @property
    def temporary_password_expired(self):
        return self.must_change_password and (self.temporary_password_expires_at is None
            or timezone.now() >= self.temporary_password_expires_at)


class AuditEvent(models.Model):
    occurred_at = models.DateTimeField(default=timezone.now)
    actor = models.ForeignKey(User, null=True, on_delete=models.PROTECT)
    actor_snapshot = models.JSONField(default=dict)
    project_id = models.BigIntegerField(null=True)
    entity_type = models.CharField(max_length=40)
    entity_id = models.BigIntegerField()
    entity_snapshot = models.JSONField(default=dict)
    action = models.CharField(max_length=40)
    changes = models.JSONField(default=dict)
    ticket_context_id = models.BigIntegerField(null=True)
    metadata = models.JSONField(default=dict)

    class Meta:
        db_table = 'audit_events'
        indexes = [models.Index(fields=['entity_type', 'entity_id', 'occurred_at'])]
