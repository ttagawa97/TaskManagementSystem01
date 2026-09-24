from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET


@require_GET
def home(request):
    return render(request, 'home.html', {'now': timezone.localtime()})


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
