import json
import re

import pytest

from tests.contract import CONTRACT

TOKEN_KEYS = {"authentication_token", "access_token", "refresh_token"}


@pytest.fixture(autouse=True)
def hosts(settings):
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "api.example.com", "app", "localhost"]


def served(client, host="localhost", **headers):
    response = client.get("/api-docs/v1/swagger.json", headers={"Host": host, **headers})
    assert response.status_code == 200
    return response.json()


def test_lists_the_proxied_request_origin_as_the_only_server(client, monkeypatch):
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "prod")

    document = served(client, "api.example.com", **{"X-Forwarded-Proto": "https"})

    assert document["servers"] == [{"url": "https://api.example.com", "description": "prod"}]


def test_follows_x_forwarded_host_when_the_proxy_reaches_the_app_under_an_internal_name(
    client, monkeypatch
):
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "dev")

    document = served(
        client,
        "app:3000",
        **{"X-Forwarded-Host": "api.example.com", "X-Forwarded-Proto": "https"},
    )

    assert document["servers"] == [{"url": "https://api.example.com", "description": "dev"}]


def test_lists_localhost_3000_for_a_local_development_request(client, monkeypatch):
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)

    document = served(client, "localhost:3000")

    assert document["servers"] == [{"url": "http://localhost:3000", "description": "test"}]


def test_still_serves_the_documented_paths(client):
    assert "/api/v1/projects" in served(client)["paths"]


def test_serves_the_contract_unchanged_but_for_its_servers(client):
    contract = json.loads(CONTRACT.read_text())
    document = served(client)

    assert {**document, "servers": None} == {**contract, "servers": None}


def test_documents_the_auth_operations(client):
    document = served(client)

    assert {"type": "http", "scheme": "bearer"} in document["components"][
        "securitySchemes"
    ].values()
    assert document["paths"]["/api/v1/sign_in"]["post"]["deprecated"] is True


def test_carries_placeholder_tokens_never_live_ones_in_its_examples(client):
    values = list(token_values(served(client)))

    assert values
    assert all(re.fullmatch(r"<[a-z-]+>", value) for value in values)


def token_values(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in TOKEN_KEYS and isinstance(value, str):
                yield value
            else:
                yield from token_values(value)
    elif isinstance(node, list):
        for value in node:
            yield from token_values(value)


def test_serves_the_swagger_ui(client):
    assert client.get("/api-docs").status_code == 200
