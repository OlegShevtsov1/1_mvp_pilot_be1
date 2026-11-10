import json
import os

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_safe


@require_safe
def health(request):
    return JsonResponse({"status": "ok", "release": os.environ.get("APP_RELEASE", "unknown")})


@require_safe
def api_docs(request):
    """The OpenAPI contract (contract/openapi.json) with the origin the reader actually reached,
    behind a proxy via X-Forwarded-Proto/Host, as its only server, so "Try it out" targets this
    deployment."""
    document = json.loads((settings.BASE_DIR / "contract" / "openapi.json").read_text())
    environment = os.environ.get("SENTRY_ENVIRONMENT", settings.APP_ENVIRONMENT)
    document["servers"] = [{"url": _base_url(request), "description": environment}]
    return JsonResponse(document)


def _base_url(request):
    scheme = _last_forwarded(request, "X-Forwarded-Proto") or request.scheme
    host = _last_forwarded(request, "X-Forwarded-Host") or request.get_host()
    return f"{scheme}://{host}"


def _last_forwarded(request, header):
    return request.headers.get(header, "").split(",")[-1].strip()
