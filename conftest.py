import pytest
from django.core.cache import cache

from apps.common import rate_limit


@pytest.fixture(autouse=True)
def _clear_rate_limit_counters():
    """The rate-limit counters outlive a test; leftovers would refuse requests in another."""
    cache.clear()
    rate_limit.FALLBACK.clear()
    yield
    cache.clear()
    rate_limit.FALLBACK.clear()
