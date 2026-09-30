from django.conf import settings
from django.db import models
from django.db.models import Q, F, JSONField
from django.core.validators import MaxLengthValidator


class Ticket(models.Model):
    PRIORITIES = [('high', '高'), ('medium', '中'), ('low', '低')]
    project = models.ForeignKey('projects.Project', on_delete=models.PROTECT)
    title = models.CharField('タイトル', max_length=200)
    description_markdown = models.TextField('説明（Markdown）', blank=True, max_length=100000)
    status = models.ForeignKey('projects.TicketStatus', on_delete=models.PROTECT)
    type = models.ForeignKey('projects.TicketType', on_delete=models.PROTECT)
    priority = models.CharField('優先度', max_length=6, choices=PRIORITIES, default='medium')
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='assigned_tickets')
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_tickets')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='children')
    start_date = models.DateField('開始日', null=True, blank=True)
    due_date = models.DateField('期限', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tickets'
        ordering = ['-updated_at', '-id']
        indexes = [models.Index(fields=['project', '-updated_at', '-id']), models.Index(fields=['assignee', '-updated_at', '-id'])]
        constraints = [
            models.CheckConstraint(condition=Q(start_date__isnull=True) | Q(due_date__isnull=True) | Q(start_date__lte=F('due_date')), name='ticket_date_order'),
            models.CheckConstraint(condition=Q(priority__in=['high', 'medium', 'low']), name='ticket_priority'),
            models.CheckConstraint(condition=~Q(parent_id=F('id')), name='ticket_not_own_parent'),
        ]


class Comment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ticket_comments')
    author_snapshot = JSONField(default=dict)
    body_markdown = models.TextField(blank=True, validators=[MaxLengthValidator(100000)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ticket_comments'
        ordering = ['created_at', 'id']


class Attachment(models.Model):
    ticket = models.ForeignKey(Ticket, null=True, blank=True, on_delete=models.CASCADE, related_name='attachments')
    comment = models.ForeignKey(Comment, null=True, blank=True, on_delete=models.CASCADE, related_name='attachments')
    wiki_page_id = models.BigIntegerField(null=True, blank=True)
    uploader = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='uploaded_attachments')
    original_filename = models.CharField(max_length=255)
    storage_key = models.CharField(max_length=255, unique=True)
    media_type = models.CharField(max_length=255, default='application/octet-stream')
    size_bytes = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'attachments'
        ordering = ['created_at', 'id']
        constraints = [models.CheckConstraint(
            condition=(
                Q(ticket__isnull=False, comment__isnull=True, wiki_page_id__isnull=True)
                | Q(ticket__isnull=True, comment__isnull=False, wiki_page_id__isnull=True)
                | Q(ticket__isnull=True, comment__isnull=True, wiki_page_id__isnull=False)
            ), name='attachment_single_owner')]
