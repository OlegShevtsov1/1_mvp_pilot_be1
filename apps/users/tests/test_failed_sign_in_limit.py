from datetime import UTC, datetime

import pytest
from django.core.cache import cache, caches
from django.db import OperationalError
from django.test import override_settings
from oauth2_provider.models import AccessToken

from apps.common import rate_limit
from apps.users import accounts
from apps.users.models import User
from apps.users.oauth import Validator
from tests.contract import assert_matches_contract

SOURCE = "203.0.113.7"
MESSAGE = "Too many failed sign-ins from this address. Wait a minute before trying again"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def frozen(clock):
    """Windows are clock minutes; a frozen clock keeps a test's attempts in one."""
    return clock


def at(minute, second):
    return datetime(2026, 1, 1, 12, minute, second, tzinfo=UTC)


@pytest.fixture
def legacy_sign_in(client, user):
    def sign_in(email=None, password="wrong-password", source=SOURCE, headers=None):
        response = client.post(
            "/api/v1/sign_in",
            {"email": email or user.email, "password": password},
            content_type="application/json",
            headers=headers or {},
            REMOTE_ADDR=source,
        )
        assert_matches_contract(response, "post", "/api/v1/sign_in")
        return response

    return sign_in


@pytest.fixture
def token_sign_in(client, user, web_client):
    def sign_in(email=None, password="wrong-password", source=SOURCE):
        response = client.post(
            "/oauth/token",
            {
                "grant_type": "password",
                "client_id": web_client.client_id,
                "username": email or user.email,
                "password": password,
            },
            REMOTE_ADDR=source,
        )
        assert_matches_contract(response, "post", "/oauth/token")
        return response

    return sign_in


@pytest.fixture
def fail_legacy(legacy_sign_in):
    def fail(count, **options):
        for _ in range(count):
            assert legacy_sign_in(**options).status_code == 401

    return fail


@pytest.fixture
def fail_token(token_sign_in):
    def fail(count, **options):
        for _ in range(count):
            assert token_sign_in(**options).status_code == 400

    return fail


@pytest.fixture
def wrap_check_password(monkeypatch):
    """Runs `before(user)` ahead of every password check."""
    original = User.check_password

    def wrap(before):
        def check_password(self, raw_password):
            before(self)
            return original(self, raw_password)

        monkeypatch.setattr(User, "check_password", check_password)

    def restore():
        monkeypatch.setattr(User, "check_password", original)

    wrap.restore = restore
    return wrap


def assert_wait_refusal(response):
    assert response.status_code == 429
    assert response["Retry-After"] == "60"
    assert response.json() == {"errors": [MESSAGE]}


def clear_counters():
    cache.clear()
    rate_limit.FALLBACK.clear()


class TestAC09:
    def test_gives_an_unknown_email_and_a_wrong_password_the_same_refusal_at_sign_in(
        self, legacy_sign_in
    ):
        unknown_email = legacy_sign_in(email="nobody@example.com")
        wrong_password = legacy_sign_in()

        assert (unknown_email.status_code, unknown_email.json()) == (
            wrong_password.status_code,
            wrong_password.json(),
        )
        assert wrong_password.status_code == 401
        assert wrong_password.json() == {"status": "error", "message": "Invalid email or password"}

    def test_gives_an_unknown_email_and_a_wrong_password_the_same_refusal_at_oauth_token(
        self, token_sign_in
    ):
        unknown_email = token_sign_in(email="nobody@example.com")
        wrong_password = token_sign_in()

        assert (unknown_email.status_code, unknown_email.json()) == (
            wrong_password.status_code,
            wrong_password.json(),
        )
        assert wrong_password.status_code == 400
        assert wrong_password.json()["error"] == "invalid_grant"


