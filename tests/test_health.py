"""GET /health.

/health is not an operation of contract/openapi.json, so it is checked by exact body equality.
"""


def test_health_reports_the_release(client, monkeypatch):
    monkeypatch.setenv("APP_RELEASE", "0123abcd")

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "release": "0123abcd"}


def test_health_release_defaults_to_unknown(client, monkeypatch):
    monkeypatch.delenv("APP_RELEASE", raising=False)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "release": "unknown"}
