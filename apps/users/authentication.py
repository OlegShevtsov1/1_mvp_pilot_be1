from rest_framework.authentication import BaseAuthentication

from apps.users.legacy import (
    authenticate_legacy,
    legacy_enabled,
    record_legacy_use,
    smoke_token_presented,
)
from apps.users.tokens import access_token_for, bearer_token


class DualSchemeAuthentication(BaseAuthentication):
    """An OAuth bearer token, or the legacy X-User-Email / X-User-Token pair.

    A bearer token decides alone; only a request without one falls back to the legacy pair
    (ADR-0005). `request.auth` is the AccessToken, or None for the legacy pair.
    """

    def authenticate(self, request):
        raw = bearer_token(request)
        if raw is not None:
            token = access_token_for(raw)
            return (token.user, token) if token and token.user else None

        if not legacy_enabled():
            return None
        user = authenticate_legacy(request.headers)
        if user is None:
            return None
        if not smoke_token_presented(request):
            record_legacy_use(user)
        return (user, None)
