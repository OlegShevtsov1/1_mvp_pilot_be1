# Error intake, GlitchTip, CORS and API docs

The frontend error intake (`apps/errors`), the GlitchTip smoke checks (`apps/admin_smoke`), the
backend Sentry setup, and the CORS and API docs settings.

## `POST /api/errors`

The frontend's Sentry tunnel (`apps/errors`). It relays a browser SDK envelope to GlitchTip, so
ad blockers and the CSP only ever see this API.

- An envelope is accepted when the DSN in its header has the public key and project id of
  `SENTRY_ALLOWED_FE_DSN`; its host, scheme, port, path and secret are ignored. The upstream URL
  and the `X-Sentry-Auth` key come from the allowed DSN only, never from the request.
- Answers:
  - the upstream status and body, passed through;
  - `403 {"error": "dsn not allowed"}` for another key or project;
  - `400 {"error": "malformed envelope"}` (also for a header DSN that is not a valid RFC 3986
    http(s) URI) or `400 {"error": "envelope header has no http(s) dsn"}`;
  - `413` (empty body) over 256 KiB;
  - `502 {"error": "upstream unreachable"}` when GlitchTip does not answer (connect 2 s, read 5 s);
  - `404` (empty body) while `SENTRY_ALLOWED_FE_DSN` is unset, and for any method but POST;
  - `429` (empty body, no `Retry-After`) past 30 requests a minute from one client IP.
- The limit is counted before anything else, so accepted, refused, too-large and 404 requests all
  count. The window is fixed: it starts with a client's first request. Each request is counted
  in Django's default cache and in the process's memory, and the higher count wins. The default
  cache is per process today, so with several gunicorn workers the limit is per worker.

## `POST /admin/glitchtip_smoke/<kind>`

Deliberate failures that prove a deployment's errors reach GlitchTip (`apps/admin_smoke`), each
tagged with a marker: the `X-Smoke-Marker` header when it is 1–63 word characters or `-`, a
generated `glitchtip-smoke-<12 hex>` otherwise.

Hidden unless the caller presents `SMOKE_TOKEN` in `X-Smoke-Token`: every refusal is a 404 with an
empty body, never a 401/403. That covers a missing or wrong token, an unset `SMOKE_TOKEN`, an
unknown kind and any method but POST.

| Kind | Answer | GlitchTip receives |
|---|---|---|
| `manual` | `202 {"kind": "manual", "marker": …, "event_id": …}` (`event_id` is null while `SENTRY_DSN` is unset) | the message `glitchtip smoke manual <marker>` |
| `unhandled` | 500 | a `GlitchtipSmokeError` carrying the marker |
| `db` | 500 | a database error naming the marker as an unknown column |

## Backend errors to GlitchTip

The Sentry SDK (`sentry-sdk[django]`) is initialised at startup by `apps.errors`. Without
`SENTRY_DSN` it sends nothing, which keeps development and the tests offline. The DSN is never
logged. Every event is scrubbed with the filter parameters (`passw`, `email`, `secret`, `token`,
`_key`, `crypt`, `salt`, `certificate`, `otp`, `ssn`, matched case-insensitively anywhere in a key)
in the request data, headers and query string and in the extra data. Frame locals are not sent.

## CORS

django-cors-headers, set up as follows:

- origins: those listed in `CORS_ALLOWED_ORIGINS`, read per request; unset or empty allows none;
- methods `GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD`; any request header (the preflight's
  `Access-Control-Request-Headers` is echoed); `Retry-After` exposed; no credentials; preflight
  max age 7200 s.

## API docs

`GET /api-docs/v1/swagger.json` serves `contract/openapi.json` with `servers` replaced by the
origin the reader reached (`X-Forwarded-Proto`/`X-Forwarded-Host` when a proxy sets them) and the
description `<SENTRY_ENVIRONMENT>`. `GET /api-docs` is a Swagger UI page for it.

## Environment

Secrets (`SENTRY_DSN`, `SENTRY_ALLOWED_FE_DSN`, `SMOKE_TOKEN`) are never logged or committed.

| Variable | Default | Meaning |
|---|---|---|
| `SENTRY_DSN` | unset | backend events go to GlitchTip; unset leaves the SDK inert |
| `SENTRY_ENVIRONMENT` | `development` (`test` under the test settings) | the Sentry environment and the swagger `servers` description |
| `APP_RELEASE` | unset: no release | the Sentry release (also reported by `/health`) |
| `SENTRY_ALLOWED_FE_DSN` | unset | the frontend DSN `/api/errors` accepts; unset makes `/api/errors` answer 404 |
| `CORS_ALLOWED_ORIGINS` | empty: no origin | comma-separated origins allowed to call the API from a browser |
| `SMOKE_TOKEN` | unset | the `X-Smoke-Token` value for `/admin/glitchtip_smoke/*`; unset makes it always 404 |
