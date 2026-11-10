import json

import pytest
from django.test import RequestFactory

from apps.common.views import not_found, server_error

NOT_AUTHORIZED = {"error": "You are not authorized to perform this action"}


@pytest.mark.urls("apps.common.tests.urls")
@pytest.mark.parametrize(
    ("name", "status", "body", "retry_after"),
    [
        ("forbidden", 403, NOT_AUTHORIZED, None),
        ("forbidden-message", 403, {"error": "Not yours"}, None),
        ("resource-not-found", 404, {"error": "Project not found"}, None),
        ("resource-not-found-default", 404, {"error": "Resource not found"}, None),
        ("validation-failed", 422, {"errors": ["Name can't be blank"]}, None),
        (
            "validation-failed-message",
            422,
            {"status": "error", "message": "Could not save", "errors": ["Bad"]},
            None,
        ),
        ("too-many-requests", 429, {"errors": ["Slow down"]}, "60"),
        (
            "too-many-requests-message",
            429,
            {"status": "error", "message": "No", "errors": ["Slow down"]},
            "3600",
        ),
        ("parameter-missing", 422, {"status": 422, "error": "Unprocessable Content"}, None),
        ("not-authenticated", 401, {"error": "Not Authorized"}, None),
        ("authentication-failed", 401, {"error": "Not Authorized"}, None),
        ("permission-denied", 403, NOT_AUTHORIZED, None),
        ("django-permission-denied", 403, NOT_AUTHORIZED, None),
        ("http404", 404, {"error": "Not Found"}, None),
        ("not-found", 404, {"error": "Not Found"}, None),
        ("parse-error", 400, {"status": 400, "error": "Bad Request"}, None),
    ],
)
def test_renders_be_error_bodies(client, name, status, body, retry_after):
    response = client.get(f"/raise/{name}")

    assert response.status_code == status
    assert json.loads(response.content) == body
    assert response.headers.get("Retry-After") == retry_after
    assert "WWW-Authenticate" not in response.headers


@pytest.mark.urls("apps.common.tests.urls")
def test_another_method_on_a_known_path_is_an_unknown_route(client):
    response = client.post("/get-only")

    assert response.status_code == 404
    assert response.json() == {"status": 404, "error": "Not Found"}


@pytest.mark.urls("apps.common.tests.urls")
def test_an_unhandled_error_raises_to_django(client):
    with pytest.raises(RuntimeError, match="boom"):
        client.get("/raise/unhandled")


@pytest.mark.urls("apps.common.tests.urls")
def test_an_unhandled_error_answers_be_json_500(client):
    client.raise_request_exception = False

    response = client.get("/raise/unhandled")

    assert response.status_code == 500
    assert response.json() == {"status": 500, "error": "Internal Server Error"}


def test_server_error_view():
    response = server_error(RequestFactory().get("/"))

    assert response.status_code == 500
    assert json.loads(response.content) == {"status": 500, "error": "Internal Server Error"}


def test_not_found_view():
    response = not_found(RequestFactory().get("/"), Exception())

    assert response.status_code == 404
    assert json.loads(response.content) == {"status": 404, "error": "Not Found"}


def test_an_unknown_url_answers_be_json_404(client):
    response = client.get("/no/such/route")

    assert response.status_code == 404
    assert response.json() == {"status": 404, "error": "Not Found"}
