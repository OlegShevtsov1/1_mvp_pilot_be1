import sentry_sdk
from django.db import connection
from django.http import HttpResponse, JsonResponse

from apps.admin_smoke import smoke
from apps.admin_smoke.token import smoke_token_presented


def glitchtip_smoke(request, kind):
    """Hidden unless the caller presents SMOKE_TOKEN: every refusal is a 404, never a 401/403."""
    if (
        request.method != "POST"
        or not smoke_token_presented(request)
        or kind not in smoke.KINDS_IN_REQUEST
    ):
        return HttpResponse(status=404)

    marker = smoke.marker(request.headers.get("X-Smoke-Marker"))
    message = smoke.message(kind, marker)
    if kind == "unhandled":
        raise smoke.GlitchtipSmokeError(message)
    if kind == "manual":
        event_id = sentry_sdk.capture_message(message, level="error")
        return JsonResponse({"kind": "manual", "marker": marker, "event_id": event_id}, status=202)
    with connection.cursor() as cursor:
        # Both SQLite and Postgres name an unknown qualified column in full in their error, so the
        # marker lands in the message. A bare double-quoted name would not do on SQLite: it reads
        # an unresolved one as a string literal and raises nothing.
        cursor.execute(
            f"SELECT smoke_q.{connection.ops.quote_name(marker)} FROM (SELECT 1) AS smoke_q"
        )
    return HttpResponse(status=204)