class TestAC10:
    def test_refuses_the_eleventh_failure_at_oauth_token_before_the_password_is_checked(
        self, fail_token, token_sign_in, monkeypatch
    ):
        fail_token(10)

        def unexpected(*args, **kwargs):
            pytest.fail("the password was checked")

        monkeypatch.setattr(Validator, "validate_user", unexpected)

        assert_wait_refusal(token_sign_in(password="password"))
        assert AccessToken.objects.count() == 0

    def test_refuses_the_eleventh_failure_at_sign_in_before_the_password_is_checked(
        self, fail_legacy, legacy_sign_in, monkeypatch
    ):
        fail_legacy(10)

        def unexpected(*args, **kwargs):
            pytest.fail("the password was checked")

        monkeypatch.setattr(accounts, "sign_in", unexpected)

        assert_wait_refusal(legacy_sign_in(password="password"))

    def test_counts_failures_at_both_doors_together(self, fail_token, fail_legacy, token_sign_in):
        fail_token(5)
        fail_legacy(5)

        assert_wait_refusal(token_sign_in())

    def test_counts_an_unknown_email_like_a_wrong_password(self, fail_legacy, legacy_sign_in):
        fail_legacy(10, email="nobody@example.com")

        assert_wait_refusal(legacy_sign_in(email="nobody@example.com"))

    def test_counts_an_unknown_email_like_a_wrong_password_at_oauth_token(
        self, fail_token, token_sign_in
    ):
        fail_token(10, email="nobody@example.com")

        assert_wait_refusal(token_sign_in(email="nobody@example.com"))

    def test_does_not_count_successful_sign_ins(self, legacy_sign_in, token_sign_in, fail_legacy):
        for _ in range(10):
            assert legacy_sign_in(password="password").status_code == 200
            assert token_sign_in(password="password").status_code == 200
        fail_legacy(10)

        assert_wait_refusal(legacy_sign_in())

    def test_keeps_the_failures_counted_before_a_successful_sign_in(
        self, fail_legacy, legacy_sign_in
    ):
        fail_legacy(9)
        assert legacy_sign_in(password="password").status_code == 200
        fail_legacy(1)

        assert_wait_refusal(legacy_sign_in())

    def test_does_not_let_a_success_whose_window_ended_during_its_check_lower_the_next_window(
        self, fail_legacy, legacy_sign_in, wrap_check_password
    ):
        fail_legacy(1)
        wrap_check_password(lambda user: clear_counters())
        assert legacy_sign_in(password="password").status_code == 200
        wrap_check_password.restore()
        fail_legacy(10)

        assert_wait_refusal(legacy_sign_in())

    def test_does_not_count_an_attempt_whose_check_failed_with_a_server_error_at_sign_in(
        self, legacy_sign_in, monkeypatch
    ):
        original = User.check_password

        def broken(self, raw_password):
            raise ValueError("invalid hash")

        monkeypatch.setattr(User, "check_password", broken)
        for _ in range(10):
            with pytest.raises(ValueError):
                legacy_sign_in()
        monkeypatch.setattr(User, "check_password", original)

        assert legacy_sign_in().status_code == 401

    def test_does_not_count_an_attempt_whose_check_failed_with_a_server_error_at_oauth_token(
        self, token_sign_in, monkeypatch
    ):
        original = User.check_password

        def broken(self, raw_password):
            raise ValueError("invalid hash")

        monkeypatch.setattr(User, "check_password", broken)
        for _ in range(10):
            with pytest.raises(ValueError):
                token_sign_in()
        monkeypatch.setattr(User, "check_password", original)

        assert token_sign_in().status_code == 400

    def test_gives_back_an_attempt_once_when_a_server_error_follows_its_right_password(
        self, fail_token, token_sign_in, monkeypatch
    ):
        fail_token(9)
        original = Validator.save_bearer_token

        def broken(*args, **kwargs):
            raise OperationalError("connection timeout")

        monkeypatch.setattr(Validator, "save_bearer_token", broken)
        with pytest.raises(OperationalError):
            token_sign_in(password="password")
        monkeypatch.setattr(Validator, "save_bearer_token", original)
        fail_token(1)

        assert_wait_refusal(token_sign_in())

    def test_refuses_an_attempt_that_arrives_while_the_tenth_failure_is_still_being_checked(
        self, fail_legacy, legacy_sign_in, wrap_check_password
    ):
        fail_legacy(9)
        checks = []
        second = []

        def while_checking(user):
            checks.append(user)
            if len(checks) == 1:
                second.append(legacy_sign_in())

        wrap_check_password(while_checking)

        first = legacy_sign_in()

        assert_wait_refusal(second[0])
        assert first.status_code == 401
        assert len(checks) == 1

    def test_keeps_counting_the_window_a_restart_left_only_in_the_cache(
        self, frozen, fail_legacy, legacy_sign_in, wrap_check_password
    ):
        frozen.travel_to(at(0, 10))
        fail_legacy(1)
        rate_limit.FALLBACK.clear()
        frozen.travel_to(at(0, 40))
        wrap_check_password(lambda user: frozen.travel_to(at(1, 15)))
        assert legacy_sign_in(password="password").status_code == 200
        wrap_check_password.restore()
        frozen.travel_to(at(1, 45))
        fail_legacy(5)
        rate_limit.FALLBACK.clear()
        fail_legacy(5)

        assert_wait_refusal(legacy_sign_in())

    def test_does_not_take_a_give_back_from_the_next_window_another_failure_opened(
        self, frozen, fail_legacy, legacy_sign_in, wrap_check_password
    ):
        frozen.travel_to(at(0, 50))
        checks = []

        def while_checking(user):
            checks.append(user)
            if len(checks) == 1:
                frozen.travel_to(at(1, 55))
                assert legacy_sign_in().status_code == 401

        wrap_check_password(while_checking)
        assert legacy_sign_in(password="password").status_code == 200
        fail_legacy(9)

        assert_wait_refusal(legacy_sign_in())

    def test_keeps_each_source_apart(self, fail_legacy, legacy_sign_in):
        fail_legacy(10)

        assert legacy_sign_in(source="203.0.113.8").status_code == 401

    def test_keeps_limiting_when_the_cache_fails(self, fail_legacy, legacy_sign_in, monkeypatch):
        def broken(*args, **kwargs):
            raise ConnectionError("cache down")

        monkeypatch.setattr(caches["default"], "incr", broken)
        fail_legacy(10)

        assert_wait_refusal(legacy_sign_in())


