import http.client
import json
import logging
import secrets
import ssl
import threading
import time
import zlib
from datetime import timedelta

import jwt
import pytest

from apps.users import google
from apps.users.tests.conftest import GOOGLE_CLIENT_ID, jwks, make_id_token


@pytest.fixture
def keys():
    return google.KeySet()


@pytest.fixture
def key1(google_keys):
    return google_keys[0]


@pytest.fixture
def key2(google_keys):
    return google_keys[1]


@pytest.fixture
def id_token(key1):
    def id_token(key=None, kid="key-1", **claims):
        return make_id_token(key or key1, kid=kid, sub="1234567890", **claims)

    return id_token


@pytest.fixture
def verify(keys):
    def verify(token, **options):
        return google.verify_id_token(
            token, **({"client_id": GOOGLE_CLIENT_ID} | options), keys=keys
        )

    return verify


@pytest.fixture
def reports(caplog):
    caplog.set_level(logging.ERROR, logger="apps.users.google")
    return lambda: [record for record in caplog.records if record.exc_info]


def assert_refusal(result, error):
    assert not result.success
    assert result.email is None
    assert result.uid is None
    assert result.error == error


UNAVAILABLE = google.KeysUnavailable("Google certs answered 503")


class TestWhenGoogleServesItsKeys:
    @pytest.fixture(autouse=True)
    def served(self, certs, key1):
        certs.answer(jwks((key1, "key-1")))

    def test_accepts_a_google_signed_token_for_our_client_with_a_verified_email(
        self, verify, id_token
    ):
        result = verify(id_token())

        assert result.success
        assert result.email == "person@example.com"
        assert result.uid == "1234567890"
        assert result.error is None

    def test_accepts_the_issuer_form_without_the_scheme(self, verify, id_token):
        assert verify(id_token(iss="accounts.google.com")).success

    def test_refuses_a_token_signed_by_another_key_under_a_known_key_id(
        self, verify, id_token, google_keys
    ):
        assert_refusal(verify(id_token(key=google_keys[2])), "invalid_token")

    def test_refuses_a_token_issued_for_another_client(self, verify, id_token):
        assert_refusal(
            verify(id_token(aud="someone-else.apps.googleusercontent.com")), "invalid_token"
        )

    def test_refuses_a_token_from_another_issuer(self, verify, id_token):
        assert_refusal(verify(id_token(iss="https://evil.example")), "invalid_token")

    def test_refuses_an_expired_token(self, verify, id_token):
        assert_refusal(verify(id_token(exp=int(time.time()) - 60)), "invalid_token")

    def test_refuses_a_token_whose_email_google_has_not_verified(self, verify, id_token):
        assert_refusal(verify(id_token(email_verified=False)), "email_not_verified")

    def test_refuses_a_token_that_does_not_say_the_email_is_verified(self, verify, id_token):
        assert_refusal(verify(id_token(email_verified=None)), "email_not_verified")

    def test_accepts_a_token_whose_email_verified_is_the_string_true(self, verify, id_token):
        assert verify(id_token(email_verified="true")).success

    def test_refuses_a_token_without_an_email(self, verify, id_token):
        assert_refusal(verify(id_token(email=None)), "email_not_verified")

    def test_accepts_a_token_whose_iat_is_ahead_of_our_clock(self, verify, id_token):
        assert verify(id_token(iat=int(time.time()) + 300)).success

    def test_accepts_a_token_for_an_audience_list_that_holds_our_client(self, verify, id_token):
        assert verify(id_token(aud=["someone-else", GOOGLE_CLIENT_ID])).success

    def test_refuses_a_token_signed_with_a_shared_secret(self, verify):
        secret = secrets.token_bytes(32)
        token = make_id_token(secret, kid="key-1", alg="HS256", sub="1")

        assert_refusal(verify(token), "invalid_token")

    def test_refuses_something_that_is_not_a_token(self, verify):
        assert_refusal(verify("not-a-token"), "invalid_token")

    def test_refuses_a_missing_token(self, verify):
        assert_refusal(verify(None), "invalid_token")
        assert_refusal(verify(""), "invalid_token")

    def test_refuses_every_token_without_a_client_id_and_without_asking_google(
        self, verify, id_token, certs, monkeypatch
    ):
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)

        assert_refusal(verify(id_token(), client_id=None), "not_configured")
        assert certs.calls == 0

    def test_reads_the_client_id_from_google_client_id(self, id_token, keys, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID)

        assert google.verify_id_token(id_token(), keys=keys).success

    def test_fetches_the_keys_once_for_several_tokens(self, verify, id_token, certs):
        for _ in range(2):
            assert verify(id_token()).success

        assert certs.calls == 1

    def test_fetches_the_keys_again_after_an_hour(self, verify, id_token, certs, clock):
        verify(id_token())
        clock.travel(timedelta(minutes=61))

        assert verify(id_token()).success
        assert certs.calls == 2


