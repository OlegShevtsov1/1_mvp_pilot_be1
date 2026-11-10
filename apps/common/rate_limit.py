"""The fixed-window request counter and the client address a request is counted under."""

import ipaddress
import logging
import re

from django.conf import settings
from django.core.cache import cache
from django.core.cache.backends.locmem import LocMemCache

logger = logging.getLogger(__name__)

# Counts in this process too, so a failing or cleared cache never lifts a limit.
FALLBACK = LocMemCache("rate-limit-fallback", {})


def _count(store, key, amount, timeout):
    store.add(key, 0, timeout)
    return store.incr(key, amount)


def increment(key, amount, timeout):
    """Add `amount` to `key` in the Django cache and the fallback; the higher count wins."""
    counts = [_count(FALLBACK, key, amount, timeout)]
    try:
        counts.append(_count(cache, key, amount, timeout))
    except Exception:
        logger.warning("Rate-limit cache failed; counting in this process only", exc_info=True)
    return max(counts)


def _trusted(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in ipaddress.ip_network(net) for net in settings.TRUSTED_PROXIES)


def _valid(address):
    try:
        ipaddress.ip_address(address)
    except ValueError:
        return False
    return True


def client_ip(request):
    """The client IP rule: walking X-Forwarded-For from the right, the first entry that is not a
    trusted proxy, then REMOTE_ADDR; when all are trusted, the left-most entry. No Client-IP
    header check."""
    remote_addr = request.META.get("REMOTE_ADDR", "")
    forwarded = re.split(r"[,\s]+", request.META.get("HTTP_X_FORWARDED_FOR", "").strip())
    forwarded = [address for address in reversed(forwarded) if _valid(address)]
    untrusted = [address for address in [*forwarded, remote_addr] if not _trusted(address)]
    if untrusted:
        return untrusted[0]
    return forwarded[-1] if forwarded else remote_addr


def source_of(request):
    """The forwarded client address only when a trusted proxy forwarded it, else REMOTE_ADDR."""
    remote_addr = request.META.get("REMOTE_ADDR", "")
    return client_ip(request) if _trusted(remote_addr) else remote_addr
