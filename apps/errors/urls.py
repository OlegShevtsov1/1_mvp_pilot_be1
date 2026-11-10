from django.urls import path

from apps.errors.views import errors_create

urlpatterns = [
    path("api/errors", errors_create),
]
