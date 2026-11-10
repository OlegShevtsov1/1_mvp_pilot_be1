"""Browsers may call this API only from the origins in CORS_ALLOWED_ORIGINS (comma-separated,
e.g. https://app.dev.example.com). Read per request; unset or empty allows no origin.
No credentials: the API authenticates with headers (bearer Authorization, legacy token headers),
not cookies, so any request header is allowed. Retry-After is exposed so the browser can read it
on a 429.
"""

import os

from corsheaders.middleware import ACCESS_CONTROL_ALLOW_HEADERS
from corsheaders.middleware import CorsMiddleware as BaseCorsMiddleware


def allow_configured_origin(sender, request, **kwargs):
    allowed = [o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")]
    return request.headers.get("origin") in [o for o in allowed if o]


class CorsMiddleware(BaseCorsMiddleware):
    """Allows any request header by echoing the preflight's Access-Control-Request-Headers:
    django-cors-headers only sends a fixed list, and a "*" there does not cover Authorization."""

    def add_response_headers(self, request, response):
        response = super().add_response_headers(request, response)
        requested = request.headers.get("access-control-request-headers")
        if requested and ACCESS_CONTROL_ALLOW_HEADERS in response:
            response[ACCESS_CONTROL_ALLOW_HEADERS] = requested
        return response
