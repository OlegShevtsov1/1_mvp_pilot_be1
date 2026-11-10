import pytest
from django.test import RequestFactory

from apps.users.legacy import authenticate_legacy, legacy_enabled, smoke_token_presented
from apps.users.models import User


def legacy_headers(email, token):
    return {"X-User-Email": email, "X-User-Token": token}


@pytest.mark.django_db
def test_authenticates_a_matching_email_and_token(user):
    assert authenticate_legacy(legacy_headers(user.email, user.authentication_token)) == user


@pytest.mark.django_db
def test_does_not_authenticate_a_wrong_token(user):
    assert authenticate_legacy(legacy_headers(user.email, "not-the-token")) is None


@pytest.mark.django_db
def test_does_not_authenticate_a_blank_token_against_a_blank_stored_token(user):
    User.objects.filter(pk=user.pk).update(authentication_token="")

    assert authenticate_legacy(legacy_headers(user.email, "")) is None


@pytest.mark.django_db
def test_does_not_authenticate_an_unknown_email(user):
    assert (
        authenticate_legacy(legacy_headers("nobody@example.com", user.authentication_token)) is None
    )


@pytest.mark.parametrize(
    ("value", "enabled"),
    [
        (None, True),
        ("", True),
        ("true", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("FALSE", False),
        ("f", False),
        ("F", False),
        ("0", False),
        ("off", False),
        ("OFF", False),
    ],
)
def test_legacy_enabled_reads_legacy_auth_enabled_as_a_boolean(monkeypatch, value, enabled):
    if value is None:
        monkeypatch.delenv("LEGACY_AUTH_ENABLED", raising=False)
    else:
        monkeypatch.setenv("LEGACY_AUTH_ENABLED", value)

    assert legacy_enabled() is enabled


def smoke_request(token=None):
    headers = {} if token is None else {"HTTP_X_SMOKE_TOKEN": token}
    return RequestFactory().get("/", **headers)


def test_smoke_token_matches_the_configured_secret(monkeypatch):
    monkeypatch.setenv("SMOKE_TOKEN", "smoke-test-token")

    assert smoke_token_presented(smoke_request("smoke-test-token"))
    assert not smoke_token_presented(smoke_request("wrong"))
    assert not smoke_token_presented(smoke_request())


@pytest.mark.parametrize("configured", [None, "", "  "])
def test_a_blank_smoke_token_never_matches(monkeypatch, configured):
    if configured is None:
        monkeypatch.delenv("SMOKE_TOKEN", raising=False)
    else:
        monkeypatch.setenv("SMOKE_TOKEN", configured)

    assert not smoke_token_presented(smoke_request(""))
    assert not smoke_token_presented(smoke_request("  "))
