"""Sign-up and legacy sign-in."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from django.db import transaction

from apps.common.exceptions import ParameterMissing
from apps.users.models import User
from apps.users.tokens import IssuedTokens, issue_tokens

# Email format: one @, no whitespace, something on both sides.
_EMAIL = re.compile(r"\A[^@\s]+@[^@\s]+\Z")


def _scalar(value):
    """A JSON value read as a scalar param: arrays and objects are dropped, and numbers and
    booleans become their text (`"true"` / `"false"`)."""
    match value:
        case None | str():
            return value
        case bool():
            return str(value).lower()
        case int() | float():
            return str(value)
    return None


def _blank(value):
    return value is None or not str(value).strip()


def sign_up_errors(email, password, password_confirmation):
    """Sign-up validation messages, in order."""
    errors = []
    if _blank(email):
        errors.append("Email can't be blank")
    else:
        if User.objects.filter(email=str(email).strip().lower()).exists():
            errors.append(
                "Email already belongs to an account. Sign in instead, with Google sign-in or "
                "your password"
            )
        if not _EMAIL.match(str(email).strip()):
            errors.append("Email is invalid")
    if _blank(password):
        errors.append("Password can't be blank")
    if password_confirmation is not None and password_confirmation != password:
        errors.append("Password confirmation doesn't match Password")
    if not _blank(password):
        if len(password) < 6:
            errors.append("Password is too short (minimum is 6 characters)")
        elif len(password) > 128:
            errors.append("Password is too long (maximum is 128 characters)")
    return errors


@dataclass
class SignUp:
    user: User | None = None
    errors: list[str] = field(default_factory=list)
    tokens: IssuedTokens | None = None


def sign_up(data):
    params = data.get("user") if isinstance(data, Mapping) else None
    if not isinstance(params, Mapping) or not params:
        raise ParameterMissing()
    email = _scalar(params.get("email"))
    password = _scalar(params.get("password"))
    errors = sign_up_errors(email, password, _scalar(params.get("password_confirmation")))
    if errors:
        return SignUp(errors=errors)
    with transaction.atomic():
        user = User.objects.create_user(email, password)
        return SignUp(user=user, tokens=issue_tokens(user))


@dataclass
class SignIn:
    user: User | None = None
    errors: list[str] = field(default_factory=list)


def sign_in(data):
    params = data if isinstance(data, Mapping) else {}
    email = _scalar(params.get("email"))
    password = _scalar(params.get("password"))
    user = User.objects.filter(email=email).first()
    if user is None or not user.check_password(password):
        return SignIn(user=user, errors=["Invalid email or password"])
    return SignIn(user=user)
