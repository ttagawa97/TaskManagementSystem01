from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename
from uuid import uuid4
import mimetypes
from accounts.models import User, AuditEvent
from accounts.services import Conflict, lock_users, fresh_actor, snapshot as actor_snapshot
from projects.models import Project, Membership, TicketStatus, TicketType
from projects.services import visible_projects, can_manage, require_writable
from .models import Attachment, Comment, Ticket

FIELDS = ('title', 'description_markdown', 'status_id', 'type_id', 'priority', 'assignee_id', 'start_date', 'due_date')


def visible_tickets(actor):
    return Ticket.objects.filter(project__in=visible_projects(actor)).select_related('project', 'status', 'type', 'assignee', 'creator')


def recent_related_updates(actor, limit=20):
    projects = visible_projects(actor)
    visible_ids = projects.values_list('pk', flat=True)
    current_relations = Ticket.objects.filter(project__in=projects).filter(
        Q(creator_id=actor.pk) | Q(assignee_id=actor.pk)
    ).values_list('pk', flat=True)
    ticket_events = AuditEvent.objects.filter(
        entity_type='ticket', project_id__in=visible_ids, ticket_context_id__isnull=False,
    )
    historical_relations = ticket_events.filter(
        Q(entity_snapshot__creator_id=actor.pk)
        | Q(entity_snapshot__assignee_id=actor.pk)
        | Q(changes__assignee_id__before=actor.pk)
        | Q(changes__assignee_id__after=actor.pk)
    ).values_list('ticket_context_id', flat=True)
    related_ids = set(current_relations).union(historical_relations)
    active_related_ids = Ticket.objects.filter(project__in=projects, pk__in=related_ids).values_list('pk', flat=True)
    events = ticket_events.filter(ticket_context_id__in=active_related_ids).order_by('-occurred_at', '-pk')[:limit]
    labels = {'create':'作成', 'update':'更新', 'delete':'削除'}
    result = list(events)
    for event in result:
        event.action_display = labels.get(event.action, event.action)
    return result


def get_ticket(actor, pk):
    return get_object_or_404(visible_tickets(actor), pk=pk)


def can_delete(actor, ticket):
    return actor.pk == ticket.creator_id or can_manage(actor, ticket.project)


def snapshot(ticket):
    return {k: (getattr(ticket, k).isoformat() if hasattr(getattr(ticket, k), 'isoformat') else getattr(ticket, k))
            for k in ('id', 'project_id', 'creator_id', 'parent_id', *FIELDS)}


def record(actor, ticket, action, before=None, metadata=None):
    after = {} if action == 'delete' else snapshot(ticket)
    old = before or {}
    AuditEvent.objects.create(actor=actor, actor_snapshot=actor_snapshot(actor), project_id=ticket.project_id,
        entity_type='ticket', entity_id=ticket.pk, entity_snapshot=snapshot(ticket), action=action,
        ticket_context_id=ticket.pk, metadata=metadata or {},
        changes={k: {'before': old.get(k), 'after': after.get(k)} for k in old.keys() | after.keys() if old.get(k) != after.get(k)})


def writable_project(actor, pk):
    lock_users()
    actor = fresh_actor(actor)
    project = get_object_or_404(Project.objects.select_for_update().filter(pk__in=visible_projects(actor).values('pk')), pk=pk)
    require_writable(project)
    return actor, project


@transaction.atomic
def save_ticket(actor, project_id, data, ticket_id=None):
    actor, project = writable_project(actor, project_id)
    ticket = get_object_or_404(Ticket.objects.select_for_update(), pk=ticket_id, project=project) if ticket_id else Ticket(project=project, creator=actor)
    before = snapshot(ticket) if ticket.pk else None
    # Parent controls are introduced at the next P4 checkpoint, never accepted early.
    if set(data) - set(FIELDS):
        raise ValidationError('変更できない項目が指定されています。')
    for key in FIELDS:
        if key in data:
            setattr(ticket, key, data[key])
    ticket.title = ticket.title.strip()
    if not ticket.title:
        raise ValidationError('タイトルを入力してください。')
    for field, model in [('status', TicketStatus), ('type', TicketType)]:
        value = getattr(ticket, field + '_id')
        master = model.objects.filter(pk=value, project=project).first()
        if master is None or (not master.is_active and (before is None or before[field + '_id'] != value)):
            raise ValidationError('同じプロジェクトの有効なステータス・種別を指定してください。')
        setattr(ticket, field, master)
    if ticket.assignee_id:
        if not User.objects.filter(pk=ticket.assignee_id, is_active=True, is_special=False, membership__project=project).exists():
            raise ValidationError('担当者はこのプロジェクトの有効な参加者から選択してください。')
    if ticket.start_date and ticket.due_date and ticket.start_date > ticket.due_date:
        raise ValidationError('期限は開始日以降にしてください。')
    ticket.full_clean()
    ticket.save()
    if before != snapshot(ticket):
        record(actor, ticket, 'update' if before else 'create', before)
    return ticket


