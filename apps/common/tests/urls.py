from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from django.urls import path
from rest_framework import exceptions as drf
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import (
    Forbidden,
    ParameterMissing,
    ResourceNotFound,
    TooManyRequests,
    ValidationFailed,
)

RAISES = {
    "forbidden": lambda: Forbidden(),
    "forbidden-message": lambda: Forbidden("Not yours"),
    "resource-not-found": lambda: ResourceNotFound("Project"),
    "resource-not-found-default": lambda: ResourceNotFound(),
    "validation-failed": lambda: ValidationFailed(["Name can't be blank"]),
    "validation-failed-message": lambda: ValidationFailed(["Bad"], message="Could not save"),
    "too-many-requests": lambda: TooManyRequests(["Slow down"], 60),
    "too-many-requests-message": lambda: TooManyRequests(["Slow down"], 3600, message="No"),
    "parameter-missing": lambda: ParameterMissing(),
    "not-authenticated": lambda: drf.NotAuthenticated(),
    "authentication-failed": lambda: drf.AuthenticationFailed(),
    "permission-denied": lambda: drf.PermissionDenied(),
    "django-permission-denied": lambda: DjangoPermissionDenied(),
    "http404": lambda: Http404(),
    "not-found": lambda: drf.NotFound(),
    "parse-error": lambda: drf.ParseError(),
    "unhandled": lambda: RuntimeError("boom"),
}


class Raising(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, name):
        raise RAISES[name]()


class GetOnly(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({})


urlpatterns = [
    path("raise/<str:name>", Raising.as_view()),
    path("get-only", GetOnly.as_view()),
]

handler404 = "apps.common.views.not_found"
handler500 = "apps.common.views.server_error"
