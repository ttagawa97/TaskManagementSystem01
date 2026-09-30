from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, JsonResponse
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from accounts.views import access, error
from accounts.services import Conflict
from projects.models import TicketStatus, TicketType
from projects.services import get_project
from projects.views import apply_error
from . import services
from .forms import CommentForm, TicketForm, SearchForm
from .models import Attachment, Comment
from .markdown import render_markdown


@access()
@require_GET
def ticket_list(request, project_id=None, mine=False):
    project = get_project(request.user, project_id) if project_id else None
    form = SearchForm(request.GET, actor=request.user, project=project, mine=mine)
    sortable_fields = {
        'id': 'pk', 'title': 'title', 'project': 'project__name', 'status': 'status__name',
        'type': 'type__name', 'priority': 'priority', 'assignee': 'assignee__display_name',
        'start_date': 'start_date', 'due_date': 'due_date', 'updated_at': 'updated_at',
    }
    sort_by = request.GET.get('sort_by', '')
    sort_order = request.GET.get('sort_order', '')
    sort_valid = ((not sort_by and not sort_order) or
                  (sort_by in sortable_fields and sort_order in ('asc', 'desc')))
    tickets = services.visible_tickets(request.user)
    if project:
        tickets = tickets.filter(project=project)
    if mine:
        tickets = tickets.filter(assignee=request.user)
    valid = form.is_valid()
    if valid and sort_valid:
        data = form.cleaned_data
        for field in ('project_id', 'assignee_id', 'priority'):
            if data.get(field):
                tickets = tickets.filter(**{field+'__in': data[field]})
        for field, relation, model in (
            ('status_id', 'status', TicketStatus),
            ('type_id', 'type', TicketType),
        ):
            if data.get(field):
                names = model.objects.filter(pk__in=data[field]).values_list('name', flat=True)
                tickets = tickets.filter(**{relation+'__name__in': names})
        if data['q']:
            tickets = tickets.filter(Q(title__icontains=data['q']) | Q(description_markdown__icontains=data['q']))
    else:
        tickets = tickets.none()
    if sort_valid and sort_by:
        direction = '' if sort_order == 'asc' else '-'
        field_name = sortable_fields[sort_by]
        ordering = [direction + field_name]
        if field_name != 'pk':
            ordering.append(direction + 'pk')
        tickets = tickets.order_by(*ordering)
    size = form.cleaned_data.get('page_size') or 50 if valid else 50
    page = Paginator(tickets, size).get_page(request.GET.get('page'))
    query = request.GET.copy()
    query.pop('page', None)
    sort_urls = {}
    for field_name in sortable_fields:
        sort_query = request.GET.copy()
        sort_query.pop('page', None)
        sort_query.pop('sort_by', None)
        sort_query.pop('sort_order', None)
        if sort_by == field_name and sort_order == 'asc':
            sort_query.update({'sort_by': field_name, 'sort_order': 'desc'})
        elif sort_by != field_name or sort_order != 'desc':
            sort_query.update({'sort_by': field_name, 'sort_order': 'asc'})
        sort_urls[field_name] = '?' + sort_query.urlencode() if sort_query else '?'
    return render(request, 'tickets/list.html', {'form':form, 'page':page, 'query':query.urlencode(), 'project':project,
        'heading':'自チケット' if mine else 'チケット検索', 'sort_by':sort_by, 'sort_order':sort_order,
        'sort_urls':sort_urls}, status=200 if valid and sort_valid else 400)


@access()
@require_http_methods(['GET', 'POST'])
def edit(request, project_id=None, pk=None):
    ticket = services.get_ticket(request.user, pk) if pk else None
    project = ticket.project if ticket else get_project(request.user, project_id)
    if project.is_archived and request.method == 'POST':
        return error(request, 'アーカイブ中は変更できません。先に解除してください。', 409)
    form = TicketForm(request.POST if request.method == 'POST' else None, project=project, ticket=ticket,
                      initial=services.snapshot(ticket) if ticket else None)
    if project.is_archived:
        for field in form.fields.values():
            field.disabled = True
    status = 400 if request.method == 'POST' else 200
    if request.method == 'POST' and form.is_valid():
        try:
            # Reject immutable and future controls instead of silently accepting them.
            if any(k in request.POST for k in ('project_id', 'creator_id', 'parent_id')):
                raise ValidationError('変更できない項目が指定されています。')
            saved = services.save_ticket(request.user, project.pk, form.service_data(), pk)
            return redirect(f'/projects/{saved.project_id}/tickets')
        except ValidationError as exc:
            status = apply_error(form, exc)
    return render_ticket_editor(request, project, ticket, form, CommentForm(), status)


def render_ticket_editor(request, project, ticket, form, comment_form, status=200):
    comments = list(ticket.comments.prefetch_related('attachments').all()) if ticket else []
    for comment in comments:
        comment.rendered_body = render_markdown(comment.body_markdown)
    return render(request, 'tickets/form.html', {'form':form, 'project':project, 'ticket':ticket,
        'heading':'チケット編集' if ticket else 'チケット作成', 'read_only':project.is_archived,
        'description_html':render_markdown(ticket.description_markdown) if ticket else '',
        'comments':comments, 'comment_form':comment_form,
        'can_delete':bool(ticket and services.can_delete(request.user, ticket))}, status=status)


@access()
@require_POST
def comment_create(request, pk):
    ticket = services.get_ticket(request.user, pk)
    if ticket.project.is_archived:
        return error(request, 'アーカイブ中はコメントを追加できません。先に解除してください。', 409)
    form = CommentForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            services.create_comment(request.user, ticket.pk, form.cleaned_data['body_markdown'], form.cleaned_data['attachments'])
            return redirect(f'/tickets/{ticket.pk}')
        except ValidationError as exc:
            form.add_error(None, exc)
    ticket_form = TicketForm(project=ticket.project, ticket=ticket, initial=services.snapshot(ticket))
    return render_ticket_editor(request, ticket.project, ticket, ticket_form, form, 400)


@access()
@require_GET
def attachment_content(request, pk):
    attachment = get_object_or_404(Attachment.objects.select_related('comment__ticket'), pk=pk,
                                    comment__isnull=False)
    services.get_ticket(request.user, attachment.comment.ticket_id)
    response = FileResponse(default_storage.open(attachment.storage_key, 'rb'),
                            as_attachment=True, filename=attachment.original_filename,
                            content_type='application/octet-stream')
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@access()
@require_http_methods(['GET', 'POST'])
def delete(request, pk):
    ticket = services.get_ticket(request.user, pk)
    if not services.can_delete(request.user, ticket):
        raise PermissionDenied
    if ticket.project.is_archived:
        return error(request, 'アーカイブ中は変更できません。先に解除してください。', 409)
    if request.method == 'POST':
        try:
            project_id = services.delete_ticket(request.user, pk)
            return redirect(f'/projects/{project_id}/tickets')
        except Conflict as exc:
            return error(request, '; '.join(exc.messages), 409)
    return render(request, 'tickets/delete.html', {'ticket':ticket, 'project':ticket.project})


@access()
@require_POST
def preview(request):
    text = request.POST.get('text', '')
    if len(text) > 100000:
        return JsonResponse({'error':{'code':'invalid_input', 'message':'説明は100000文字以内で入力してください。', 'fields':{'text':'文字数超過'}}}, status=400)
    return JsonResponse({'html':render_markdown(text)})