@transaction.atomic
def create_comment(actor, ticket_id, body_markdown, files=()):
    files = list(files)
    if not body_markdown.strip() and not files:
        raise ValidationError('コメント本文または添付ファイルを指定してください。')
    if len(files) > 10 or any(f.size > 10 * 1024 * 1024 for f in files):
        raise ValidationError('添付ファイルは10個まで、1個あたり10 MiB以下にしてください。')
    ticket = get_ticket(actor, ticket_id)
    actor, project = writable_project(actor, ticket.project_id)
    ticket = get_object_or_404(Ticket.objects.select_for_update(), pk=ticket_id, project=project)
    comment = Comment(ticket=ticket, author=actor, author_snapshot=actor_snapshot(actor),
                      body_markdown=body_markdown)
    comment.full_clean()
    comment.save()
    stored_keys = []
    attachment_rows = []
    try:
        for uploaded in files:
            name = get_valid_filename(uploaded.name.replace('\\', '/').split('/')[-1])[:255] or 'attachment'
            key = default_storage.save(f'comment-attachments/{uuid4().hex}', uploaded)
            stored_keys.append(key)
            media_type = mimetypes.guess_type(name)[0] or 'application/octet-stream'
            attachment_rows.append(Attachment(comment=comment, uploader=actor, original_filename=name,
                storage_key=key, media_type=media_type, size_bytes=uploaded.size))
        Attachment.objects.bulk_create(attachment_rows)
    except Exception:
        for key in stored_keys:
            default_storage.delete(key)
        raise
    try:
        attachment_metadata = [{'id': item.pk, 'filename': item.original_filename, 'size_bytes': item.size_bytes}
                               for item in comment.attachments.all()]
        snapshot = {'id': comment.pk, 'ticket_id': ticket.pk, 'author_id': actor.pk,
                    'author_snapshot': comment.author_snapshot, 'body_markdown': comment.body_markdown,
                    'attachments': attachment_metadata}
        AuditEvent.objects.create(actor=actor, actor_snapshot=actor_snapshot(actor), project_id=project.pk,
            entity_type='comment', entity_id=comment.pk, entity_snapshot=snapshot, action='create',
            changes={'body_markdown': {'before': None, 'after': comment.body_markdown},
                     'attachments': {'before': None, 'after': attachment_metadata}},
            ticket_context_id=ticket.pk)
    except Exception:
        for key in stored_keys:
            default_storage.delete(key)
        raise
    return comment


@transaction.atomic
def delete_ticket(actor, pk):
    # Project IDs cannot change, so resolve before locking, then re-read the ticket.
    project_id = get_ticket(actor, pk).project_id
    actor, project = writable_project(actor, project_id)
    ticket = get_object_or_404(Ticket.objects.select_for_update(), pk=pk, project=project)
    if not can_delete(actor, ticket):
        raise PermissionDenied
    if ticket.children.exists():
        raise Conflict('子チケットがあるため削除できません。先に子の削除または関係解除が必要です。')
    for comment in ticket.comments.prefetch_related('attachments').all():
        attachment_metadata = [{'id': item.pk, 'filename': item.original_filename,
                                'size_bytes': item.size_bytes} for item in comment.attachments.all()]
        comment_snapshot = {'id': comment.pk, 'ticket_id': ticket.pk, 'author_id': comment.author_id,
                            'author_snapshot': comment.author_snapshot, 'body_markdown': comment.body_markdown,
                            'attachments': attachment_metadata}
        AuditEvent.objects.create(actor=actor, actor_snapshot=actor_snapshot(actor), project_id=project.pk,
            entity_type='comment', entity_id=comment.pk, entity_snapshot=comment_snapshot, action='delete',
            changes={'body_markdown': {'before': comment.body_markdown, 'after': None},
                     'attachments': {'before': attachment_metadata, 'after': None}},
            ticket_context_id=ticket.pk)
        attachment_keys = [attachment.storage_key for attachment in comment.attachments.all()]
        transaction.on_commit(lambda keys=attachment_keys: [default_storage.delete(key) for key in keys])
    record(actor, ticket, 'delete', snapshot(ticket))
    ticket.delete()
    return project.pk
