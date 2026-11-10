import hmac
import os


def smoke_token_presented(request):
    """The pipeline-only secret deploy checks present in X-Smoke-Token; a blank SMOKE_TOKEN never
    matches."""
    expected = os.environ.get("SMOKE_TOKEN", "")
    given = request.headers.get("X-Smoke-Token", "")
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())
