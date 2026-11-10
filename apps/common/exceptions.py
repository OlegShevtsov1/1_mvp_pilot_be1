"""The API's error answers.

Views raise these; `exception_handler` renders them and DRF's own exceptions in the API's shapes.
"""

from http import HTTPStatus

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, JsonResponse
from rest_framework import exceptions as drf

NOT_AUTHORIZED = "You are not authorized to perform this action"


class ApiError(drf.APIException):
    def __init__(self, status_code, body, headers=None):
        super().__init__()
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}


def _with_message(errors, message):
    return (
        {"errors": errors}
        if message is None
        else {
            "status": "error",
            "message": message,
            "errors": errors,
        }
    )


class Forbidden(ApiError):
    def __init__(self, message=NOT_AUTHORIZED):
        super().__init__(403, {"error": message})


class ResourceNotFound(ApiError):
    def __init__(self, resource="Resource"):
        super().__init__(404, {"error": f"{resource} not found"})


class ValidationFailed(ApiError):
    """422 with the validation messages; `message` adds `status`/`message` keys (sign-up)."""

    def __init__(self, errors, message=None):
        super().__init__(422, _with_message(errors, message))


class TooManyRequests(ApiError):
    def __init__(self, errors, retry_after, message=None):
        super().__init__(429, _with_message(errors, message), {"Retry-After": str(retry_after)})


class ParameterMissing(ApiError):
    """A required body parameter is missing or empty: 422."""

    def __init__(self):
        super().__init__(422, public_exception_body(422))


# RFC 9110's reason phrase for 422, which Python 3.12 still calls "Unprocessable Entity".
_REASON_PHRASES = {422: "Unprocessable Content"}


def public_exception_body(status):
    """The `{"status", "error"}` body of an error no view handles."""
    return {"status": status, "error": _REASON_PHRASES.get(status) or HTTPStatus(status).phrase}


def error_response(exc: ApiError) -> JsonResponse:
    response = JsonResponse(exc.body, status=exc.status_code)
    for name, value in exc.headers.items():
        response[name] = value
    return response


def exception_handler(exc, context):
    match exc:
        case ApiError():
            return error_response(exc)
        case drf.NotAuthenticated() | drf.AuthenticationFailed():
            # DRF may have made this a 403 for want of a WWW-Authenticate scheme; it is a 401.
            return JsonResponse({"error": "Not Authorized"}, status=401)
        case drf.PermissionDenied() | DjangoPermissionDenied():
            return JsonResponse({"error": NOT_AUTHORIZED}, status=403)
        case Http404() | drf.NotFound():
            return JsonResponse({"error": "Not Found"}, status=404)
        case drf.MethodNotAllowed():
            # Routes match method and path, so another method on a known path is an unknown route.
            return JsonResponse(public_exception_body(404), status=404)
        case drf.APIException():
            return JsonResponse(public_exception_body(exc.status_code), status=exc.status_code)
    return None
