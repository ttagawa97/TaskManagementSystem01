from django.urls import path
from . import views

urlpatterns = [
    path('projects', views.project_list),
    path('projects/new', views.create),
    path('projects/<int:pk>', views.detail),
    path('projects/<int:pk>/edit', views.edit),
    path('projects/<int:pk>/members', views.members),
    path('projects/<int:pk>/members/<int:user_id>/role', views.role),
    path('projects/<int:pk>/archive', views.archive, {'operation':'archive'}),
    path('projects/<int:pk>/unarchive', views.archive, {'operation':'unarchive'}),
]
for kind in ['statuses', 'types']:
    urlpatterns += [
        path('projects/<int:pk>/' + kind, views.masters, {'kind':kind}),
        path('projects/<int:pk>/' + kind + '/new', views.master_edit, {'kind':kind}),
        path('projects/<int:pk>/' + kind + '/<int:master_id>', views.master_edit, {'kind':kind}),
    ]
