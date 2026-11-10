# Projects and tasks API

The projects and tasks endpoints (`apps/projects` and `apps/tasks`).
The contract is `contract/openapi.json`.

## Endpoints

Every endpoint needs a bearer access token or the legacy `X-User-Email` / `X-User-Token` pair;
without one it answers `401 {"error": "Not Authorized"}`.

| Method | Path | Body | Answers |
|---|---|---|---|
| GET | `/api/v1/projects[?task_status=<status>]` | — | 200 |
| POST | `/api/v1/projects` | `{"project": {"name", "description"}}` | 201, 422 |
| GET | `/api/v1/projects/{id}` | — | 200, 404 |
| PUT, PATCH | `/api/v1/projects/{id}` | `{"project": {"name"?, "description"?}}` | 200, 404, 422 |
| DELETE | `/api/v1/projects/{id}` | — | 204, 404, 422 |
| GET | `/api/v1/projects/{project_id}/tasks` | — | 200, 404 |
| POST | `/api/v1/projects/{project_id}/tasks` | `{"task": {"name", "description", "status"?}}` | 201, 404, 422 |
| GET | `/api/v1/projects/{project_id}/tasks/{id}` | — | 200, 404 |
| PUT, PATCH | `/api/v1/projects/{project_id}/tasks/{id}` | `{"task": {"name"?, "description"?, "status"?}}` | 200, 404, 422 |
| DELETE | `/api/v1/projects/{project_id}/tasks/{id}` | — | 204, 404 |

PATCH is not in the contract; it behaves as PUT.

## Answers

Bodies are wrapped as `{"data": …}`; DELETE answers 204 with no body. Lists are in id order.

- Project: `{"id", "name", "description", "user": {"id", "email"}, "tasks": [{"id", "name",
  "description", "status"}, …]}`.
- Task: `{"id", "name", "description", "status", "project": <the project above>}`; the nested
  project carries its `user` and `tasks` too (the contract's example shows the project without
  them).

`task_status` keeps the projects having a task of that status, and lists only those tasks in
each; an unknown status lists nothing.

## Lookups

A project is looked up among the caller's projects, a task among its project's tasks. Another
user's project or task answers `404 {"error": "Not Found"}`, like a missing one, never 403. Ids
are read by their leading digits: `5abc` and `5.json` name 5, `abc` names nothing.

## Requests and validation

A project body is a `project` object, of which only `name` and `description` are read; a task
body is a `task` object, of which only `name`, `description` and `status` are read. A missing or
empty `project` / `task` answers `422 {"status": 422, "error": "Unprocessable Content"}`. Other
keys are ignored, arrays and objects are dropped, numbers become their text and booleans `"t"` /
`"f"`. A JSON body without the wrapper key is read as if wrapped under it.

Invalid records answer `422 {"errors": [...]}` with these messages, in this order:

- Project: `Name can't be blank`, `Name is too short (minimum is 5 characters)` /
  `Name is too long (maximum is 20 characters)`, `Description can't be blank`,
  `Description is too short (minimum is 20 characters)` /
  `Description is too long (maximum is 120 characters)`.
- Task: `Status must be one of: not_started, in_progress, completed`, `Name can't be blank`,
  `Description can't be blank`, `Status can't be blank`. A new task without `status` is
  `not_started`.
- Deleting a project that has tasks: `Cannot delete record because dependent tasks exist`.

## List caches and query cost

Both lists are cached for 15 minutes (Django's default cache) under keys derived from the
database on each request, so any write to the list changes the key:

- `projects:<user id>:stats:count=<n>:updated=<latest updated_at|none>[:filter:<status>]:v1`
- `tasks:<project id>:stats:count=<n>:updated=<latest updated_at|none>:v1`

The timestamp is ISO 8601 to the microsecond. Saving or deleting a task touches its project and
the project's owner, and keeps `projects.tasks_count`; saving or deleting a project touches its
owner and keeps `users.projects_count`.

The cached tasks list keeps each task's nested project as it was when the list was cached, until
a task of the project changes.

`GET /api/v1/projects` costs at most 4 queries on a cache miss, whatever the number of projects
and tasks (`apps/projects/tests/test_dashboard_list_cost.py`).
