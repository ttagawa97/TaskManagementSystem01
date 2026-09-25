import secrets
from datetime import timedelta
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone
from .models import AuditEvent, User


class Conflict(ValidationError):
    pass


def lock_users():
    # Serialize user mutations and authentication against role/password changes.
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(810021)')


def snapshot(user):
    return {key: getattr(user, key) for key in ('id', 'username', 'display_name', 'is_system_admin', 'is_active')}


def record(actor, user, action, before=None, metadata=None):
    after = snapshot(user)
    AuditEvent.objects.create(actor=actor, actor_snapshot=snapshot(actor) if actor else {},
        entity_type='user', entity_id=user.pk, entity_snapshot=after, action=action,
        changes={key: {'before': (before or {}).get(key), 'after': value}
                 for key, value in after.items() if (before or {}).get(key) != value},
        metadata=metadata or {})


def fresh_actor(actor, admin=False):
    current = User.objects.get(pk=actor.pk)
    if (not current.is_active or current.is_special or current.must_change_password
            or current.password != actor.password or (admin and not current.is_system_admin)):
        raise PermissionDenied
    return current


def set_temporary(user, raw=None):
    if raw is None:
        while True:
            raw = secrets.token_urlsafe(24)
            try:
                validate_password(raw, user)
                break
            except ValidationError:
                raw = None
    else:
        validate_password(raw, user)
    user.set_password(raw)
    user.must_change_password = True
    user.temporary_password_expires_at = timezone.now() + timedelta(hours=72)
    return raw


def validate_user(user):
    if user.username == 'unknown' or user.is_special:
        raise Conflict('unknownは予約ユーザーです。')
    if User.objects.filter(username=user.username).exclude(pk=user.pk).exists():
        raise Conflict('このユーザーIDは既に使用されています。')
    user.full_clean(exclude=['password', 'last_login', 'temporary_password_expires_at'])


@transaction.atomic
def create_user(actor, values, initial_password=None):
    lock_users()
    if actor is None:
        if User.objects.filter(is_special=False).exists():
            raise Conflict('初期管理者は作成済みです。既存の管理者でログインしてください。')
        values = {**values, 'is_system_admin': True}
    else:
        actor = fresh_actor(actor, admin=True)
    user = User(**values)
    validate_user(user)
    raw = set_temporary(user, initial_password)
    user.save()
    record(actor, user, 'create', metadata={'source': 'initial_admin_command'} if actor is None else {})
    return user, raw


@transaction.atomic
def edit_user(actor, pk, values):
    lock_users()
    actor = fresh_actor(actor, admin=True)
    user = User.objects.get(pk=pk, is_special=False)
    before = snapshot(user)
    if user.is_active and user.is_system_admin and not values['is_system_admin']:
        if not User.objects.filter(is_active=True, is_system_admin=True, is_special=False).exclude(pk=pk).exists():
            raise Conflict('最後の有効なシステム管理者は解除できません。先に別の管理者を指定してください。')
    for key in ('username', 'display_name', 'is_system_admin'):
        setattr(user, key, values[key])
    validate_user(user)
    user.save()
    if snapshot(user) != before:
        record(actor, user, 'update', before)
    return user


@transaction.atomic
def reset_password(actor, pk):
    lock_users()
    actor = fresh_actor(actor, admin=True)
    user = User.objects.get(pk=pk, is_special=False)
    raw = set_temporary(user)
    user.save()
    record(actor, user, 'password_reset', snapshot(user))
    return user, raw


@transaction.atomic
def change_password(actor, old, new):
    lock_users()
    user = User.objects.get(pk=actor.pk)
    if (not user.is_active or user.is_special or user.password != actor.password
            or user.temporary_password_expired):
        raise PermissionDenied
    if not user.check_password(old):
        raise ValidationError('現在のパスワードが正しくありません。')
    validate_password(new, user)
    if user.check_password(new):
        raise ValidationError('現在とは異なるパスワードを指定してください。')
    user.set_password(new)
    user.must_change_password = False
    user.temporary_password_expires_at = None
    user.save()
    record(user, user, 'password_change', snapshot(user))
    return user
