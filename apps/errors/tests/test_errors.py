import json

import pytest
from django.core.cache import caches
from django.core.cache.backends.locmem import LocMemCache
from django.test import override_settings

from apps.common import rate_limit
from apps.errors import tunnel

ALLOWED_DSN = "https://fepublic@errors.example.test/2"
UPSTREAM = "https://errors.example.test/api/2/envelope/"


@pytest.fixture(autouse=True)
def allowed_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_ALLOWED_FE_DSN", ALLOWED_DSN)
    return ALLOWED_DSN


def envelope(dsn=ALLOWED_DSN):
    return f'{json.dumps({"dsn": dsn})}\n{{"type":"event"}}\n{{"message":"errors spec"}}'


def refused_envelope():
    return envelope("https://other@errors.example.test/2")


def too_large_envelope():
    return f"{envelope()}\n{'x' * tunnel.MAX_BYTES}"


def post_envelope(client, body=None, **extra):
    return client.post(
        "/api/errors",
        envelope() if body is None else body,
        content_type="text/plain;charset=UTF-8",
        **extra,
    )


def post_statuses(client, count, body):
    return [post_envelope(client, body).status_code for _ in range(count)]


def post_statuses_from(client, count, forwarded_for):
    return [
        post_envelope(client, refused_envelope(), HTTP_X_FORWARDED_FOR=forwarded_for).status_code
        for _ in range(count)
    ]


def post_alternating(client, count, **extra):
    return [
        post_envelope(client, envelope() if i % 2 == 0 else refused_envelope(), **extra).status_code
        for i in range(count)
    ]


def alternating_statuses(count):
    return [200 if i % 2 == 0 else 403 for i in range(count)]


def fail_cache_increments(monkeypatch, failing):
    """Calls numbered in `failing` fail, as an unreachable shared cache does."""
    cache = caches["default"]
    original = cache.incr
    calls = 0

    def incr(*args, **kwargs):
        nonlocal calls
        calls += 1
        if failing(calls):
            raise ConnectionError("cache unreachable")
        return original(*args, **kwargs)

    monkeypatch.setattr(cache, "incr", incr)


def bodies(upstream):
    return [call["body"].decode() for call in upstream.calls]


def test_relays_an_envelope_for_the_allowed_dsn_and_passes_the_upstream_answer_through(
    client, upstream
):
    upstream.respond(200, b'{"id":"x"}')

    response = post_envelope(client)

    assert response.status_code == 200
    assert response.content == b'{"id":"x"}'
    assert [call["url"] for call in upstream.calls] == [UPSTREAM]
    assert bodies(upstream) == [envelope()]


def test_refuses_another_dsn_with_403_without_forwarding(client, upstream):
    response = post_envelope(client, refused_envelope())

    assert response.status_code == 403
    assert response.json() == {"error": "dsn not allowed"}
    assert upstream.calls == []


def test_refuses_a_body_over_256_kib_with_413(client, upstream):
    response = post_envelope(client, too_large_envelope())

    assert response.status_code == 413
    assert upstream.calls == []


def test_limits_one_client_to_30_envelopes_a_minute(client, upstream):
    upstream.respond(200, b"{}")

    statuses = post_statuses(client, 31, envelope())

    assert statuses == [200] * 30 + [429]


def test_limits_one_client_to_30_refused_envelopes_a_minute(client, upstream):
    statuses = post_statuses(client, 31, refused_envelope())

    assert statuses == [403] * 30 + [429]
    assert upstream.calls == []


def test_counts_accepted_and_refused_envelopes_against_the_same_limit(client, upstream):
    upstream.respond(200, b"{}")

    assert post_alternating(client, 31) == alternating_statuses(30) + [429]


def test_keeps_limiting_accepted_and_refused_alike_when_the_cache_store_fails(
    client, upstream, monkeypatch
):
    upstream.respond(200, b"{}")
    fail_cache_increments(monkeypatch, lambda call: True)

    statuses = post_alternating(client, 31, REMOTE_ADDR="203.0.113.77")

    assert statuses == alternating_statuses(30) + [429]


@override_settings(TRUSTED_PROXIES=["127.0.0.1/32"])
def test_limits_each_client_a_trusted_proxy_forwards_separately(client):
    clients = [f"203.0.113.{i}" for i in range(31)]

    assert [
        post_envelope(client, refused_envelope(), HTTP_X_FORWARDED_FOR=ip).status_code
        for ip in clients
    ] == [403] * 31
    assert post_statuses_from(client, 31, "203.0.113.200") == [403] * 30 + [429]


def test_counts_a_too_large_request_toward_the_shared_limit(client):
    post_statuses(client, 29, refused_envelope())

    assert post_envelope(client, too_large_envelope()).status_code == 413
    assert post_envelope(client, refused_envelope()).status_code == 429


