"""Checks responses against the API's OpenAPI contract, contract/openapi.json."""

import json
from functools import cache
from pathlib import Path

import jsonschema

CONTRACT = Path(__file__).resolve().parents[1] / "contract" / "openapi.json"


@cache
def _contract():
    return json.loads(CONTRACT.read_text())


def assert_matches_contract(response, method, path):
    """Assert `response` is a documented response of `method path` and matches its JSON schema.

    `path` is the contract's path template, e.g. "/api/v1/projects/{id}". A documented
    response without JSON content is checked by status code only.
    """
    operation = _contract()["paths"].get(path, {}).get(method.lower())
    assert operation is not None, f"{method.upper()} {path} is not an operation of {CONTRACT.name}"

    status = str(response.status_code)
    documented = operation["responses"]
    assert status in documented, (
        f"{method.upper()} {path} documents {sorted(documented)} responses, got {status}"
    )

    schema = documented[status].get("content", {}).get("application/json", {}).get("schema")
    if schema is not None:
        # OpenAPI 3.0 schema objects are a Draft 4 subset; this contract uses no $ref or nullable.
        validator = jsonschema.Draft4Validator(
            schema, format_checker=jsonschema.Draft4Validator.FORMAT_CHECKER
        )
        validator.validate(json.loads(response.content))
