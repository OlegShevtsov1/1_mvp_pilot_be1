"""Errors go to GlitchTip through the Sentry SDK. Without SENTRY_DSN the SDK is initialised but
sends nothing, which keeps development and the test suite offline."""

import os
import re
from urllib.parse import parse_qsl, urlencode

from django.conf import settings
from sentry_sdk.integrations.django import DjangoIntegration

# Parameter filter: a key containing any of these, in any case, has its value filtered.
FILTER_PARAMETERS = (
    "passw",
    "email",
    "secret",
    "token",
    "_key",
    "crypt",
    "salt",
    "certificate",
    "otp",
    "ssn",
)
FILTERED = "[FILTERED]"
_FILTERED_KEY = re.compile("|".join(FILTER_PARAMETERS), re.IGNORECASE)


def filter_parameters(value):
    if isinstance(value, dict):
        return {
            key: FILTERED if _FILTERED_KEY.search(str(key)) else filter_parameters(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [filter_parameters(item) for item in value]
    return value


def _filter_query_string(query_string):
    if isinstance(query_string, dict):
        return filter_parameters(query_string)
    pairs = parse_qsl(query_string, keep_blank_values=True)
    return urlencode(
        [(key, FILTERED if _FILTERED_KEY.search(key) else item) for key, item in pairs], safe="[]"
    )


def before_send(event, hint):
    """The SDK's own deny list does not know this app's filter parameters (email, token, ...), so
    every event is scrubbed with them as well. The Django integration ships the query string as a
    raw string, so it is parsed and filtered too."""
    request = event.get("request")
    if isinstance(request, dict):
        if isinstance(request.get("data"), dict):
            request["data"] = filter_parameters(request["data"])
        if isinstance(request.get("headers"), dict):
            request["headers"] = filter_parameters(request["headers"])
        if isinstance(request.get("query_string"), str | dict):
            request["query_string"] = _filter_query_string(request["query_string"])
    if isinstance(event.get("extra"), dict):
        event["extra"] = filter_parameters(event["extra"])
    return event


def sentry_options():
    return {
        "dsn": os.environ.get("SENTRY_DSN") or None,
        "environment": os.environ.get("SENTRY_ENVIRONMENT", settings.APP_ENVIRONMENT),
        "release": os.environ.get("APP_RELEASE") or None,
        # Frame locals are not sent: a request's repr in them would carry its query string past
        # before_send.
        "include_local_variables": False,
        "before_send": before_send,
        "integrations": [DjangoIntegration()],
    }
