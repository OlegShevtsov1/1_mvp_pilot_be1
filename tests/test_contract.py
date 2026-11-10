import jsonschema
import pytest
from django.http import HttpResponse, JsonResponse

from tests.contract import assert_matches_contract

ME = {
    "status": "success",
    "message": "User profile",
    "data": {"user_id": 1, "email": "a@example.com"},
}


def test_accepts_a_documented_response():
    assert_matches_contract(JsonResponse(ME), "get", "/api/v1/me")


@pytest.mark.parametrize(
    "body",
    [
        {"status": "success", "message": "User profile"},
        {**ME, "extra": 1},
        {**ME, "data": {"user_id": 1, "email": "not-an-email"}},
    ],
    ids=["missing-key", "extra-key", "bad-email"],
)
def test_rejects_a_body_off_the_schema(body):
    with pytest.raises(jsonschema.ValidationError):
        assert_matches_contract(JsonResponse(body), "get", "/api/v1/me")


def test_rejects_an_undocumented_status():
    with pytest.raises(AssertionError, match="got 500"):
        assert_matches_contract(JsonResponse({"error": "x"}, status=500), "get", "/api/v1/me")


def test_checks_only_the_status_of_a_response_without_content():
    assert_matches_contract(HttpResponse(status=204), "delete", "/api/v1/projects/{id}")


def test_health_is_not_in_the_contract():
    with pytest.raises(AssertionError, match="not an operation"):
        assert_matches_contract(JsonResponse({"status": "ok"}), "get", "/health")
