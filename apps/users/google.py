"""Google sign-in (ADR-0004): verify a Google ID token, then sign in, link or create its user.

Any doubt is a refusal (AC-07).
Google's signing keys are kept in process memory, and Google is asked at most once per
REFETCH_COOLDOWN, whether the last call worked or not, so tokens with made-up key ids or an
outage at Google cannot make every request call Google.
"""

import base64
import json
import logging
import os
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import timedelta

import jwt
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.users.models import Identity, User
from apps.users.tokens import link_identity

logger = logging.getLogger(__name__)

CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
KEYS_TTL = timedelta(hours=1)
REFETCH_COOLDOWN = timedelta(seconds=60)

# Per key type, the members a served key must carry and those it may; a key carrying a member of
# another type is in a bad form. Every member but crv is base64url, and only oct's k may be empty.
KEY_MEMBERS = {
    "EC": ({"crv", "x", "y"}, {"d"}),
    "RSA": ({"n", "e"}, {"d", "p", "q", "dp", "dq", "qi"}),
    "oct": ({"k"}, set()),
    "OKP": ({"crv", "x"}, {"d"}),
    "AKP": ({"pub"}, {"priv"}),
}
ALL_MEMBERS = {"oth"}.union(*(required | optional for required, optional in KEY_MEMBERS.values()))
AKP_ALGS = ("ML-DSA-44", "ML-DSA-65", "ML-DSA-87")
KEY_OP_USES = {
    "sign": "sig",
    "verify": "sig",
    **dict.fromkeys(
        ("encrypt", "decrypt", "wrapKey", "unwrapKey", "deriveKey", "deriveBits"), "enc"
    ),
}


class KeysUnavailable(Exception):
    pass


def fetch_certs():
    with urllib.request.urlopen(CERTS_URL, timeout=5) as response:
        if response.status != 200:
            raise KeysUnavailable(f"Google certs answered {response.status}")
        return response.read()


def _parse(body):
    data = json.loads(body)
    keys = data.get("keys") if isinstance(data, dict) else None
    if not isinstance(keys, list) or not all(isinstance(key, dict) for key in keys):
        raise KeysUnavailable("Google certs have no keys")
    # A key of an unknown type is skipped.
    served = {}
    for key in keys:
        if key.get("kty") in KEY_MEMBERS:
            _check_key(key)
            served.setdefault(_identity(key), key)
    if not served:
        raise KeysUnavailable("Google certs have no usable keys")
    return tuple(served.values())


# Any key of a known type in a bad form refuses the set. Whether a key can verify a token is
# decided only when a token's kid selects it.
def _check_key(key):
    kty = key["kty"]
    required, optional = KEY_MEMBERS[kty]
    if not required <= key.keys() or key.keys() & (ALL_MEMBERS - required - optional):
        raise KeysUnavailable(f"Google certs hold a {kty} key with missing or foreign members")
    for name in key.keys() & (required | optional) - {"crv"}:
        if not _decode_base64url(key[name]) and kty != "oct":
            raise ValueError(f"{name} is empty")
    if kty == "AKP" and key.get("alg") not in AKP_ALGS:
        raise KeysUnavailable("Google certs hold an AKP key without its alg")
    if "key_ops" in key:
        ops = key["key_ops"]
        if len(ops) > len(KEY_OP_USES) or len(set(ops)) != len(ops):
            raise KeysUnavailable("Google certs repeat a key operation")
        if "use" in key and any(
            op not in KEY_OP_USES or KEY_OP_USES[op] != key["use"] for op in ops
        ):
            raise KeysUnavailable("Google certs give a key operations its use forbids")


# Two keys with one kid and the same key material are one key.
def _identity(key):
    kty = key["kty"]
    material = {
        name: key[name] for name in KEY_MEMBERS[kty][0] | ({"alg"} if kty == "AKP" else set())
    }
    return json.dumps([kty, material], sort_keys=True), key.get("kid")


def _decode_base64url(value):
    if len(value) % 4 == 1:
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode())


def _find_key(keyset, kid):
    found = [key for key in keyset if key.get("kid") == kid]
    if len(found) > 1:
        raise jwt.InvalidKeyError("Google certs repeat a key id")
    return found[0] if found else None


# A key's alg does not bind it, and a private key verifies with its public half.
def _verifying_key(key):
    use, ops = key.get("use"), key.get("key_ops")
    if use and use != "sig":
        raise jwt.InvalidKeyError("The Google key is not a signature key")
    if ops and "verify" not in (ops if isinstance(ops, list) else [ops]):
        raise jwt.InvalidKeyError("The Google key may not verify")
    if key["kty"] != "RSA":
        raise jwt.InvalidKeyError("The Google key is not an RSA key")
    return jwt.algorithms.RSAAlgorithm.from_jwk({"kty": "RSA", "n": key["n"], "e": key["e"]})


