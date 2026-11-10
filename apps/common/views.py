"""Django's 404/500 handlers, answering `{"status": <code>, "error": "<reason>"}`."""

from django.http import JsonResponse

from apps.common.exceptions import public_exception_body


def not_found(request, exception):
    return JsonResponse(public_exception_body(404), status=404)


def server_error(request):
    return JsonResponse(public_exception_body(500), status=500)
