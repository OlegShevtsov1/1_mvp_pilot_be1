import json

import pytest
from urllib3.exceptions import ReadTimeoutError

from apps.errors import tunnel

ALLOWED_DSN = "https://fepublic@errors.example.test:8443/glitchtip/2"
UPSTREAM = "https://errors.example.test:8443/glitchtip/api/2/envelope/"


def envelope(dsn):
    return "\n".join(
        [
            json.dumps({"event_id": "a" * 32, "dsn": dsn}),
            json.dumps({"type": "event"}),
            json.dumps({"event_id": "a" * 32, "message": "tunnel spec é"}, ensure_ascii=False),
        ]
    ).encode()


def rejected_status(body, allowed_dsn=ALLOWED_DSN):
    with pytest.raises(tunnel.Rejected) as rejected:
        tunnel.forward(body, allowed_dsn)
    return rejected.value.status


def test_posts_the_unchanged_body_to_the_envelope_endpoint_derived_from_the_allowed_dsn(upstream):
    body = envelope(ALLOWED_DSN)
    upstream.respond(200, b'{"id":"x"}')

    assert tunnel.forward(body, ALLOWED_DSN) == (200, b'{"id":"x"}')
    [call] = upstream.calls
    assert (call["method"], call["url"], call["body"]) == ("POST", UPSTREAM, body)
    assert call["headers"]["Content-Type"] == "application/x-sentry-envelope"
    auth = call["headers"]["X-Sentry-Auth"]
    assert "sentry_key=fepublic" in auth
    assert "sentry_secret" not in auth


def test_derives_the_endpoint_for_a_dsn_without_a_path_prefix_or_port(upstream):
    dsn = "http://fepublic@errors.example.test/7"
    upstream.respond(200)

    assert tunnel.forward(envelope(dsn), dsn)[0] == 200
    assert [call["url"] for call in upstream.calls] == [
        "http://errors.example.test/api/7/envelope/"
    ]


def test_passes_an_upstream_error_status_through(upstream):
    upstream.respond(429, b"")

    assert tunnel.forward(envelope(ALLOWED_DSN), ALLOWED_DSN)[0] == 429


@pytest.mark.parametrize(
    "dsn",
    [
        "https://otherkey@errors.example.test:8443/glitchtip/2",
        "https://fepublic@errors.example.test:8443/glitchtip/3",
        "https://errors.example.test:8443/glitchtip/2",
        "https://fepublic@attacker.example.test/3",
        "https://otherkey@attacker.example.test/2",
    ],
)
def test_rejects_a_dsn_with_403_and_forwards_nothing(upstream, dsn):
    assert rejected_status(envelope(dsn)) == 403
    assert upstream.calls == []


@pytest.mark.parametrize(
    "dsn",
    [
        "https://fepublic@attacker.example.test/2",
        "http://fepublic@errors.example.test:8443/glitchtip/2",
        "https://fepublic:secret@attacker.example.test/2",
        "https://fepublic@api.example.test:9999/other/prefix/2",
    ],
)
def test_forwards_to_the_allowed_dsns_endpoint_never_to_its_host(upstream, dsn):
    upstream.respond(200)

    assert tunnel.forward(envelope(dsn), ALLOWED_DSN)[0] == 200
    assert [call["url"] for call in upstream.calls] == [UPSTREAM]


@pytest.mark.parametrize(
    "first_line",
    [
        "not json",
        "[1]",
        '{"event_id":"x"}',
        '{"dsn":"http://[bad"}',
        '{"dsn":"https://fepublic@api example.test/2"}',
        '{"dsn":"https://fepublic@api.example.test/2\\u00e9"}',
        '{"dsn":"https://fepublic@api.example.test/%zz/2"}',
        '{"dsn":"mailto:a@b"}',
        "",
        "[" * 100_000,
    ],
)
def test_rejects_the_envelope_header_with_400(upstream, first_line):
    assert rejected_status(f"{first_line}\n{{}}".encode()) == 400
    assert upstream.calls == []


@pytest.mark.parametrize(
    "dsn",
    [
        ALLOWED_DSN + '?a={|^`\\"<%',
        ALLOWED_DSN + "?a[b]=1",
        ALLOWED_DSN + "#a?b/c",
        "https://fepublic@[::1]:8443/glitchtip/2",
        "https://fepublic@errors.example.test:/2",
    ],
)
def test_forwards_a_dsn_the_uri_grammar_accepts(upstream, dsn):
    upstream.respond(200)

    assert tunnel.forward(envelope(dsn), ALLOWED_DSN)[0] == 200
    assert [call["url"] for call in upstream.calls] == [UPSTREAM]


@pytest.mark.parametrize(
    "dsn",
    [
        "https://fepublic@errors.example.test:abc/2",
        ALLOWED_DSN + "#a#b",
        "https://fepublic@errors.example.test:8443/glitch[tip/2",
        "https://fepublic@errors.example.test:8443/glitchtip]/2",
        ALLOWED_DSN + "?a=%zz",
        ALLOWED_DSN + "#{",
    ],
)
def test_rejects_a_dsn_the_uri_grammar_refuses_with_400(upstream, dsn):
    assert rejected_status(envelope(dsn)) == 400
    assert upstream.calls == []


def test_answers_502_when_glitchtip_does_not_answer_in_time(upstream):
    upstream.responder = lambda call: ReadTimeoutError(None, call["url"], "Read timed out.")

    assert rejected_status(envelope(ALLOWED_DSN)) == 502
