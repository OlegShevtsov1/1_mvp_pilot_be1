import os

from django.http import HttpResponse, JsonResponse

from apps.common.rate_limit import client_ip, increment
from apps.errors import tunnel

# Rate limit: RATE_LIMIT requests per client IP per WINDOW seconds, counted before the view
# does anything else, so accepted, refused-DSN and too-large requests all count.
RATE_LIMIT = 30
WINDOW = 60


def errors_create(request):
    """POST /api/errors: the frontend's Sentry tunnel (see apps.errors.tunnel)."""
    if request.method != "POST":
        return HttpResponse(status=404)
    if increment(f"rate-limit:errors:{client_ip(request)}", 1, WINDOW) > RATE_LIMIT:
        return HttpResponse(status=429)

    allowed_dsn = os.environ.get("SENTRY_ALLOWED_FE_DSN", "")
    if not allowed_dsn.strip():
        return HttpResponse(status=404)

    body = _read_body(request)
    if body is None:
        return HttpResponse(status=413)

    try:
        status, upstream_body = tunnel.forward(body, allowed_dsn)
    except tunnel.Rejected as rejected:
        return JsonResponse({"error": str(rejected)}, status=rejected.status)
    return HttpResponse(upstream_body, status=status, content_type="application/json")


def _read_body(request):
    """None when the body exceeds tunnel.MAX_BYTES, whatever Content-Length claims."""
    if int(request.META.get("CONTENT_LENGTH") or 0) > tunnel.MAX_BYTES:
        return None
    body = request.read(tunnel.MAX_BYTES + 1)
    return None if len(body) > tunnel.MAX_BYTES else body
