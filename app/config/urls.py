from django.urls import path, include
from django.contrib.staticfiles.views import serve
from core import views
from accounts import views as accounts

urlpatterns = [
    path('', include('projects.urls')),
    path('auth/login', accounts.login_view),
    path('auth/logout', accounts.logout_view),
    path('auth/password/change', accounts.password_view),
    path('users', accounts.users_view),
    path('users/new', accounts.user_form_view),
    path('users/<int:pk>', accounts.user_form_view),
    path('users/<int:pk>/reset-password', accounts.reset_view),
    path('', views.home, name='home'),
    path('health/', views.health, name='health'),
    # Local development only. No upload/media file serving route is exposed.
    path('static/<path:path>', serve, {'insecure': True}),
]
handler404 = 'core.views.not_found'
handler500 = 'core.views.server_error'

handler403 = 'core.views.forbidden'
