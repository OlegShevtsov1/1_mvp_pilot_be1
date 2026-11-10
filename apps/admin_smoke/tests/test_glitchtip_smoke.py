import io
import json
import re
import secrets
from wsgiref.util import setup_testing_defaults

import pytest
from django.core.handlers.wsgi import WSGIHandler
from django.core.signals import request_started
from django.db import DatabaseError, close_old_connections
from django.test import Client

from tests.sentry import capture_sentry_events, last_exception

SMOKE_TOKEN = "smoke-token-spec"
PASSWORD = f"hunter2-{secrets.token_hex(4)}"


@pytest.fixture(autouse=True)
def smoke_token(monkeypatch):
    monkeypatch.setenv("SMOKE_TOKEN", SMOKE_TOKEN)


@pytest.fixture
def events():
    with capture_sentry_events() as events:
        yield events


def smoke(client, kind, token=SMOKE_TOKEN, marker="smoke-spec-marker"):
    headers = {"X-Smoke-Marker": marker}
    if token is not None:
        headers["X-Smoke-Token"] = token
    return client.post(f"/admin/glitchtip_smoke/{kind}?password={PASSWORD}", headers=headers)


def test_is_a_404_without_a_token(client, events):
    assert smoke(client, "manual", token=None).status_code == 404
    assert events == []


def test_is_a_404_with_a_wrong_token(client, events):
    assert smoke(client, "manual", token="wrong").status_code == 404
    assert events == []


def test_is_a_404_even_with_a_header_when_smoke_token_is_not_configured(client, monkeypatch):
    monkeypatch.delenv("SMOKE_TOKEN")

    assert smoke(client, "manual", token="").status_code == 404


def test_is_a_404_for_an_unknown_kind(client, events):
    assert smoke(client, "rake").status_code == 404
    assert events == []


def test_is_a_404_for_another_method(client, events):
    response = client.get("/admin/glitchtip_smoke/manual", headers={"X-Smoke-Token": SMOKE_TOKEN})

    assert response.status_code == 404
    assert response.content == b""
    assert events == []


def test_reports_a_manual_message_carrying_the_marker(client, events):
    response = smoke(client, "manual")

    assert response.status_code == 202
    [event] = events
    assert response.json() == {
        "kind": "manual",
        "marker": "smoke-spec-marker",
        "event_id": event["event_id"],
    }
    assert event["message"] == "glitchtip smoke manual smoke-spec-marker"


def test_replaces_a_marker_that_is_not_a_plain_word_with_a_generated_one(client):
    response = smoke(client, "manual", marker="<script>")

    assert re.fullmatch(r"glitchtip-smoke-[0-9a-f]{12}", response.json()["marker"])


def test_reports_an_unhandled_exception_and_answers_500(events):
    # Through the WSGI handler, as in production: the test client's requests reach the SDK without
    # their request data, which would leave the password check below vacuous.
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/admin/glitchtip_smoke/unhandled",
        "QUERY_STRING": f"password={PASSWORD}",
        "HTTP_X_SMOKE_TOKEN": SMOKE_TOKEN,
        "HTTP_X_SMOKE_MARKER": "smoke-spec-marker",
        "HTTP_HOST": "localhost",
        "wsgi.input": io.BytesIO(b""),
    }
    setup_testing_defaults(environ)
    statuses = []
    # As the test client does: a request must not close the test database connection.
    request_started.disconnect(close_old_connections)
    try:
        WSGIHandler()(environ, lambda status, headers, exc_info=None: statuses.append(status))
    finally:
        request_started.connect(close_old_connections)

    assert statuses == ["500 Internal Server Error"]
    event = events[-1]
    assert event["request"]["url"] == "http://localhost/admin/glitchtip_smoke/unhandled"
    exception = last_exception(event)
    assert exception["type"] == "GlitchtipSmokeError"
    assert "smoke-spec-marker" in exception["value"]
    assert PASSWORD not in json.dumps(event)


@pytest.mark.django_db
def test_reports_a_database_error_carrying_the_marker_and_answers_500(events):
    response = smoke(Client(raise_request_exception=False), "db")

    assert response.status_code == 500
    exception = last_exception(events[-1])
    assert exception["type"] in {cls.__name__ for cls in DatabaseError.__subclasses__()}
    assert "smoke-spec-marker" in exception["value"]
