# 1_mvp_pilot_be1

The Python + Django analogue of the Rails pilot backend `OlegShevtsov1/1_mvp_pilot_be`: the same JSON API,
so the frontend works unchanged.

**The API must match contract/openapi.json. Existing paths and components stay unchanged, so
existing clients keep working; a new endpoint is added to the contract with its schemas.**

**This repo uses the Django layout config/ + apps/ from django-patterns, not the src/ layout of
python-best-practices.**

## Stack

Python 3.12, Django 5.2 (LTS), Django REST framework, django-oauth-toolkit, drf-spectacular,
pytest + pytest-django + pytest-xdist, ruff, uv (dependencies locked in `uv.lock`).

## Commands

```bash
uv sync                                               # install, dev group included
uv run pytest -n auto                                 # tests (SQLite in memory)
uv run ruff check . && uv run ruff format --check .   # lint
uv run python manage.py makemigrations                # after a model change; commit the migration
bin/local-up [--ref <rev>]                            # run a commit of origin on 127.0.0.1:8095
bin/local-down                                        # stop it
bin/local-check                                       # exit 0 when /health answers 200
```

Change dependencies only with `uv add` / `uv remove` and commit `pyproject.toml` with `uv.lock`.

## Layout and conventions

- `config/settings/{base,local,test}.py`: `base` reads the environment (`DJANGO_SECRET_KEY`,
  `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`); `local` is the default of `manage.py`
  and `wsgi.py`; pytest uses `test`.
- Domain apps live in `apps/<name>/` with the label `<name>`; their tests in `apps/<name>/tests/`.
  Project-level tests live in `tests/`.
- The auth model `users.User` (`apps/users`) is final: email is the login and its columns are be's
  `users` table. Don't add `AbstractUser` / `PermissionsMixin` fields be doesn't have.
- Responses render as JSON only (no browsable API). API docs are served at `/api-docs` and
  `/api-docs/v1/swagger.json`, as be's rswag does.
- Every endpoint that is an operation of the contract is tested with
  `tests.contract.assert_matches_contract(response, method, path)`, where `path` is the
  contract's path template (e.g. `"/api/v1/projects/{id}"`). Endpoints be leaves out of the
  contract (`/health`) are tested against be's request specs instead.
- Never change an existing path or component (schemas, responses) of `contract/openapi.json`,
  so existing clients keep working. A new endpoint adds its path, and any schema it needs under
  `components.schemas` (referenced as `#/components/schemas/<Name>`). `info` and `servers` stay
  neutral (no origin project named).
- The skills in `.claude/skills/` are vendored; see `.claude/skills/README.md`.

## Auth and errors

Every DRF view is authenticated by `apps.users.authentication.DualSchemeAuthentication` (a bearer
access token, or the legacy `X-User-Email` / `X-User-Token` pair, whose use is counted) and needs
`IsAuthenticated`, so a new view gets both from `REST_FRAMEWORK` without declaring anything; an
unauthenticated request answers be's `401 {"error": "Not Authorized"}`. A public view sets
`authentication_classes = []` and `permission_classes = [AllowAny]`. In a view, `request.user` is
the user and `request.auth` the `AccessToken`, or `None` for the legacy pair.

Raise errors from `apps.common.exceptions` and let the exception handler render them; never build
an error body by hand: `ValidationFailed(errors[, message])` → 422, `ResourceNotFound("Project")` →
404 `{"error": "Project not found"}` (`Http404` → `{"error": "Not Found"}`), `Forbidden()` → 403,
`TooManyRequests(errors, retry_after[, message])` → 429 with `Retry-After`. Unknown URLs and
unhandled errors render Rails' `{"status": <code>, "error": "<reason>"}` (`apps.common.views`).
