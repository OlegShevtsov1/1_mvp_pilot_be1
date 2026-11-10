import pytest
import urllib3
from django.core.cache import caches

from apps.common import rate_limit
from apps.errors import tunnel


class FakeUpstream:
    """Stands in for the tunnel's HTTP pool: records every request and answers as configured."""

    def __init__(self):
        self.calls = []
        self.responder = None

    def respond(self, status=200, body=b""):
        self.responder = lambda call: (status, body)

    def request(self, method, url, body=None, headers=None):
        call = {"method": method, "url": url, "body": body, "headers": headers or {}}
        self.calls.append(call)
        assert self.responder is not None, f"unexpected upstream request: {method} {url}"
        result = self.responder(call)
        if isinstance(result, Exception):
            raise result
        status, data = result
        return urllib3.HTTPResponse(body=data, status=status, preload_content=True)


@pytest.fixture(autouse=True)
def upstream(monkeypatch):
    fake = FakeUpstream()
    monkeypatch.setattr(tunnel, "http", fake)
    caches["default"].clear()
    rate_limit.FALLBACK.clear()
    return fake
