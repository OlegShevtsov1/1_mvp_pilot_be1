"""POST /oauth/token and /oauth/revoke.

django-oauth-toolkit issues and stores the tokens; this module narrows it to the offered grants
(password, refresh_token, google_id_token), reads JSON bodies, and renders the OAuth bodies.
"""

import hashlib
import json

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from oauth2_provider import views as dot_views
from oauth2_provider.models import AccessToken, RefreshToken, revoke_access_token
from oauth2_provider.oauth2_backends import OAuthLibCore
from oauth2_provider.oauth2_validators import OAuth2Validator
from oauthlib.oauth2.rfc6749 import errors
from oauthlib.oauth2.rfc6749.endpoints import ResourceEndpoint, RevocationEndpoint, TokenEndpoint
from oauthlib.oauth2.rfc6749.grant_types import (
    RefreshTokenGrant,
    ResourceOwnerPasswordCredentialsGrant,
)
from oauthlib.oauth2.rfc6749.grant_types.base import GrantTypeBase
from oauthlib.oauth2.rfc6749.tokens import BearerToken

from apps.common.exceptions import public_exception_body
from apps.users.google import google_sign_in
from apps.users.limits import limit_failed_sign_ins
from apps.users.models import User

# The OAuth error_description text for each error code.
OAUTH_ERROR_DESCRIPTIONS = {
    "invalid_request": (
        "The request is missing a required parameter, includes an unsupported parameter value, "
        "or is otherwise malformed."
    ),
    "invalid_client": (
        "Client authentication failed due to unknown client, no client authentication included, "
        "or unsupported authentication method."
    ),
    "invalid_grant": (
        "The provided authorization grant is invalid, expired, revoked, does not match the "
        "redirection URI used in the authorization request, or was issued to another client."
    ),
    "unauthorized_client": (
        "The client is not authorized to perform this request using this method."
    ),
    "unsupported_grant_type": (
        "The authorization grant type is not supported by the authorization server."
    ),
    "invalid_scope": "The requested scope is invalid, unknown, or malformed.",
}


def _error_response(error, headers):
    return headers, error.json, error.status_code


class UnsupportedGrant(GrantTypeBase):
    """Every grant type not offered; oauthlib hands those to the default grant."""

    def create_token_response(self, request, token_handler):
        return _error_response(
            errors.UnsupportedGrantTypeError(request=request), self._get_default_headers()
        )


class GoogleIdTokenGrant(GrantTypeBase):
    """The google_id_token grant: the client, grant type and scopes are checked before
    Google sign-in may create or link a user."""

    def create_token_response(self, request, token_handler):
        headers = self._get_default_headers()
        try:
            self._validate(request)
        except errors.OAuth2Error as error:
            headers.update(error.headers)
            return _error_response(error, headers)
        token = token_handler.create_token(request, refresh_token=True)
        self.request_validator.save_token(token, request)
        return headers, json.dumps(token), 200

    def _validate(self, request):
        validator = self.request_validator
        if validator.client_authentication_required(request):
            authenticated = validator.authenticate_client(request)
        else:
            authenticated = validator.authenticate_client_id(request.client_id, request)
        if not authenticated:
            raise errors.InvalidClientError(request=request)
        self.validate_grant_type(request)
        self.validate_scopes(request)
        # oauthlib's Request raises AttributeError for a parameter the body does not carry.
        user = google_sign_in(getattr(request, "id_token", None) or "").user
        if user is None:
            raise errors.InvalidGrantError(request=request)
        request.user = user


GRANTS = {
    "password": ResourceOwnerPasswordCredentialsGrant,
    "refresh_token": RefreshTokenGrant,
    "google_id_token": GoogleIdTokenGrant,
}


class Server(TokenEndpoint, RevocationEndpoint, ResourceEndpoint):
    def __init__(
        self,
        request_validator,
        token_expires_in=None,
        token_generator=None,
        refresh_token_generator=None,
        **kwargs,
    ):
        bearer = BearerToken(
            request_validator, token_generator, token_expires_in, refresh_token_generator
        )
        TokenEndpoint.__init__(
            self,
            default_grant_type="unsupported",
            grant_types={
                name: grant(request_validator)
                for name, grant in (GRANTS | {"unsupported": UnsupportedGrant}).items()
            },
            default_token_type=bearer,
        )
        RevocationEndpoint.__init__(self, request_validator)
        ResourceEndpoint.__init__(self, default_token="Bearer", token_types={"Bearer": bearer})


