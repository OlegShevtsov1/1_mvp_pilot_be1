import json
import secrets

import pytest
import sentry_sdk

from apps.errors.sentry import before_send, sentry_options
from tests.sentry import capture_sentry_events

# Generated, not literal: events carry source context lines of this file, so a literal secret
# would leak into the event through the stack trace and hide what the scrubber does.
PASSWORD = f"hunter2-{secrets.token_hex(4)}"
TOKEN = f"tok-{secrets.token_hex(4)}"


def test_scrubs_filtered_parameters_from_the_query_string_and_the_headers_of_a_captured_request():
    # The request part of an event as the Django integration builds it.
    event = {
        "request": {
            "url": "http://dev.example.test/api/v1/me",
            "method": "GET",
            "query_string": f"password={PASSWORD}&token={TOKEN}&kind=kept",
            "headers": {"X-User-Token": TOKEN, "Host": "dev.example.test"},
        }
    }

    scrubbed = before_send(event, {})

    assert scrubbed["request"]["url"] == "http://dev.example.test/api/v1/me"
    assert scrubbed["request"]["query_string"] == "password=[FILTERED]&token=[FILTERED]&kind=kept"
    assert scrubbed["request"]["headers"]["Host"] == "dev.example.test"
    assert PASSWORD not in json.dumps(scrubbed)
    assert TOKEN not in json.dumps(scrubbed)


def test_scrubs_filtered_keys_from_the_extra_data():
    with capture_sentry_events() as events:
        with sentry_sdk.new_scope() as scope:
            scope.set_extra("secret", TOKEN)
            scope.set_extra("kind", "kept")
            sentry_sdk.capture_message("sentry spec")

    [event] = events
    assert event["extra"]["secret"] == "[FILTERED]"
    assert event["extra"]["kind"] == "kept"
    assert TOKEN not in json.dumps(event)


def test_tags_events_with_the_release_and_the_deploy_environment(monkeypatch):
    monkeypatch.setenv("APP_RELEASE", "release-spec")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "dev")

    with capture_sentry_events() as events:
        sentry_sdk.capture_message("sentry spec")

    assert (events[-1]["release"], events[-1]["environment"]) == ("release-spec", "dev")


def test_defaults_the_environment_to_the_app_environment(monkeypatch):
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)

    with capture_sentry_events() as events:
        sentry_sdk.capture_message("sentry spec")

    assert events[-1]["environment"] == "test"


@pytest.mark.parametrize(
    "set_dsn",
    [lambda env: env.delenv("SENTRY_DSN", raising=False), lambda env: env.setenv("SENTRY_DSN", "")],
)
def test_is_disabled_when_the_dsn_is_unset_or_empty(monkeypatch, set_dsn):
    set_dsn(monkeypatch)

    assert sentry_options()["dsn"] is None


def test_reports_to_the_dsn_from_the_environment(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://key@glitchtip.example.test/1")

    assert sentry_options()["dsn"] == "https://key@glitchtip.example.test/1"
