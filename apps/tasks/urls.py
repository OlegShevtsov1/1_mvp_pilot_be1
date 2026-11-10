from django.urls import path

from apps.tasks import views

urlpatterns = [
    path("api/v1/projects/<str:project_id>/tasks", views.TaskListView.as_view()),
    path("api/v1/projects/<str:project_id>/tasks/<str:id>", views.TaskDetailView.as_view()),
]
