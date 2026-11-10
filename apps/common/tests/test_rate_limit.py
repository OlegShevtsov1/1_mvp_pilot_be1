import pytest
from django.core.cache import cache
from django.test import RequestFactory, override_settings

from apps.common import rate_limit
from apps.common.rate_limit import client_ip, increment, source_of


def request(remote_addr, forwarded=None):
    headers = {"HTTP_X_FORWARDED_FOR": forwarded} if forwarded is not None else {}
    return RequestFactory().get("/", REMOTE_ADDR=remote_addr, **headers)


def test_increment_counts_in_both_stores():
    assert increment("k", 1, 60) == 1
    assert increment("k", 1, 60) == 2
    assert increment("k", -1, 60) == 1
    assert cache.get("k") == 1
    assert rate_limit.FALLBACK.get("k") == 1


def test_increment_goes_below_zero_as_be_does():
    assert increment("k", -1, 60) == -1


def test_increment_keeps_counting_when_the_django_cache_fails(monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise ConnectionError("cache down")

    monkeypatch.setattr(cache, "incr", broken)

    assert increment("k", 1, 60) == 1
    assert increment("k", 1, 60) == 2
    assert "Rate-limit cache failed" in caplog.text


def test_increment_takes_the_higher_count_when_one_store_was_cleared():
    for _ in range(3):
        increment("k", 1, 60)
    rate_limit.FALLBACK.clear()
    assert increment("k", 1, 60) == 4

    cache.clear()
    assert increment("k", 1, 60) == 2  # the fallback had restarted at 1


def test_a_direct_caller_is_its_own_address():
    assert client_ip(request("203.0.113.7")) == "203.0.113.7"
    assert source_of(request("203.0.113.7")) == "203.0.113.7"


def test_a_trusted_proxy_forwards_the_client_address():
    proxied = request("127.0.0.1", "203.0.113.100, 203.0.113.10")

    assert client_ip(proxied) == "203.0.113.10"
    assert source_of(proxied) == "203.0.113.10"


def test_forwarded_addresses_from_trusted_proxies_are_skipped():
    assert client_ip(request("127.0.0.1", "203.0.113.5, 10.0.0.2")) == "203.0.113.5"


def test_only_trusted_proxies_leave_the_first_forwarded_address():
    assert client_ip(request("127.0.0.1", "10.0.0.1, 10.0.0.2")) == "10.0.0.1"


def test_invalid_forwarded_entries_are_ignored():
    assert client_ip(request("127.0.0.1", "not-an-ip, 203.0.113.9")) == "203.0.113.9"


def test_an_untrusted_caller_does_not_set_its_source_with_the_forwarded_header():
    spoofed = request("198.51.100.7", "203.0.113.50")

    assert source_of(spoofed) == "198.51.100.7"
    # The client IP rule still takes the forwarded address (the sign-up limit keys on it).
    assert client_ip(spoofed) == "203.0.113.50"


@pytest.mark.parametrize("remote_addr", ["192.168.1.1", "10.1.2.3", "172.16.0.1", "::1"])
def test_private_and_loopback_callers_are_trusted_proxies(remote_addr):
    assert source_of(request(remote_addr, "203.0.113.10")) == "203.0.113.10"


@override_settings(TRUSTED_PROXIES=["127.0.0.1/32"])
def test_trusted_proxies_come_from_settings():
    assert source_of(request("127.0.0.1", "203.0.113.10")) == "203.0.113.10"
    assert source_of(request("10.0.0.1", "203.0.113.10")) == "10.0.0.1"
