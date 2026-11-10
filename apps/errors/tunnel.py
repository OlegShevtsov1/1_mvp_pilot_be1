"""Relays a browser SDK envelope to GlitchTip so ad blockers and the CSP only ever see this API.

An envelope is accepted when its DSN has the allowed DSN's public key and project id; its host,
scheme, port, path and secret are ignored, so the frontend can publish the DSN with its public
host instead of the internal one. The upstream URL is derived from the one allowed DSN, never
from the request, so the tunnel cannot be pointed at any other host. The forward authenticates
with the allowed DSN's public key: GlitchTip, unlike Sentry Relay, does not read the DSN from the
envelope header.
"""

import json
import re
from urllib.parse import urlsplit

import urllib3
from sentry_sdk.consts import VERSION, EndpointType
from sentry_sdk.utils import Dsn

MAX_BYTES = 256 * 1024

# The DSN grammar accepted: an RFC 3986 URI with only the authority branch of hier-part, since the
# caller has required http:// or https://, plus a check for a malformed escape in the query. The
# query is lenient and the fragment strict.
# The classes are ASCII on purpose: Python's \d also matches non-ASCII digits.
_H = "[0-9A-Fa-f]"
_DEC_OCTET = r"(?:[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5]|[0-9])"
_IPV4 = rf"{_DEC_OCTET}\.{_DEC_OCTET}\.{_DEC_OCTET}\.{_DEC_OCTET}"
_LS32 = rf"(?:{_H}{{1,4}}:{_H}{{1,4}}|{_IPV4})"
_IPV6 = (
    rf"(?:(?:{_H}{{1,4}}:){{6}}{_LS32}"
    rf"|::(?:{_H}{{1,4}}:){{5}}{_LS32}"
    rf"|{_H}{{1,4}}?::(?:{_H}{{1,4}}:){{4}}{_LS32}"
    rf"|(?:(?:{_H}{{1,4}}:)?{_H}{{1,4}})?::(?:{_H}{{1,4}}:){{3}}{_LS32}"
    rf"|(?:(?:{_H}{{1,4}}:){{0,2}}{_H}{{1,4}})?::(?:{_H}{{1,4}}:){{2}}{_LS32}"
    rf"|(?:(?:{_H}{{1,4}}:){{0,3}}{_H}{{1,4}})?::{_H}{{1,4}}:{_LS32}"
    rf"|(?:(?:{_H}{{1,4}}:){{0,4}}{_H}{{1,4}})?::{_LS32}"
    rf"|(?:(?:{_H}{{1,4}}:){{0,5}}{_H}{{1,4}})?::{_H}{{1,4}}"
    rf"|(?:(?:{_H}{{1,4}}:){{0,6}}{_H}{{1,4}})?::)"
)
_PCT = rf"%{_H}{_H}"
_HOST = (
    rf"(?:\[(?:{_IPV6}|v{_H}++\.[!$&-.0-9:;=A-Z_a-z~]++)\]"
    rf"|{_IPV4}"
    rf"|(?:{_PCT}|[!$&-.0-9;=A-Z_a-z~])*+)"
)
_USERINFO = rf"(?:{_PCT}|[!$&-.0-9:;=A-Z_a-z~])*+"
_SEGMENT = rf"(?:{_PCT}|[!$&-.0-9:;=@A-Z_a-z~/])"
_FRAGMENT = rf"(?:{_PCT}|[!$&-.0-9:;=@A-Z_a-z~/?])*+"
RFC3986_URI = re.compile(
    rf"[A-Za-z][+\-.0-9A-Za-z]*+://"
    rf"(?:{_USERINFO}@)?{_HOST}(?::[0-9]*+)?"
    rf"(?:/{_SEGMENT}*+)?"
    rf"(?:\?(?P<query>[^#]*+))?"
    rf"(?:\#{_FRAGMENT})?"
)
INVALID_ESCAPE = re.compile(r"%[^0-9A-Fa-f]{2}")

http = urllib3.PoolManager(retries=False, timeout=urllib3.Timeout(connect=2, read=5))


class Rejected(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def forward(body, allowed_dsn):
    """Returns (upstream status, upstream body)."""
    auth = Dsn(allowed_dsn).to_auth(client=f"sentry.python/{VERSION}")
    if _key_and_project(envelope_dsn(body)) != _key_and_project(allowed_dsn):
        raise Rejected(403, "dsn not allowed")

    try:
        response = http.request(
            "POST",
            auth.get_api_url(EndpointType.ENVELOPE),
            body=body,
            headers={
                "Content-Type": "application/x-sentry-envelope",
                "X-Sentry-Auth": auth.to_header(),
            },
        )
    except (urllib3.exceptions.HTTPError, OSError) as error:
        raise Rejected(502, "upstream unreachable") from error
    return response.status, response.data


def envelope_dsn(body):
    try:
        header = json.loads(body.split(b"\n", 1)[0])
    except (ValueError, RecursionError) as error:
        raise Rejected(400, "malformed envelope") from error
    dsn = header.get("dsn") if isinstance(header, dict) else None
    if not (isinstance(dsn, str) and dsn.startswith(("http://", "https://"))):
        raise Rejected(400, "envelope header has no http(s) dsn")
    if not _parses_as_uri(dsn):
        raise Rejected(400, "malformed envelope")
    return dsn


def _parses_as_uri(dsn):
    match = RFC3986_URI.fullmatch(dsn) if dsn.isascii() else None
    return bool(match) and not INVALID_ESCAPE.search(re.sub(r"[\t\r\n]", "", match["query"] or ""))


def _key_and_project(dsn):
    """The DSN's public key and project id (its last path segment).
    Not through sentry_sdk's Dsn, which raises on a DSN without a key: such an envelope is
    refused with 403, not malformed."""
    try:
        parts = urlsplit(dsn)
    except ValueError as error:
        raise Rejected(400, "malformed envelope") from error
    segments = [segment for segment in parts.path.split("/") if segment]
    return parts.username, segments[-1] if segments else None