def served_with(key1, *others):
    served = json.loads(jwks((key1, "key-1")))
    served["keys"] += others
    return json.dumps(served).encode()


def rsa_jwk(key, kid, **members):
    """The JWK of a public or private key, without the key_ops PyJWT adds, as Google serves it."""
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key, as_dict=True)
    del jwk["key_ops"]
    return jwk | {"kid": kid} | members


AN_EC_KEY = {"kty": "EC", "crv": "P-256", "x": "AAAA", "y": "AAAA"}


class TestWhenGoogleServesKeysWeCannotUse:
    """Each served key is checked for form when the set is fetched, and for use only when a
    token's key id selects it."""

    @pytest.mark.parametrize(
        "other",
        [
            lambda key: rsa_jwk(key.public_key(), "other", use="enc"),
            lambda key: rsa_jwk(key.public_key(), "other", key_ops=["sign"]),
            lambda key: rsa_jwk(key, "other"),
            lambda key: {"kty": "OKP", "crv": "X25519", "x": "AAAA", "kid": "other"},
            lambda key: AN_EC_KEY | {"kid": "other"},
            lambda key: {"kty": "AKP", "alg": "ML-DSA-44", "pub": "AAAA", "kid": "other"},
            lambda key: {"kty": "FOO", "kid": "other"},
        ],
        ids=["encryption", "signing-only", "private", "X25519", "EC", "AKP", "unknown type"],
    )
    def test_accepts_a_token_whose_key_google_serves_beside_keys_we_cannot_verify_with(
        self, verify, id_token, certs, key1, key2, other
    ):
        certs.answer(served_with(key1, other(key2)))

        assert verify(id_token()).success

    @pytest.mark.parametrize(
        "selected",
        [
            lambda key: rsa_jwk(key.public_key(), "key-2", use="enc"),
            lambda key: rsa_jwk(key, "key-2", key_ops=["sign"]),
            lambda key: AN_EC_KEY | {"kid": "key-2"},
        ],
        ids=["encryption", "signing-only", "EC"],
    )
    def test_refuses_a_token_whose_key_id_selects_a_key_we_cannot_verify_with(
        self, verify, id_token, certs, key1, key2, selected
    ):
        certs.answer(served_with(key1, selected(key2)))

        assert_refusal(verify(id_token(key=key2, kid="key-2")), "invalid_token")

    def test_verifies_with_the_public_half_of_a_served_private_key(
        self, verify, id_token, certs, key1, key2
    ):
        certs.answer(served_with(key1, rsa_jwk(key2, "key-2")))

        assert verify(id_token(key=key2, kid="key-2")).success

    def test_counts_a_key_served_twice_as_one_key(self, verify, id_token, certs, key1):
        certs.answer(served_with(key1, rsa_jwk(key1.public_key(), "key-1", use="sig")))

        assert verify(id_token()).success

    def test_refuses_a_token_whose_key_id_google_gives_two_keys(
        self, verify, id_token, certs, key1, key2
    ):
        certs.answer(served_with(key1, rsa_jwk(key2.public_key(), "key-1")))

        assert_refusal(verify(id_token()), "invalid_token")

    @pytest.mark.parametrize(
        "other",
        [
            {"kty": "AKP", "pub": "AAAA"},
            {"kty": "EC", "crv": "P-256", "x": "AAAA"},
            {"kty": "RSA", "n": "AAAA", "e": ""},
            {"kty": "RSA", "n": "AAAA", "e": "AQAB", "x": "AAAA"},
            {"kty": "RSA", "n": "AAAA", "e": "AQAB", "key_ops": ["verify", "verify"]},
            {"kty": "RSA", "n": "AAAA", "e": "AQAB", "use": "sig", "key_ops": ["encrypt"]},
        ],
        ids=[
            "AKP key without alg",
            "EC key without y",
            "empty exponent",
            "member of another key type",
            "repeated key operation",
            "use and key_ops disagree",
        ],
    )
    def test_refuses_with_keys_unavailable_a_set_with_a_key_in_a_bad_form(
        self, verify, id_token, certs, key1, reports, other
    ):
        certs.answer(served_with(key1, other | {"kid": "other"}))

        assert_refusal(verify(id_token()), "keys_unavailable")
        assert len(reports()) == 1