class Validator(OAuth2Validator):
    def validate_grant_type(self, client_id, grant_type, client, request, *args, **kwargs):
        return grant_type in GRANTS

    # No scopes are configured.
    def validate_scopes(self, client_id, scopes, client, request, *args, **kwargs):
        return not scopes

    # The row lock is held until the token is written (TokenView runs the grant in one
    # transaction), and the row is read under it, so the password is checked as it is after any
    # Google link that held the lock first (AC-06).
    def validate_user(self, username, password, client, request, *args, **kwargs):
        email = (username or "").strip().lower()
        user = User.objects.select_for_update().filter(email=email).first()
        if user is None or not user.check_password(password):
            return False
        request.user = user
        return True

    def validate_refresh_token(self, refresh_token, client, request, *args, **kwargs):
        checksum = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
        owner = RefreshToken.objects.filter(token_checksum=checksum).values("user_id")
        list(User.objects.select_for_update().filter(pk__in=owner))
        return super().validate_refresh_token(refresh_token, client, request, *args, **kwargs)


class MalformedBody(Exception):
    pass


def oauth_params(request):
    """The form or JSON body of an OAuth request, as a dict."""
    if request.content_type == "application/json":
        try:
            body = json.loads(request.body or b"{}")
        except ValueError as error:
            raise MalformedBody from error
        return body if isinstance(body, dict) else {}
    return request.POST.dict()


def _bad_request():
    """An unparseable JSON body answers 400 before any grant runs."""
    return JsonResponse(public_exception_body(400), status=400)


class Backend(OAuthLibCore):
    def extract_body(self, request):
        if request.content_type == "application/json":
            return list(oauth_params(request).items())
        return super().extract_body(request)


def _oauth_body(response):
    body = json.loads(response.content)
    if response.status_code == 200:
        return {
            "access_token": body["access_token"],
            "token_type": "Bearer",
            "expires_in": body["expires_in"],
            "refresh_token": body["refresh_token"],
            "created_at": int(timezone.now().timestamp()),
        }
    error = body.get("error")
    if error in OAUTH_ERROR_DESCRIPTIONS:
        return {"error": error, "error_description": OAUTH_ERROR_DESCRIPTIONS[error]}
    return body


class TokenView(dot_views.TokenView):
    def post(self, request, *args, **kwargs):
        try:
            grant_type = oauth_params(request).get("grant_type")
        except MalformedBody:
            return _bad_request()

        def attempt():
            return self._grant(request, grant_type, *args, **kwargs)

        if grant_type == "password":
            response = limit_failed_sign_ins(request, attempt, is_failure=_wrong_credentials)
        else:
            response = attempt()
        return response if response.status_code == 429 else _reshaped(response)

    def _grant(self, request, grant_type, *args, **kwargs):
        # The user's row is locked for the password and refresh grants until the token is written,
        # as Google linking does, so neither leaves a token the link did not see (AC-06).
        if grant_type in ("password", "refresh_token"):
            with transaction.atomic():
                return super().post(request, *args, **kwargs)
        return super().post(request, *args, **kwargs)


def _wrong_credentials(response):
    return (
        response.status_code == 400 and json.loads(response.content).get("error") == "invalid_grant"
    )


def _reshaped(response):
    reshaped = JsonResponse(_oauth_body(response), status=response.status_code)
    for name in ("Cache-Control", "Pragma", "WWW-Authenticate"):
        if name in response:
            reshaped[name] = response[name]
    return reshaped


@method_decorator(csrf_exempt, name="dispatch")
class RevokeView(View):
    """Revoke for public clients: the token's holder may revoke it, and the answer
    is 200 whether or not the token was known."""

    http_method_names = ["post"]

    def post(self, request):
        try:
            raw = str(oauth_params(request).get("token") or "")
        except MalformedBody:
            return _bad_request()
        checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        access = AccessToken.objects.filter(token_checksum=checksum).first()
        if access is not None:
            revoke_access_token(access)
        else:
            refresh = RefreshToken.objects.filter(
                token_checksum=checksum, revoked__isnull=True
            ).first()
            if refresh is not None:
                refresh.revoke()
        return JsonResponse({})