def test_keeps_the_count_when_the_cache_store_recovers_mid_window(client, monkeypatch):
    fail_cache_increments(monkeypatch, lambda call: call <= 25)

    assert post_statuses(client, 31, refused_envelope()) == [403] * 30 + [429]


def test_keeps_the_count_when_the_cache_store_fails_mid_window(client, monkeypatch):
    fail_cache_increments(monkeypatch, lambda call: call >= 26)

    assert post_statuses(client, 31, refused_envelope()) == [403] * 30 + [429]


def test_keeps_the_count_in_the_cache_store_for_a_process_that_has_not_counted_yet(
    client, monkeypatch
):
    post_statuses(client, 29, refused_envelope())
    monkeypatch.setattr(rate_limit, "FALLBACK", LocMemCache("rate-limit-fresh", {}))

    assert post_envelope(client, refused_envelope()).status_code == 403
    assert post_envelope(client, refused_envelope()).status_code == 429


class TestWhenTheFrontendPublishesTheDsnWithItsPublicHost:
    ALLOWED_DSN = "http://fepublic@errors.internal.test:8000/2"
    UPSTREAM = "http://errors.internal.test:8000/api/2/envelope/"
    PUBLIC_DSN = "https://fepublic@api.example.test/2"

    @pytest.fixture(autouse=True)
    def allowed_dsn(self, monkeypatch):
        monkeypatch.setenv("SENTRY_ALLOWED_FE_DSN", self.ALLOWED_DSN)

    def test_relays_the_old_full_dsn_form_to_the_internal_glitchtip(self, client, upstream):
        upstream.respond(200, b"{}")

        response = post_envelope(client, envelope(self.ALLOWED_DSN))

        assert response.status_code == 200
        assert [call["url"] for call in upstream.calls] == [self.UPSTREAM]
        assert bodies(upstream) == [envelope(self.ALLOWED_DSN)]

    def test_relays_the_public_host_form_to_the_internal_glitchtip_and_never_contacts_its_host(
        self, client, upstream
    ):
        upstream.respond(200, b'{"id":"x"}')

        response = post_envelope(client, envelope(self.PUBLIC_DSN))

        assert response.status_code == 200
        assert response.content == b'{"id":"x"}'
        [call] = upstream.calls
        assert call["url"] == self.UPSTREAM
        assert call["body"].decode() == envelope(self.PUBLIC_DSN)
        assert "sentry_key=fepublic" in call["headers"]["X-Sentry-Auth"]

    def test_relays_the_public_host_form_when_the_allowed_dsn_carries_a_secret_key(
        self, client, upstream, monkeypatch
    ):
        monkeypatch.setenv(
            "SENTRY_ALLOWED_FE_DSN", "http://fepublic:allowedsecret@errors.internal.test:8000/2"
        )
        upstream.respond(200, b"{}")

        response = post_envelope(client, envelope(self.PUBLIC_DSN))

        assert response.status_code == 200
        assert [call["url"] for call in upstream.calls] == [self.UPSTREAM]
        assert bodies(upstream) == [envelope(self.PUBLIC_DSN)]

    def test_refuses_the_public_host_with_another_key(self, client, upstream):
        response = post_envelope(client, envelope("https://other@api.example.test/2"))

        assert response.status_code == 403
        assert upstream.calls == []

    def test_refuses_the_public_host_with_another_project(self, client, upstream):
        response = post_envelope(client, envelope("https://fepublic@api.example.test/3"))

        assert response.status_code == 403
        assert upstream.calls == []


def test_does_not_exist_while_no_frontend_dsn_is_configured(client, monkeypatch):
    monkeypatch.delenv("SENTRY_ALLOWED_FE_DSN")

    assert post_envelope(client).status_code == 404


def test_answers_another_method_with_404(client, upstream):
    response = client.get("/api/errors")

    assert response.status_code == 404
    assert response.content == b""
    assert upstream.calls == []


def test_relays_a_valid_envelope_that_glitchtip_accepts_authenticated_with_the_dsn_public_key(
    client, upstream
):
    """Regression: GlitchTip answered 403 {"detail":"Denied"} to
    every tunnelled envelope, because the forward carried no Sentry auth. Unlike Sentry Relay,
    GlitchTip ignores the DSN in the envelope header and needs the public key in X-Sentry-Auth."""

    def glitchtip(call):
        auth = call["headers"].get("X-Sentry-Auth", "")
        fields = [field.strip() for field in auth.removeprefix("Sentry ").split(",")]
        if auth.startswith("Sentry ") and "sentry_key=fepublic" in fields:
            return 200, b'{"id":"x"}'
        return 403, b'{"detail":"Denied"}'

    upstream.responder = glitchtip
    body = envelope().replace("errors spec", "glitchtip auth regression")

    response = post_envelope(client, body)

    assert response.status_code == 200
    assert response.content == b'{"id":"x"}'
    assert [call["url"] for call in upstream.calls] == [UPSTREAM]
    assert bodies(upstream) == [body]
