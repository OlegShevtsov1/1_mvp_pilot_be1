"""The user journey bin/local-smoke drives against a running server, over real HTTP.

Every answer of a contract operation is checked with tests.contract.assert_matches_contract;
/health, /api-docs and the CORS preflight, which the contract leaves out, are checked by status
and body. Prints `ok <method> <path> <status>` per step and
`smoke: N/N ok`; the first mismatch prints `FAIL …` and exits 1.

Usage: python -m tests.local_smoke <release>
"""

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from tests.contract import assert_matches_contract

BASE = "http://127.0.0.1:8095"
PASSWORD = "password123"


@dataclass
class Reply:
    """What assert_matches_contract reads of a response: status_code and content."""

    status_code: int
    content: bytes
    headers: dict = field(default_factory=dict)

    def json(self):
        return json.loads(self.content)


class Smoke:
    def __init__(self):
        self.passed = 0

    def call(self, method, path, expected, *, contract=None, body=None, headers=None):
        """Send one request; check its status and, given `contract` (the operation's path
        template), the answer against the contract."""
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(BASE + path, data=data, method=method)
        if body is not None:
            request.add_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                reply = Reply(response.status, response.read(), dict(response.headers))
        except urllib.error.HTTPError as error:
            reply = Reply(error.code, error.read(), dict(error.headers))

        try:
            assert reply.status_code == expected, f"expected {expected}, got {reply.status_code}"
            if contract is not None:
                assert_matches_contract(reply, method, contract)
        except Exception as error:
            print(f"FAIL {method} {path} {reply.status_code}: {error}", file=sys.stderr)
            print(reply.content[:2000].decode(errors="replace"), file=sys.stderr)
            print(f"smoke: {self.passed} ok before the failure", file=sys.stderr)
            sys.exit(1)
        self.passed += 1
        print(f"ok {method} {path} {reply.status_code}", flush=True)
        return reply

    def check(self, condition, message):
        if not condition:
            print(f"FAIL {message}", file=sys.stderr)
            sys.exit(1)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def main(release):
    s = Smoke()
    client_id = os.environ["OAUTH_CLIENT_ID"]
    origin = os.environ["CORS_ALLOWED_ORIGINS"].split(",")[0]

    health = s.call("GET", "/health", 200)
    s.check(health.json() == {"status": "ok", "release": release}, f"/health {health.content}")

    def sign_up(email):
        user = {"email": email, "password": PASSWORD, "password_confirmation": PASSWORD}
        return s.call(
            "POST", "/api/v1/users", 201, contract="/api/v1/users", body={"user": user}
        ).json()["data"]

    alice = sign_up("alice@example.com")
    bob = sign_up("bob@example.com")
    s.check("access_token" in alice, "sign-up issued no token pair: is the web client set up?")

    signed_in = s.call(
        "POST",
        "/api/v1/sign_in",
        200,
        contract="/api/v1/sign_in",
        body={"email": "alice@example.com", "password": PASSWORD},
    ).json()["data"]
    legacy = {
        "X-User-Email": "alice@example.com",
        "X-User-Token": signed_in["authentication_token"],
    }

    password_grant = {
        "grant_type": "password",
        "client_id": client_id,
        "username": "alice@example.com",
        "password": PASSWORD,
    }
    pair = s.call("POST", "/oauth/token", 200, contract="/oauth/token", body=password_grant).json()
    refresh_grant = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": pair["refresh_token"],
    }
    pair = s.call("POST", "/oauth/token", 200, contract="/oauth/token", body=refresh_grant).json()
    token = pair["access_token"]

    s.call("GET", "/api/v1/me", 200, contract="/api/v1/me", headers=bearer(token))
    s.call("GET", "/api/v1/me", 200, contract="/api/v1/me", headers=legacy)

    projects = "/api/v1/projects"
    project = {"name": "Smoke project", "description": "Created by bin/local-smoke"}
    created = s.call(
        "POST", projects, 201, contract=projects, body={"project": project}, headers=bearer(token)
    ).json()["data"]
    one = f"{projects}/{created['id']}"
    one_t = "/api/v1/projects/{id}"
    s.call("GET", projects, 200, contract=projects, headers=bearer(token))
    s.call("GET", one, 200, contract=one_t, headers=bearer(token))
    s.call(
        "PUT",
        one,
        200,
        contract=one_t,
        body={"project": {"name": "Smoke renamed"}},
        headers=bearer(token),
    )

    tasks = f"{one}/tasks"
    tasks_t = "/api/v1/projects/{project_id}/tasks"
    task = {"name": "Smoke task", "description": "Created by bin/local-smoke"}
    created_task = s.call(
        "POST", tasks, 201, contract=tasks_t, body={"task": task}, headers=bearer(token)
    ).json()["data"]
    task_one = f"{tasks}/{created_task['id']}"
    task_t = "/api/v1/projects/{project_id}/tasks/{id}"
    s.call("GET", tasks, 200, contract=tasks_t, headers=bearer(token))
    s.call("GET", task_one, 200, contract=task_t, headers=bearer(token))
    s.call(
        "PUT",
        task_one,
        200,
        contract=task_t,
        body={"task": {"status": "completed"}},
        headers=bearer(token),
    )
    s.call("DELETE", task_one, 204, contract=task_t, headers=bearer(token))

    s.call("GET", one, 404, contract=one_t, headers=bearer(bob["access_token"]))
    s.call("GET", projects, 401, contract=projects)
    s.call(
        "POST",
        projects,
        422,
        contract=projects,
        body={"project": {"name": "abc"}},
        headers=bearer(token),
    )
    s.call("DELETE", one, 204, contract=one_t, headers=bearer(token))

    s.call(
        "POST",
        "/oauth/revoke",
        200,
        contract="/oauth/revoke",
        body={"client_id": client_id, "token": token},
    )
    s.call("GET", "/api/v1/me", 401, contract="/api/v1/me", headers=bearer(token))
    s.call(
        "POST",
        "/api/v1/sign_out",
        204,
        contract="/api/v1/sign_out",
        headers=bearer(alice["access_token"]),
    )

    s.call("GET", "/api-docs", 200)
    preflight = s.call(
        "OPTIONS",
        projects,
        200,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    allowed = {k.lower(): v for k, v in preflight.headers.items()}
    s.check(
        allowed.get("access-control-allow-origin") == origin,
        f"preflight from {origin} not allowed: {preflight.headers}",
    )

    print(f"smoke: {s.passed}/{s.passed} ok")


if __name__ == "__main__":
    main(sys.argv[1])
