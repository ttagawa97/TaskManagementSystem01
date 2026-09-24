from django.urls import path
from django.contrib.staticfiles.views import serve
from core import views

urlpatterns = [
    path('', views.home, name='home'),
    path('health/', views.health, name='health'),
    # Local development only. No upload/media file serving route is exposed.
    path('static/<path:path>', serve, {'insecure': True}),
]
handler404 = 'core.views.not_found'
handler500 = 'core.views.server_error'
