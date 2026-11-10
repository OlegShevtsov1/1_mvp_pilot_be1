"""Deliberate failures that prove a deployment's errors reach GlitchTip, each tagged with a
marker the operator can search for."""

import re
import secrets


class GlitchtipSmokeError(Exception):
    pass


KINDS_IN_REQUEST = ("unhandled", "manual", "db")
# 63 bytes is Postgres' identifier limit; the db kind uses the marker as a column name.
MARKER_FORMAT = re.compile(r"[\w-]{1,63}", re.ASCII)


def marker(given):
    if given and MARKER_FORMAT.fullmatch(given):
        return given
    return f"glitchtip-smoke-{secrets.token_hex(6)}"


def message(kind, marker):
    return f"glitchtip smoke {kind} {marker}"
