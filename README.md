# Projects and Tasks API

A Django + Django REST framework JSON API for users, projects and tasks: email/password sign-up and
sign-in, OAuth2 access and refresh tokens (password, refresh-token and Google ID-token grants), a
legacy header token pair, a Sentry tunnel that relays frontend errors to GlitchTip, and OpenAPI
docs. `contract/openapi.json` is the API's OpenAPI document, and the tests check every response of
a contract operation against it.

## Prerequisites

[uv](https://docs.astral.sh/uv/). It installs Python 3.12 and the locked dependencies.

## Install and test

```bash
uv sync
uv run pytest -n auto
uv run ruff check .
uv run ruff format --check .
```

Tests run on in-memory SQLite. CI (`.github/workflows/ci.yml`) runs the same commands, checks for
missing migrations, runs the live smoke (`local-smoke` job, see below), and checks the PR title
(`BE1-<n>[-<m>]: …`) and the single `Type:` line of the PR body.

## Development server

```bash
uv run python manage.py migrate
uv run python manage.py runserver 127.0.0.1:8095
```

## Run and verify locally

```bash
bin/local-up [--ref <sha>]   # run origin/main, or <sha>, on http://127.0.0.1:8095
bin/local-check              # exit 0 when /health answers 200
bin/local-down               # stop the server
```

`bin/local-up` clones origin into `~/.local/state/projects-tasks-api/app`, checks out the ref, runs
`migrate`, and restarts gunicorn in the background. The same directory holds the pid file
`gunicorn.pid`, the logs `gunicorn.log` and `access.log`, and the database `db.sqlite3`, which
survives ref switches. All three scripts can be re-run safely.

To roll back, run `bin/local-up --ref <previous main sha>`. Migrations are not reversed by a ref
switch: rolling back past a migration needs `manage.py migrate <app> <previous migration>` first,
or a fresh `db.sqlite3`.

To verify a commit end to end:

```bash
bin/local-smoke [--ref <sha>]   # smoke origin/main, or <sha>, on a fresh server
uv run pytest -m smoke          # the same, from pytest (LOCAL_SMOKE_REF picks the commit)
```

`bin/local-smoke` starts origin/main (or `<sha>`) with `bin/local-up` on a fresh SQLite database in
a temp dir, drives the user journey over HTTP (sign-up, sign-in, OAuth token, refresh and revoke,
`/me` with both auth schemes, projects and tasks, 401/404/422, sign-out, `/api-docs` and a CORS
preflight), and checks every answer of a contract operation against `contract/openapi.json`.
It prints `ok <method> <path> <status>` per step and `smoke: N/N ok` at the end, exits non-zero on
the first mismatch, and always stops its server and removes the temp dir. It refuses to start while
something answers on 8095: run `bin/local-down` first. The unit suite deselects the `smoke` test;
CI runs it in the `local-smoke` job.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `DJANGO_SECRET_KEY` | set by the `local` and `test` settings | required by `config.settings.base` |
| `DJANGO_DEBUG` | off | `1` turns debug on |
| `DJANGO_ALLOWED_HOSTS` | `127.0.0.1,localhost` | comma-separated |
| `DATABASE_URL` | `sqlite:///db.sqlite3` in the checkout | a `postgres://` URL needs `psycopg` installed |
| `APP_RELEASE` | `unknown` | reported by `/health`; `bin/local-up` sets it to the commit sha |
| `OAUTH_CLIENT_ID` | unset | client id of the public web client; unset, sign-up returns only the legacy fields |
| `GOOGLE_CLIENT_ID` | unset | Google OAuth client id the ID tokens must be issued for; unset, Google sign-in is refused |
| `LEGACY_AUTH_ENABLED` | `true` | `false` stops accepting the legacy `X-User-Email` / `X-User-Token` pair |
| `PROJECTS_TASKS_API_STATE_DIR` | `~/.local/state/projects-tasks-api` | where `bin/local-up` / `bin/local-down` keep the checkout, database, pid file and logs; `bin/local-smoke` points it at a temp dir |
| `SMOKE_TOKEN` | unset | deploy checks sending it in `X-Smoke-Token` skip the sign-up limit and the legacy-use count |

`uv run python manage.py oauth_web_application` creates the web client named by `OAUTH_CLIENT_ID`
(and does nothing while it is unset); `/oauth/token` needs it.

The sign-up and failed sign-in limits count in `CACHES["default"]` and in the process. With the
default `LocMemCache` each gunicorn worker counts on its own; point `CACHES` at a shared backend for
exact limits.

GlitchTip, CORS and smoke-check variables: see [docs/errors-and-cors.md](docs/errors-and-cors.md).

## Endpoints

- `GET /health` → `{"status": "ok", "release": "<APP_RELEASE>"}`
- `GET /api-docs` — Swagger UI; `GET /api-docs/v1/swagger.json` — the OpenAPI contract
  (`contract/openapi.json`) with `servers` set to the requesting origin
- `POST /api/errors` — the frontend's Sentry tunnel to GlitchTip
- `POST /admin/glitchtip_smoke/<kind>` — GlitchTip smoke checks, hidden without `SMOKE_TOKEN`
- `POST /api/v1/users` — sign up; 201 (with a token pair when the web client is configured), 422,
  429 after 5 sign-ups an hour from one address
- `POST /api/v1/sign_in` — legacy sign-in with email and password; 200, 401, 429 after 10 failed
  sign-ins a minute from one address (shared with `/oauth/token`)
- `POST /api/v1/sign_out` — authenticated; 204 (ends this bearer token, or rotates the legacy
  token), 401
- `GET /api/v1/me` — authenticated; 200 with the user's id and email, 401
- `POST /oauth/token` — `password`, `refresh_token` and `google_id_token` grants (form or JSON body);
  200, 400, 401, 429
- `POST /oauth/revoke` — revokes an access or refresh token; 200 for any parseable body
  (an unparseable JSON body answers 400)
- `/api/v1/projects` and `/api/v1/projects/{id}`, with tasks nested under
  `/api/v1/projects/{project_id}/tasks` — authenticated CRUD; see
  [docs/projects-and-tasks.md](docs/projects-and-tasks.md)

Authenticated endpoints take `Authorization: Bearer <access_token>`, or the legacy
`X-User-Email` / `X-User-Token` pair. Unknown URLs answer `404 {"status": 404, "error": "Not Found"}`.

## License

[MIT](LICENSE).

Third-party licenses: dependencies are installed from PyPI, not vendored. Every direct dependency is
under a permissive license (MIT, BSD or Apache-2.0). Two transitive ones are copyleft:

- jwcrypto (LGPL-3.0-or-later), a required dependency of django-oauth-toolkit;
- certifi (MPL-2.0), through requests (via django-oauth-toolkit) and through sentry-sdk.
