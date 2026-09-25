from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from accounts.models import User, AuditEvent
from accounts.services import Conflict, fresh_actor, lock_users, snapshot as user_snapshot
from .models import Project, Membership, TicketStatus, TicketType

BUILTINS = [('未対応', 'open'), ('処理中', 'in_progress'), ('処理済み', 'resolved'), ('完了', 'closed')]
TYPES = ['タスク', 'バグ', '要望', 'その他']
MASTER_MODELS = {'statuses': TicketStatus, 'types': TicketType}


def visible_projects(user):
    projects = Project.objects.all()
    if not user.is_system_admin:
        projects = projects.filter(memberships__user=user)
    return projects.order_by('-updated_at', '-id')


def can_manage(user, project):
    return user.is_system_admin or Membership.objects.filter(project=project, user=user, is_project_admin=True).exists()


def get_project(user, pk):
    return get_object_or_404(visible_projects(user), pk=pk)


def snapshot(obj):
    if isinstance(obj, Project):
        keys = ['id', 'name', 'description', 'is_archived', 'created_by_id', 'archived_at']
    elif isinstance(obj, Membership):
        keys = ['id', 'project_id', 'user_id', 'is_project_admin']
    else:
        keys = ['id', 'project_id', 'name', 'is_active', 'sort_order']
        if isinstance(obj, TicketStatus):
            keys.append('builtin_code')
    return {key: (getattr(obj, key).isoformat() if hasattr(getattr(obj, key), 'isoformat') else getattr(obj, key)) for key in keys}


def record(actor, obj, action, before=None):
    after = snapshot(obj)
    AuditEvent.objects.create(actor=actor, actor_snapshot=user_snapshot(actor),
        project_id=obj.pk if isinstance(obj, Project) else obj.project_id,
        entity_type={Project:'project', Membership:'membership', TicketStatus:'ticket_status', TicketType:'ticket_type'}[type(obj)],
        entity_id=obj.pk, entity_snapshot=after, action=action,
        changes={k: {'before': (before or {}).get(k), 'after': v} for k,v in after.items() if (before or {}).get(k) != v})


def authorized(actor, pk, system_only=False):
    lock_users()
    actor = fresh_actor(actor, admin=system_only)
    project = get_object_or_404(Project.objects.select_for_update(), pk=pk)
    if not can_manage(actor, project):
        raise PermissionDenied
    return actor, project


def require_writable(project):
    if project.is_archived:
        raise Conflict('アーカイブ中は変更できません。先にアーカイブを解除してください。')


def valid_name(value, maximum):
    value = value.strip()
    if not value or len(value) > maximum:
        raise ValidationError(f'名称は1〜{maximum}文字で入力してください。')
    return value


@transaction.atomic
def create_project(actor, name, description, admin_ids):
    lock_users()
    actor = fresh_actor(actor, admin=True)
    ids = set(admin_ids)
    admins = list(User.objects.filter(pk__in=ids, is_active=True, is_special=False))
    if not ids or len(admins) != len(ids):
        raise ValidationError('有効なプロジェクト管理者を1名以上指定してください。')
    project = Project(name=valid_name(name, 200), description=description, created_by=actor)
    project.full_clean(exclude=['archived_at'])
    project.save()
    record(actor, project, 'create')
    for user in admins:
        member = Membership.objects.create(project=project, user=user, is_project_admin=True)
        record(actor, member, 'create')
    initialize_masters(actor, project)
    return project


def initialize_masters(actor, project):
    # Caller holds the project/user mutation lock inside its transaction.
    for index, (name, code) in enumerate(BUILTINS):
        obj, created = TicketStatus.objects.get_or_create(project=project, builtin_code=code, defaults={'name':name, 'sort_order':index})
        if created:
            record(actor, obj, 'create')
    # Only initialize types for a new project; this helper is idempotent and does
    # not recreate renamed or disabled types on later calls.
    if not TicketType.objects.filter(project=project).exists():
        for index, name in enumerate(TYPES):
            record(actor, TicketType.objects.create(project=project, name=name, sort_order=index), 'create')


@transaction.atomic
def edit_project(actor, pk, name, description):
    actor, project = authorized(actor, pk, system_only=True)
    require_writable(project)
    before = snapshot(project)
    project.name = valid_name(name, 200)
    project.description = description
    project.full_clean(exclude=['archived_at'])
    project.save()
    if before != snapshot(project):
        record(actor, project, 'update', before)
    return project


@transaction.atomic
def add_member(actor, pk, user_id):
    actor, project = authorized(actor, pk)
    require_writable(project)
    user = get_object_or_404(User, pk=user_id, is_active=True, is_special=False)
    if Membership.objects.filter(project=project, user=user).exists():
        raise Conflict('このユーザーは既に参加しています。')
    member = Membership.objects.create(project=project, user=user)
    record(actor, member, 'create')
    return member


@transaction.atomic
def change_role(actor, pk, user_id, is_admin):
    actor, project = authorized(actor, pk, system_only=True)
    require_writable(project)
    member = get_object_or_404(Membership, project=project, user_id=user_id)
    if is_admin and not User.objects.filter(pk=user_id, is_active=True, is_special=False).exists():
        raise Conflict('有効なユーザーのみ管理者に指定できます。')
    if not is_admin and member.is_project_admin:
        if not Membership.objects.filter(project=project, is_project_admin=True, user__is_active=True, user__is_special=False).exclude(pk=member.pk).exists():
            raise Conflict('最後の有効なプロジェクト管理者は解除できません。先に別の管理者を指定してください。')
    before = snapshot(member)
    member.is_project_admin = is_admin
    member.save()
    if before != snapshot(member):
        record(actor, member, 'role_change', before)
    return member


@transaction.atomic
def archive_project(actor, pk, archived):
    actor, project = authorized(actor, pk)
    before = snapshot(project)
    if project.is_archived != archived:
        project.is_archived = archived
        project.archived_at = timezone.now() if archived else None
        project.save()
        record(actor, project, 'archive' if archived else 'unarchive', before)
    return project


@transaction.atomic
def save_master(actor, pk, kind, name, is_active=True, master_id=None):
    actor, project = authorized(actor, pk)
    require_writable(project)
    Model = MASTER_MODELS[kind]
    obj = get_object_or_404(Model, pk=master_id, project=project) if master_id else Model(project=project)
    before = snapshot(obj) if obj.pk else None
    name = valid_name(name, 100)
    if isinstance(obj, TicketStatus) and obj.builtin_code and (name != obj.name or not is_active):
        raise Conflict('必須ステータスの名称変更・無効化はできません。')
    if Model.objects.filter(project=project, name=name).exclude(pk=obj.pk).exists():
        raise Conflict('同じ名称が既に登録されています。')
    if not obj.pk:
        from django.db.models import Max
        maximum = Model.objects.filter(project=project).aggregate(value=Max('sort_order'))['value']
        obj.sort_order = (maximum if maximum is not None else -1) + 1
    obj.name, obj.is_active = name, is_active
    obj.save()
    if before != snapshot(obj):
        record(actor, obj, 'update' if before else 'create', before)
    return obj