class KeySet:
    def __init__(self):
        self._lock = threading.Lock()
        self._keys = None
        self._fetched_at = None
        self._attempted_at = None

    def get(self, kid_not_found=False):
        with self._lock:
            if self._expired() or kid_not_found:
                self._refresh()
            return self._keys

    def _expired(self):
        return self._keys is None or self._fetched_at < timezone.now() - KEYS_TTL

    def _cooling_down(self):
        return (
            self._attempted_at is not None
            and self._attempted_at > timezone.now() - REFETCH_COOLDOWN
        )

    # During the cooldown an unknown key id is a bad token only if the last fetch worked; after a
    # failed one nothing proves the key id is not Google's.
    def _refresh(self):
        if not self._cooling_down():
            self._fetch()
        elif self._fetched_at != self._attempted_at:
            raise KeysUnavailable("Google certs not retried yet")

    # Anything that goes wrong reaching or reading Google's keys is an outage, never a crash.
    def _fetch(self):
        attempt = self._attempted_at = timezone.now()
        try:
            self._keys = _parse(fetch_certs())
        except KeysUnavailable:
            raise
        except Exception as error:
            raise KeysUnavailable(f"Google certs unusable: {type(error).__name__}") from error
        self._fetched_at = attempt


DEFAULT_KEYS = KeySet()


@dataclass(frozen=True)
class Verification:
    email: str | None = None
    uid: str | None = None
    error: str | None = None

    @property
    def success(self):
        return self.error is None


def verify_id_token(id_token, client_id=None, keys=None):
    client_id = client_id if client_id is not None else os.environ.get("GOOGLE_CLIENT_ID")
    if not (client_id or "").strip():
        return Verification(error="not_configured")
    try:
        claims = _decode(id_token, client_id, keys or DEFAULT_KEYS)
    except KeysUnavailable:
        logger.exception("Google certs unavailable")
        return Verification(error="keys_unavailable")
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        return Verification(error="invalid_token")
    if claims.get("iss") not in ISSUERS:
        return Verification(error="invalid_token")
    # Older Google tokens carry email_verified as the string "true".
    if (
        claims.get("email_verified") not in (True, "true")
        or not str(claims.get("email") or "").strip()
    ):
        return Verification(error="email_not_verified")
    return Verification(email=claims["email"], uid=claims["sub"])


def _decode(id_token, client_id, keys):
    kid = _key_id(id_token)
    keyset = keys.get()
    if _find_key(keyset, kid) is None:
        keyset = keys.get(kid_not_found=True)
    key = _find_key(keyset, kid)
    if key is None:
        raise jwt.InvalidKeyError("No Google key for the token's key id")
    claims = jwt.decode(id_token, _verifying_key(key), algorithms=["RS256"], options=SIGNATURE_ONLY)
    _check_claims(claims, client_id)
    return claims


# Read from the raw header: jwt.get_unverified_header would refuse some tokens (a kid that is not a
# string, a malformed signature) before the key set is consulted.
def _key_id(id_token):
    if not isinstance(id_token, str):
        raise TypeError("an ID token is a string")
    header = id_token.split(".")[0]
    return json.loads(base64.urlsafe_b64decode(header + "=" * (-len(header) % 4)))["kid"]


# PyJWT checks the signature only: its own claim checks compare nbf and iat and cast exp, so they
# would accept and refuse other tokens than _check_claims.
SIGNATURE_ONLY = {
    "verify_signature": True,
    **{f"verify_{name}": False for name in ("exp", "nbf", "iat", "aud", "iss", "sub", "jti")},
}


# Formats first, then iss, aud, exp and sub present, our audience among aud, and exp not past.
# No clock skew is allowed. nbf and iat are only format-checked.
def _check_claims(claims, client_id):
    for name in ("iss", "sub", "jti", "typ"):
        if claims.get(name) is not None and not isinstance(claims[name], str):
            raise jwt.InvalidTokenError(f"{name} is not a string")
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if aud is not None and not all(isinstance(value, str) for value in audiences):
        raise jwt.InvalidTokenError("aud is not a string")
    for name in ("exp", "nbf", "iat"):
        if claims.get(name) is not None:
            int(claims[name])
    if not {"iss", "aud", "exp", "sub"} <= claims.keys():
        raise jwt.MissingRequiredClaimError("iss, aud, exp or sub")
    if client_id not in audiences:
        raise jwt.InvalidAudienceError("aud")
    if claims["exp"] < time.time():
        raise jwt.ExpiredSignatureError("exp")


@dataclass(frozen=True)
class GoogleSignIn:
    user: User | None = None
    error: str | None = None


def google_sign_in(id_token):
    """Sign in the user linked to the Google account, link Google to the user with that email,
    or create a user; any refusal creates and links nothing."""
    verification = verify_id_token(id_token)
    if not verification.success:
        return GoogleSignIn(error=verification.error)
    try:
        with transaction.atomic():
            user = _linked_user(verification.uid) or _link_or_create(verification)
    except IntegrityError as error:
        # The database message names the email it collided on.
        logger.warning("Google sign-in not saved: %s", type(error).__name__)
        return GoogleSignIn(error="not_saved")
    return GoogleSignIn(user=user) if user else GoogleSignIn(error="already_linked")


def _linked_user(uid):
    identity = (
        Identity.objects.select_related("user").filter(provider=Identity.GOOGLE, uid=uid).first()
    )
    return identity.user if identity else None


def _find_by_email(email):
    return User.objects.filter(email=email.strip().lower()).first()


# Emails are compared lowercased, so a Google email never makes a second account (AC-06).
def _link_or_create(verification):
    user = _find_by_email(verification.email)
    if user is None:
        user = User(email=verification.email, password="")
        user.save()
        Identity.objects.create(user=user, provider=Identity.GOOGLE, uid=verification.uid)
        return user
    if user.identities.filter(provider=Identity.GOOGLE).exists():
        return None
    return link_identity(user, verification.uid)