class TestBehindAProxy:
    """127.0.0.1 stands for the proxy hop; loopback and private ranges are trusted alike."""

    PROXY = "127.0.0.1"

    def keys_on_the_forwarded_address(self, legacy_sign_in):
        for i in range(10):
            response = legacy_sign_in(
                source=self.PROXY, headers={"X-Forwarded-For": f"203.0.113.{100 + i}, 203.0.113.10"}
            )
            assert response.status_code == 401

        assert_wait_refusal(
            legacy_sign_in(source=self.PROXY, headers={"X-Forwarded-For": "203.0.113.10"})
        )

    def test_keys_on_the_address_the_proxy_forwards(self, legacy_sign_in):
        self.keys_on_the_forwarded_address(legacy_sign_in)

        other = legacy_sign_in(source=self.PROXY, headers={"X-Forwarded-For": "203.0.113.11"})
        assert other.status_code == 401

    def test_ignores_the_forwarded_header_from_a_caller_that_is_not_the_proxy(self, legacy_sign_in):
        direct = "198.51.100.7"
        for i in range(10):
            response = legacy_sign_in(
                source=direct, headers={"X-Forwarded-For": f"203.0.113.{i + 1}"}
            )
            assert response.status_code == 401

        assert_wait_refusal(
            legacy_sign_in(source=direct, headers={"X-Forwarded-For": "203.0.113.50"})
        )

    @override_settings(TRUSTED_PROXIES=["127.0.0.1/32"])
    def test_accepts_a_configured_trusted_proxy_list(self, legacy_sign_in):
        self.keys_on_the_forwarded_address(legacy_sign_in)
