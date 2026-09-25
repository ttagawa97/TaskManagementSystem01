from datetime import timedelta
from functools import wraps
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST
from . import services
from .forms import LoginForm, PasswordForm, UserForm
from .models import User


def error(request, message, status):
    return render(request, 'error.html', {'message': message}, status=status)


def access(admin=False, allow_change=False):
    def decorate(view):
        @wraps(view)
        @never_cache
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('/auth/login') if request.method == 'GET' else error(request, 'ログインしてください。', 401)
            if not request.user.is_active or request.user.is_special:
                logout(request)
                return error(request, 'ログインしてください。', 401)
            if request.user.temporary_password_expired:
                logout(request)
                return error(request, '仮パスワードの期限が切れました。管理者へ再発行を依頼してください。', 403)
            if request.user.must_change_password and not allow_change:
                return redirect('/auth/password/change') if request.method == 'GET' else error(request, '先にパスワードを変更してください。', 403)
            if admin and not request.user.is_system_admin:
                return error(request, 'この操作を行う権限がありません。', 403)
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


@sensitive_post_parameters('password')
@never_cache
@require_http_methods(['GET', 'POST'])
def login_view(request):
    form = LoginForm(request.POST or None)
    status = 200
    if request.method == 'POST':
        status = 400
        if form.is_valid():
            with transaction.atomic():
                services.lock_users()
                user = authenticate(request, **form.cleaned_data)
                if user and not user.is_special and not user.temporary_password_expired:
                    login(request, user)
                    request.session.set_expiry(timezone.now() + timedelta(hours=24))
                    return redirect('/auth/password/change' if user.must_change_password else '/')
            form.add_error(None, 'ID・パスワードが正しくないか、利用できない状態です。仮パスワードの期限切れは管理者へ再発行を依頼してください。')
            status = 401
    return render(request, 'accounts/form.html', {'form': form, 'heading': 'ログイン', 'button': 'ログイン',
        'notice': 'ログインから24時間で有効期限が切れます。期限切れの場合は再ログインしてください。'}, status=status)


@require_POST
@never_cache
def logout_view(request):
    logout(request)
    return redirect('/auth/login')


@sensitive_post_parameters('old_password', 'new_password', 'confirm_password')
@access(allow_change=True)
@require_http_methods(['GET', 'POST'])
def password_view(request):
    form = PasswordForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            user = services.change_password(request.user, form.cleaned_data['old_password'], form.cleaned_data['new_password'])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            # Rotates session key while retaining the absolute login expiry.
            update_session_auth_hash(request, user)
            return redirect('/')
    return render(request, 'accounts/form.html', {'form': form, 'heading': 'パスワード変更', 'button': '変更する',
        'notice': '初回・初期化後は、業務を始める前にパスワードを変更してください。'}, status=400 if request.method == 'POST' else 200)


@access(admin=True)
@require_http_methods(['GET'])
def users_view(request):
    page = Paginator(User.objects.filter(is_special=False).order_by('id'), 50).get_page(request.GET.get('page'))
    return render(request, 'accounts/users.html', {'page': page})


@access(admin=True)
@require_http_methods(['GET', 'POST'])
def user_form_view(request, pk=None):
    user = get_object_or_404(User, pk=pk, is_special=False) if pk else None
    form = UserForm(request.POST if request.method == 'POST' else None, initial=services.snapshot(user) if user else None)
    status = 200
    if request.method == 'POST':
        status = 400
        if form.is_valid():
            try:
                if user:
                    services.edit_user(request.user, pk, form.cleaned_data)
                    return redirect('/users' if request.user.pk != pk or form.cleaned_data['is_system_admin'] else '/')
                created, raw = services.create_user(request.user, form.cleaned_data)
                return render(request, 'accounts/issued.html', {'target': created, 'temporary_password': raw}, status=201)
            except services.Conflict as exc:
                form.add_error(None, exc)
                status = 409
            except ValidationError as exc:
                form.add_error(None, '; '.join(exc.messages))
    return render(request, 'accounts/form.html', {'form': form, 'heading': 'ユーザー編集' if user else 'ユーザー作成',
        'button': '保存する' if user else '作成する', 'target': user}, status=status)


@access(admin=True)
@require_http_methods(['GET', 'POST'])
def reset_view(request, pk):
    target = get_object_or_404(User, pk=pk, is_special=False)
    if request.method == 'POST':
        target, raw = services.reset_password(request.user, pk)
        return render(request, 'accounts/issued.html', {'target': target, 'temporary_password': raw})
    return render(request, 'accounts/reset.html', {'target': target})
