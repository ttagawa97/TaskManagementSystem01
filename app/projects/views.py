from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_GET
from accounts.views import access
from accounts.services import Conflict
from . import services
from .forms import ProjectForm, CreateProjectForm, MemberForm, RoleForm, MasterForm
from .models import Membership


def form_page(request, form, heading, status=200, notice='', **context):
    return render(request, 'projects/form.html', {'form':form, 'heading':heading, 'notice':notice, **context}, status=status)


def apply_error(form, exc):
    form.add_error(None, '; '.join(exc.messages))
    return 409 if isinstance(exc, Conflict) else 400


@access()
@require_GET
def project_list(request):
    page = Paginator(services.visible_projects(request.user), 50).get_page(request.GET.get('page'))
    return render(request, 'projects/list.html', {'page':page})


@access(admin=True)
@require_http_methods(['GET', 'POST'])
def create(request):
    form = CreateProjectForm(request.POST if request.method == 'POST' else None)
    status = 400 if request.method == 'POST' else 200
    if request.method == 'POST' and form.is_valid():
        try:
            project = services.create_project(request.user, form.cleaned_data['name'], form.cleaned_data['description'], [u.pk for u in form.cleaned_data['admins']])
            return redirect(f'/projects/{project.pk}/settings')
        except ValidationError as exc:
            status = apply_error(form, exc)
    return form_page(request, form, 'プロジェクト作成', status)


@access()
@require_GET
def detail(request, pk):
    project = services.get_project(request.user, pk)
    return render(request, 'projects/detail.html', {'project':project, 'can_manage':services.can_manage(request.user, project), 'can_edit':services.can_manage(request.user, project) and not project.is_archived})


@access(admin=True)
@require_http_methods(['GET', 'POST'])
def edit(request, pk):
    project = services.get_project(request.user, pk)
    if project.is_archived:
        return render(request, 'error.html', {'message':'アーカイブ中は変更できません。先に解除してください。'}, status=409)
    form = ProjectForm(request.POST if request.method == 'POST' else None, instance=project)
    status = 400 if request.method == 'POST' else 200
    if request.method == 'POST' and form.is_valid():
        try:
            services.edit_project(request.user, pk, form.cleaned_data['name'], form.cleaned_data['description'])
            return redirect(f'/projects/{pk}/settings')
        except ValidationError as exc:
            status = apply_error(form, exc)
    return form_page(request, form, 'プロジェクト編集', status, project=project)


@access()
@require_http_methods(['GET', 'POST'])
def members(request, pk):
    project = services.get_project(request.user, pk)
    manager = services.can_manage(request.user, project)
    form = MemberForm(request.POST if request.method == 'POST' else None, project=project)
    status = 200
    if request.method == 'POST':
        if not manager:
            raise PermissionDenied
        status = 400
        if form.is_valid():
            try:
                services.add_member(request.user, pk, form.cleaned_data['user'].pk)
                return redirect(f'/projects/{pk}/members')
            except ValidationError as exc:
                status = apply_error(form, exc)
    page = Paginator(Membership.objects.filter(project=project).select_related('user').order_by('id'), 50).get_page(request.GET.get('page'))
    return render(request, 'projects/members.html', {'project':project, 'can_manage':manager and not project.is_archived, 'form':form, 'page':page}, status=status)


@access(admin=True)
@require_http_methods(['GET', 'POST'])
def role(request, pk, user_id):
    project = services.get_project(request.user, pk)
    if project.is_archived:
        return render(request, 'error.html', {'message':'アーカイブ中は変更できません。先に解除してください。'}, status=409)
    member = get_object_or_404(Membership.objects.select_related('user'), project=project, user_id=user_id)
    form = RoleForm(request.POST if request.method == 'POST' else None, initial={'is_project_admin':member.is_project_admin})
    status = 400 if request.method == 'POST' else 200
    if request.method == 'POST' and form.is_valid():
        try:
            services.change_role(request.user, pk, user_id, form.cleaned_data['is_project_admin'])
            return redirect(f'/projects/{pk}/members')
        except ValidationError as exc:
            status = apply_error(form, exc)
    return form_page(request, form, 'プロジェクト管理者の変更', status, notice=f'{member.user.display_name}（{member.user.username}）の権限を変更します。', project=project)


@access()
@require_http_methods(['GET', 'POST'])
def archive(request, pk, operation):
    project = services.get_project(request.user, pk)
    if not services.can_manage(request.user, project):
        raise PermissionDenied
    archived = operation == 'archive'
    if request.method == 'POST':
        services.archive_project(request.user, pk, archived)
        return redirect(f'/projects/{pk}/settings')
    return render(request, 'projects/confirm.html', {'project':project, 'heading':'アーカイブ' if archived else 'アーカイブ解除'})


@access()
@require_GET
def masters(request, pk, kind):
    project = services.get_project(request.user, pk)
    page = Paginator(services.MASTER_MODELS[kind].objects.filter(project=project), 50).get_page(request.GET.get('page'))
    return render(request, 'projects/masters.html', {'project':project, 'page':page, 'kind':kind,
        'heading':'ステータス' if kind == 'statuses' else '種別', 'can_manage':services.can_manage(request.user, project), 'can_edit':services.can_manage(request.user, project) and not project.is_archived})


@access()
@require_http_methods(['GET', 'POST'])
def master_edit(request, pk, kind, master_id=None):
    project = services.get_project(request.user, pk)
    if project.is_archived:
        return render(request, 'error.html', {'message':'アーカイブ中は変更できません。先に解除してください。'}, status=409)
    if not services.can_manage(request.user, project):
        raise PermissionDenied
    obj = get_object_or_404(services.MASTER_MODELS[kind], pk=master_id, project=project) if master_id else None
    form = MasterForm(request.POST if request.method == 'POST' else None, initial={'name':obj.name, 'is_active':obj.is_active} if obj else {'is_active':True})
    status = 400 if request.method == 'POST' else 200
    if request.method == 'POST' and form.is_valid():
        try:
            services.save_master(request.user, pk, kind, **form.cleaned_data, master_id=master_id)
            return redirect(f'/projects/{pk}/{kind}')
        except ValidationError as exc:
            status = apply_error(form, exc)
    return form_page(request, form, ('ステータス' if kind == 'statuses' else '種別') + ('編集' if obj else '追加'), status,
        notice='有効のチェックを外すと無効化します。既存チケットの参照は保持されます。' if obj else '', project=project)
