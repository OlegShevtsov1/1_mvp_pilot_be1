import pytest

APP_ORIGIN = "https://app.dev.example.test"


@pytest.fixture(autouse=True)
def allowed_origins(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", f"https://other.example.test, {APP_ORIGIN}")


def preflight(client, origin, path="/api/errors", method="POST", headers="content-type"):
    return client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


def test_allows_a_preflight_from_a_configured_origin(client):
    response = preflight(client, APP_ORIGIN)

    assert response.headers["Access-Control-Allow-Origin"] == APP_ORIGIN
    assert "POST" in response.headers["Access-Control-Allow-Methods"]


def test_answers_a_simple_request_from_a_configured_origin_with_the_cors_header(client):
    response = client.get("/health", headers={"Origin": APP_ORIGIN})

    assert response.headers["Access-Control-Allow-Origin"] == APP_ORIGIN


def test_allows_a_preflight_that_sends_the_authorization_header_from_a_configured_origin(client):
    response = preflight(
        client,
        APP_ORIGIN,
        path="/api/v1/projects",
        method="GET",
        headers="authorization, content-type",
    )

    assert response.headers["Access-Control-Allow-Origin"] == APP_ORIGIN
    assert "authorization" in response.headers["Access-Control-Allow-Headers"].lower()


def test_exposes_retry_after_to_the_browser_on_answers_to_a_configured_origin(client):
    response = client.get("/health", headers={"Origin": APP_ORIGIN})

    assert "Retry-After" in response.headers["Access-Control-Expose-Headers"]


def test_gives_an_unknown_origin_no_cors_headers(client):
    assert (
        "Access-Control-Allow-Origin" not in preflight(client, "https://evil.example.com").headers
    )

    response = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert "Access-Control-Allow-Origin" not in response.headers


def test_allows_no_origin_while_cors_allowed_origins_is_empty(client, monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "")

    assert "Access-Control-Allow-Origin" not in preflight(client, APP_ORIGIN).headers
