from django.urls import path
from . import views

urlpatterns = [
    path('tickets', views.ticket_list),
    path('tickets/mine', views.ticket_list, {'mine':True}),
    path('projects/<int:project_id>/tickets', views.ticket_list),
    path('projects/<int:project_id>/tickets/new', views.edit),
    path('tickets/<int:pk>', views.edit),
    path('tickets/<int:pk>/edit', views.edit),
    path('tickets/<int:pk>/comments', views.comment_create),
    path('attachments/<int:pk>/content', views.attachment_content),
    path('tickets/<int:pk>/delete', views.delete),
    path('markdown/preview', views.preview),
]
