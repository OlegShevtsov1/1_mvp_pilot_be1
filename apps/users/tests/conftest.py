import itertools
import json
import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application, set_token_value
from oauthlib.common import generate_token

from apps.users import google
from apps.users.models import User

_numbers = itertools.count(1)


@pytest.fixture
def make_user(db):
    def make(email=None, password="password"):
        return User.objects.create_user(email or f"test{next(_numbers)}@example.com", password)

    return make


@pytest.fixture
def user(make_user):
    return make_user()


@pytest.fixture
def web_client(db):
    return Application.objects.create(
        name="todolist web",
        client_id="web-client-test",
        client_type=Application.CLIENT_PUBLIC,
        authorization_grant_type=Application.GRANT_PASSWORD,
    )


@pytest.fixture
def make_access_token(db):
    """An access token without a refresh token."""

    def make(user, application=None, expires_in=3600):
        application = application or Application.objects.create(
            name=f"client {next(_numbers)}",
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_PASSWORD,
        )
        token = AccessToken(
            user=user,
            application=application,
            expires=timezone.now() + timedelta(seconds=expires_in),
            scope="",
        )
        token.plaintext = generate_token()
        set_token_value(token, token.plaintext)
        token.save()
        return token

    return make


class Clock:
    def __init__(self, now):
        self.now = now

    def travel_to(self, *args):
        self.now = datetime(*args, tzinfo=UTC) if len(args) > 1 else args[0]

    def travel(self, delta):
        self.now += delta


@pytest.fixture
def clock(monkeypatch):
    """Stands in for travel_to/freeze_time: the code reads wall time only through timezone.now."""
    frozen = Clock(timezone.now())
    monkeypatch.setattr(timezone, "now", lambda: frozen.now)
    return frozen


GOOGLE_CLIENT_ID = "test-client.apps.googleusercontent.com"


@pytest.fixture(scope="session")
def google_keys():
    """Fixture keys stand in for Google's; generated once per run, never committed."""
    return [rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(3)]


def jwks(*pairs):
    keys = []
    for key, kid in pairs:
        public = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
        keys.append(
            {
                "kty": "RSA",
                "n": public["n"],
                "e": public["e"],
                "kid": kid,
                "use": "sig",
                "alg": "RS256",
            }
        )
    return json.dumps({"keys": keys}).encode()


def make_id_token(key, kid="k1", alg="RS256", **claims):
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": GOOGLE_CLIENT_ID,
        "sub": "google-1",
        "email": "person@example.com",
        "email_verified": True,
        "iat": now,
        "exp": now + 600,
    } | claims
    claims = {name: value for name, value in payload.items() if value is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


class Certs:
    """Google's certs endpoint: answers queued bodies or errors in turn, the last one forever."""

    def __init__(self):
        self.answers = []
        self.calls = 0

    def answer(self, *answers):
        self.answers = list(answers)

    def __call__(self):
        self.calls += 1
        answer = self.answers[0] if len(self.answers) == 1 else self.answers.pop(0)
        if isinstance(answer, BaseException) or (
            isinstance(answer, type) and issubclass(answer, BaseException)
        ):
            raise answer
        return answer() if callable(answer) else answer


@pytest.fixture
def certs(monkeypatch):
    stub = Certs()
    monkeypatch.setattr(google, "fetch_certs", stub)
    monkeypatch.setattr(google, "DEFAULT_KEYS", google.KeySet())
    return stub
