"""OAuth access and refresh tokens outside the token endpoint: lookup, issue, revoke."""

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from oauth2_provider.models import (
    AccessToken,
    Application,
    RefreshToken,
    revoke_access_token,
    set_token_value,
)
from oauth2_provider.settings import oauth2_settings
from oauthlib.common import generate_token

from apps.users.models import Identity, User

logger = logging.getLogger(__name__)

_BEARER = re.compile(r"^Bearer (.+)$", re.IGNORECASE)


def bearer_token(request):
    """The token of a `Bearer` Authorization header."""
    match = _BEARER.match(request.headers.get("Authorization", ""))
    return match.group(1) if match and match.group(1).strip() else None


def access_token_for(raw):
    """The unexpired access token whose value is `raw`; revoked tokens no longer exist."""
    checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    token = AccessToken.objects.select_related("user").filter(token_checksum=checksum).first()
    return token if token and not token.is_expired() else None


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


def issue_tokens(user):
    """One token pair for the web client named by OAUTH_CLIENT_ID.

    Without that client nothing is issued, so legacy-token callers keep working while the
    variable is unset; a uid that names no application is a misconfiguration and is reported.
    """
    uid = os.environ.get("OAUTH_CLIENT_ID", "").strip()
    if not uid:
        return None
    application = Application.objects.filter(client_id=uid).first()
    if application is None:
        logger.warning("No token pair issued: no OAuth application has OAUTH_CLIENT_ID's uid")
        return None

    expires_in = oauth2_settings.ACCESS_TOKEN_EXPIRE_SECONDS
    access = AccessToken(
        user=user,
        application=application,
        expires=timezone.now() + timedelta(seconds=expires_in),
        scope="",
    )
    access_value = generate_token()
    set_token_value(access, access_value)
    access.save()
    refresh = RefreshToken(user=user, application=application, access_token=access)
    refresh_value = generate_token()
    set_token_value(refresh, refresh_value)
    refresh.save()
    return IssuedTokens(access_value, refresh_value, expires_in)


def revoke_device(user, access_token):
    """Sign-out: a bearer token ends with its refresh token; the
    legacy token belongs to the account, so it is rotated for every device using it."""
    if access_token is not None:
        revoke_access_token(access_token)
        return
    user.authentication_token = None
    user.save(update_fields=["authentication_token", "updated_at"])


def link_identity(user, uid):
    """Link Google to `user` and end every other way in: password, tokens, legacy token.

    The row lock is the one the password and refresh grants take before they check the user,
    so a token they write meanwhile is revoked here or refused after.
    """
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        Identity.objects.create(user=user, provider=Identity.GOOGLE, uid=uid)
        for refresh in RefreshToken.objects.filter(user=user, revoked__isnull=True):
            refresh.revoke()
        AccessToken.objects.filter(user=user).delete()
        user.password = ""
        user.authentication_token = None
        user.save()
    return user