class TestWhenGoogleRotatesItsKeys:
    @pytest.fixture(autouse=True)
    def rotating(self, certs, key1, key2):
        certs.answer(jwks((key1, "key-1")), jwks((key1, "key-1"), (key2, "key-2")))

    def test_fetches_again_for_an_unknown_key_id_and_accepts_the_token(
        self, verify, id_token, key2, certs, clock
    ):
        assert verify(id_token()).success
        clock.travel(timedelta(minutes=2))

        assert verify(id_token(key=key2, kid="key-2")).success
        assert certs.calls == 2

    def test_does_not_fetch_again_for_an_unknown_key_id_right_after_a_fetch(
        self, verify, id_token, key2, certs
    ):
        assert verify(id_token()).success

        assert_refusal(verify(id_token(key=key2, kid="key-2")), "invalid_token")
        assert certs.calls == 1


class TestWhenGoogleCannotBeReached:
    def test_refuses_with_keys_unavailable_on_an_error_status_and_reports_it(
        self, verify, id_token, certs, reports
    ):
        certs.answer(UNAVAILABLE)

        assert_refusal(verify(id_token()), "keys_unavailable")
        assert len(reports()) == 1

    def test_refuses_with_keys_unavailable_on_a_timeout(self, verify, id_token, certs):
        certs.answer(TimeoutError())

        assert_refusal(verify(id_token()), "keys_unavailable")

    def test_refuses_with_keys_unavailable_on_a_malformed_key_set(self, verify, id_token, certs):
        certs.answer(b"not json")

        assert_refusal(verify(id_token()), "keys_unavailable")

    @pytest.mark.parametrize(
        "body",
        [
            "{}",
            '{"keys":[]}',
            "[]",
            "null",
            '"error"',
            '{"keys":"x"}',
            '{"keys":[{"kty":"FOO","kid":"z"}]}',
        ],
    )
    def test_refuses_with_keys_unavailable_and_reports_an_unusable_key_set(
        self, verify, id_token, certs, reports, body
    ):
        certs.answer(body.encode())

        assert_refusal(verify(id_token()), "keys_unavailable")
        assert len(reports()) == 1

    def test_does_not_call_google_again_within_a_minute_of_a_failed_fetch(
        self, verify, id_token, certs, clock
    ):
        certs.answer(UNAVAILABLE)

        for _ in range(2):
            assert_refusal(verify(id_token()), "keys_unavailable")
        assert certs.calls == 1

        clock.travel(timedelta(seconds=61))
        assert_refusal(verify(id_token()), "keys_unavailable")
        assert certs.calls == 2

    def test_does_not_call_google_for_made_up_key_ids_after_a_failed_refetch(
        self, verify, id_token, certs, key1, clock
    ):
        certs.answer(jwks((key1, "key-1")), UNAVAILABLE)

        assert verify(id_token()).success
        clock.travel(timedelta(minutes=2))
        results = [verify(id_token(kid="made-up")) for _ in range(5)]

        assert not any(result.success for result in results)
        assert certs.calls == 2

    def test_refuses_made_up_key_ids_after_a_failed_refetch_and_still_accepts_known_keys(
        self, verify, id_token, certs, key1, clock, reports
    ):
        certs.answer(jwks((key1, "key-1")), UNAVAILABLE)

        assert verify(id_token()).success
        clock.travel(timedelta(minutes=2))
        for _ in range(3):
            assert_refusal(verify(id_token(kid="made-up")), "keys_unavailable")

        assert verify(id_token()).success
        assert certs.calls == 2
        assert len(reports()) == 3

    @pytest.mark.parametrize(
        "error",
        [
            TimeoutError(),
            ConnectionResetError(),
            EOFError(),
            OSError(),
            http.client.BadStatusLine("garbled"),
            ssl.SSLError(),
            zlib.error(),
        ],
        ids=lambda error: type(error).__name__,
    )
    def test_refuses_with_keys_unavailable_and_reports_a_failed_call(
        self, verify, id_token, certs, reports, error
    ):
        certs.answer(error)

        assert_refusal(verify(id_token()), "keys_unavailable")
        assert len(reports()) == 1

    def test_refuses_with_keys_unavailable_and_reports_a_key_that_cannot_be_built(
        self, verify, id_token, certs, reports
    ):
        certs.answer(b'{"keys":[{"kty":"RSA","kid":"key-1","n":5,"e":"AQAB"}]}')

        assert_refusal(verify(id_token()), "keys_unavailable")
        assert len(reports()) == 1


def test_several_threads_call_google_once_while_the_first_fetch_is_running(certs, keys, key1):
    def slow_certs():
        time.sleep(0.2)
        return jwks((key1, "key-1"))

    certs.answer(slow_certs)
    results = []
    threads = [threading.Thread(target=lambda: results.append(keys.get())) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 5
    assert all(result is results[0] for result in results)
    assert [key["kid"] for key in results[0]] == ["key-1"]
    assert certs.calls == 1
