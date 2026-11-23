from django.urls import path

from apps.tasks import views

TASK = "api/v1/projects/<str:project_id>/tasks/<str:id>"
LABEL = "api/v1/projects/<str:project_id>/labels/<str:id>"

urlpatterns = [
    path("api/v1/projects/<str:project_id>/tasks", views.TaskListView.as_view()),
    path(TASK, views.TaskDetailView.as_view()),
    path(f"{TASK}/dependencies", views.DependencyListView.as_view()),
    path(f"{TASK}/dependencies/<str:blocker_id>", views.DependencyDetailView.as_view()),
    path(f"{TASK}/labels", views.TaskLabelListView.as_view()),
    path(f"{TASK}/labels/<str:label_id>", views.TaskLabelDetailView.as_view()),
    path("api/v1/projects/<str:project_id>/labels", views.LabelListView.as_view()),
    path(LABEL, views.LabelDetailView.as_view()),
    path(f"{LABEL}/tasks", views.LabelTasksView.as_view()),
]
