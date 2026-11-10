"""The legacy X-User-Email / X-User-Token pair (ADR-0005) and the deploy smoke token.

The pair stays accepted until the evidence cutoff; each use is counted per user and day so the
cutoff can be decided on data. LEGACY_AUTH_ENABLED=false switches the path off.
"""

import hmac
import logging
import os

from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.users.models import LegacyTokenUse, User

logger = logging.getLogger(__name__)

# The strings ActiveModel's boolean type reads as false.
_FALSE = {"false", "f", "0", "off", "FALSE", "F", "OFF"}


def legacy_enabled():
    return (os.environ.get("LEGACY_AUTH_ENABLED") or "true") not in _FALSE


def authenticate_legacy(headers):
    email = headers.get("X-User-Email")
    token = headers.get("X-User-Token")
    if not email or not token:
        return None
    user = User.objects.filter(email=email).first()
    if user and user.authentication_token:
        if hmac.compare_digest(user.authentication_token.encode(), token.encode()):
            return user
    return None


def record_legacy_use(user):
    """Count one legacy use; a failed count is logged, never allowed to refuse the request."""
    try:
        _count_use(user)
    except DatabaseError:
        logger.exception("Legacy token use not counted")


def _count_use(user):
    today = timezone.localdate()
    uses = LegacyTokenUse.objects.filter(user=user, used_on=today)
    if uses.update(uses_count=F("uses_count") + 1, updated_at=timezone.now()):
        return
    try:
        with transaction.atomic():
            LegacyTokenUse.objects.create(user=user, used_on=today, uses_count=1)
    except IntegrityError:
        uses.update(uses_count=F("uses_count") + 1, updated_at=timezone.now())


def smoke_token_presented(request):
    """The pipeline-only secret deploy checks present in X-Smoke-Token.

    A blank SMOKE_TOKEN never matches.
    """
    expected = os.environ.get("SMOKE_TOKEN", "")
    if not expected.strip():
        return False
    presented = request.headers.get("X-Smoke-Token", "")
    return hmac.compare_digest(presented.encode(), expected.encode())
