"""The failed sign-in limit of both sign-in doors (AC-10, ADR-0009); the sign-up limit (AC-04b)."""

from django.utils import timezone

from apps.common.exceptions import TooManyRequests, error_response
from apps.common.rate_limit import client_ip, increment, source_of
from apps.users.legacy import smoke_token_presented


class FailedSignInLimit:
    """Failed password sign-ins counted per source; the source is refused before its password is
    checked once it reached LIMIT failures in the window. Each attempt is counted before its check,
    so attempts in flight together cannot all pass, and given back unless it failed."""

    LIMIT = 10
    WINDOW = 60
    MESSAGE = "Too many failed sign-ins from this address. Wait a minute before trying again"

    # Windows are clock minutes and each has its own key, so the key names the window an attempt
    # was counted in: both stores agree on it, and a give-back reaches only that window.
    def __init__(self, request):
        window = int(timezone.now().timestamp()) // self.WINDOW
        self.key = f"failed-sign-in:{source_of(request)}:{window}"

    def attempt_refused(self):
        return increment(self.key, 1, self.WINDOW) > self.LIMIT

    # A window whose count was lost (a cleared or failed store) is not left below zero.
    def give_back(self):
        if increment(self.key, -1, self.WINDOW) < 0:
            increment(self.key, 1, self.WINDOW)


def limit_failed_sign_ins(request, attempt, is_failure):
    """Run the sign-in `attempt` under the limit; neither a success nor a server error counts."""
    limit = FailedSignInLimit(request)
    if limit.attempt_refused():
        return error_response(
            TooManyRequests([FailedSignInLimit.MESSAGE], FailedSignInLimit.WINDOW)
        )
    failed = False
    try:
        response = attempt()
        failed = is_failure(response)
        return response
    finally:
        if not failed:
            limit.give_back()


SIGN_UP_LIMIT = 5
SIGN_UP_WINDOW = 3600


def check_sign_up_limit(request):
    """Counted per source before anything is checked, so refused sign-ups count too (PRD §6:
    limits email probing). The deploy smoke presents SMOKE_TOKEN to stay out of it."""
    if smoke_token_presented(request):
        return
    key = f"rate-limit:api/v1/users:{client_ip(request)}"
    if increment(key, 1, SIGN_UP_WINDOW) > SIGN_UP_LIMIT:
        raise TooManyRequests(
            ["Too many sign-ups from this address. Wait an hour before trying again"],
            SIGN_UP_WINDOW,
            message="User could not be created",
        )
