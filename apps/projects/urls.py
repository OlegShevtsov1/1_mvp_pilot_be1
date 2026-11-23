from django.urls import path

from apps.projects import views

# String ids, read by their leading digits, so /api/v1/projects/5abc is project 5.
urlpatterns = [
    path("api/v1/projects", views.ProjectListView.as_view()),
    path("api/v1/projects/<str:id>", views.ProjectDetailView.as_view()),
    path("api/v1/projects/<str:project_id>/members", views.MemberListView.as_view()),
    path("api/v1/projects/<str:project_id>/members/<str:id>", views.MemberDetailView.as_view()),
]
