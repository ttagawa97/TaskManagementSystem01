from accounts.views import access
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.core.paginator import Paginator
from projects.services import visible_projects


@access()
@require_GET
def home(request):
    from tickets.services import visible_tickets, recent_related_updates
    projects = Paginator(visible_projects(request.user).order_by('name', 'id'), 50).get_page(request.GET.get('projects_page'))
    assigned = visible_tickets(request.user).filter(assignee=request.user).order_by('-updated_at', '-id')
    return render(request, 'dashboard.html', {
        'projects_page':projects,
        'assigned_tickets':assigned[:10],
        'assigned_ticket_count':assigned.count(),
        'update_events':recent_related_updates(request.user),
        'dashboard_time':timezone.localtime(),
    })


@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({'status': 'unavailable'}, status=503)
    return JsonResponse({'status': 'ok'})


def not_found(request, exception):
    return render(request, 'error.html', {'message': 'ページが見つかりません。'}, status=404)


def server_error(request):
    return render(request, 'error.html', {'message': '処理を完了できませんでした。'}, status=500)


def forbidden(request, exception):
    return render(request, 'error.html', {'message': 'この操作を行う権限がありません。'}, status=403)


@access(admin=True)
@require_GET
def settings_view(request):
    return render(request, 'settings.html')
