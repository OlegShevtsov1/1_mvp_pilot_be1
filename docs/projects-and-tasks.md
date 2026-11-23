# Projects and tasks API

The projects, members and tasks endpoints (`apps/projects` and `apps/tasks`).
The contract is `contract/openapi.json`.

## Endpoints

Every endpoint needs a bearer access token or the legacy `X-User-Email` / `X-User-Token` pair;
without one it answers `401 {"error": "Not Authorized"}`.

| Method | Path | Body | Answers |
|---|---|---|---|
| GET | `/api/v1/projects[?task_status=<status>]` | — | 200 |
| POST | `/api/v1/projects` | `{"project": {"name", "description"}}` | 201, 422 |
| GET | `/api/v1/projects/{id}` | — | 200, 404 |
| PUT, PATCH | `/api/v1/projects/{id}` | `{"project": {"name"?, "description"?}}` | 200, 403, 404, 422 |
| DELETE | `/api/v1/projects/{id}` | — | 204, 403, 404, 422 |
| GET | `/api/v1/projects/{project_id}/tasks` | — | 200, 404 |
| POST | `/api/v1/projects/{project_id}/tasks` | `{"task": {"name", "description", "status"?}}` | 201, 403, 404, 422 |
| GET | `/api/v1/projects/{project_id}/tasks/{id}` | — | 200, 404 |
| PUT, PATCH | `/api/v1/projects/{project_id}/tasks/{id}` | `{"task": {"name"?, "description"?, "status"?}}` | 200, 403, 404, 422 |
| DELETE | `/api/v1/projects/{project_id}/tasks/{id}` | — | 204, 403, 404 |
| GET | `/api/v1/projects/{project_id}/members` | — | 200, 404 |
| POST | `/api/v1/projects/{project_id}/members` | `{"member": {"email", "role"}}` | 201, 403, 404, 422 |
| PUT, PATCH | `/api/v1/projects/{project_id}/members/{id}` | `{"member": {"role"}}` | 200, 403, 404, 422 |
| DELETE | `/api/v1/projects/{project_id}/members/{id}` | — | 204, 403, 404 |
| GET | `/api/v1/projects/{project_id}/tasks/{id}/dependencies` | — | 200, 404 |
| POST | `/api/v1/projects/{project_id}/tasks/{id}/dependencies` | `{"dependency": {"task_id"}}` | 201, 403, 404, 422 |
| DELETE | `/api/v1/projects/{project_id}/tasks/{id}/dependencies/{blocker_id}` | — | 204, 403, 404 |
| GET | `/api/v1/projects/{project_id}/labels` | — | 200, 404 |
| POST | `/api/v1/projects/{project_id}/labels` | `{"label": {"name", "color"?}}` | 201, 403, 404, 422 |
| GET | `/api/v1/projects/{project_id}/labels/{id}` | — | 200, 404 |
| PUT, PATCH | `/api/v1/projects/{project_id}/labels/{id}` | `{"label": {"name"?, "color"?}}` | 200, 403, 404, 422 |
| DELETE | `/api/v1/projects/{project_id}/labels/{id}` | — | 204, 403, 404 |
| GET | `/api/v1/projects/{project_id}/labels/{id}/tasks` | — | 200, 404 |
| GET | `/api/v1/projects/{project_id}/tasks/{id}/labels` | — | 200, 404 |
| POST | `/api/v1/projects/{project_id}/tasks/{id}/labels` | `{"label": {"label_id"}}` | 201, 403, 404, 422 |
| DELETE | `/api/v1/projects/{project_id}/tasks/{id}/labels/{label_id}` | — | 204, 403, 404 |

403 only reaches a member or viewer of the project (see "Members and roles"); the project's owner
and strangers get the answers they always got. The 403s of the project and task operations are not
in the contract, whose paths for them are kept unchanged.

PATCH is not in the contract; it behaves as PUT.

## Members and roles

A project's owner (`project.user`) can share it with other users, each as a `member` or a
`viewer` (`projects.Membership`, one per project and user; the owner never has one). Rights by
role (`apps/projects/access.py`):

| | owner | member | viewer | anyone else |
|---|---|---|---|---|
| GET the project, its tasks, its members, labels and dependencies | yes | yes | yes | 404 |
| POST, PUT, PATCH, DELETE its tasks, labels and dependencies | yes | yes | 403 | 404 |
| PUT, PATCH, DELETE the project | yes | 403 | 403 | 404 |
| POST, PUT, PATCH members; DELETE another's membership | yes | 403 | 403 | 404 |
| DELETE their own membership (leave) | — | yes | yes | 404 |

`GET /api/v1/projects` lists the projects the caller owns and those shared with them, in id order;
a shared project renders its owner as `user`.

A member renders as `{"id", "role", "user": {"id", "email"}, "created_at", "updated_at"}`, with
ISO 8601 timestamps; the list is in id order. `POST` names the user by `email` (compared trimmed
and lowercased) and takes `role`; a body without the `member` key is read as if wrapped under it.
It answers:

- `404 {"error": "User not found"}` when no user has the email;
- `422 {"errors": [...]}` with `User is the project owner` or `User is already a member`, then
  `Role must be one of: member, viewer` for a missing or unknown role;
- `201 {"data": <member>}` otherwise.

`PUT` / `PATCH` read only `role` and answer 200, or 422 with the role message. A membership id of
another project answers `404 {"error": "Not Found"}` like a missing one. Saving or deleting a
membership touches its project's `updated_at`; deleting a project deletes its memberships.

## Dependencies

A task can be blocked by other tasks of its project (`Task.blocked_by`; `blocks` is the other
direction). The dependencies of a task are a sub-resource: the task and project JSON don't
include them.

`GET …/tasks/{id}/dependencies` lists the blockers as tasks (the task JSON below), in id order.
`POST` names the blocker by `task_id`; a body without the `dependency` key is read as if wrapped
under it. It answers `201 {"data": <the blocker as a task>}`, or `422 {"errors": [...]}` with one
of:

- `Task must belong to the same project`: a task of another project, or no task with the id;
- `Task cannot depend on itself`;
- `Dependency already exists`;
- `Dependency would create a cycle`: the task is already among the tasks the blocker waits for,
  directly or not. The project's dependencies are read in one query and walked in memory, so
  the check costs the same whatever the length of the chain.

`DELETE …/tasks/{id}/dependencies/{blocker_id}` removes one dependency, or answers
`404 {"error": "Not Found"}` when the task is not blocked by that task.

Changing a task's status to `completed` (PUT / PATCH on the task) while one of its blockers is
not `completed` answers `422 {"errors": ["Task is blocked by unfinished tasks"]}`, after the task's
other messages. A task already `completed` stays so, and the other statuses and fields are
never refused for a blocker. Deleting a task deletes its dependencies in both directions, so the
tasks it blocked are free.

## Labels

A project has labels (`tasks.Label`): `{"id", "name", "color", "created_at", "updated_at"}`, with
ISO 8601 timestamps, in id order. A label body is a `label` object of which `name` and `color`
are read (unwrapped bodies are wrapped as above). `POST` without a `color`, or with `null`,
takes `#808080`; `PUT` / `PATCH` change only the keys given. Invalid labels answer
`422 {"errors": [...]}` with these messages, in this order: `Name can't be blank` /
`Name is too long (maximum is 30 characters)`, `Name has already been taken` (names are unique
in their project, compared exactly), `Color must be a hex color like #1a2b3c` (`#` and six hex
digits).

A project's labels are attached to its tasks:

- `GET …/tasks/{id}/labels` lists the task's labels;
- `POST …/tasks/{id}/labels` with `{"label": {"label_id"}}` answers `201 {"data": <label>}`, or
  422 with `Label must belong to the same project` (another project's label, or no label with
  the id) or `Label already attached`;
- `DELETE …/tasks/{id}/labels/{label_id}` detaches it, or answers 404 when it is not attached;
- `GET …/labels/{id}/tasks` lists the tasks carrying the label, as tasks, in id order.

Deleting a label detaches it from its tasks; deleting a project deletes its labels; deleting a
task detaches its labels. A label of another project answers `404 {"error": "Not Found"}` like a
missing one.

Saving or deleting a label, attaching or detaching one, and adding or removing a dependency touch
the project's `updated_at`, so the projects list key changes. The task and project JSON carry
neither labels nor dependencies, so no cached list goes stale through them.

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

A project is looked up among the projects the caller sees (owned or shared), a task among its
project's tasks. A project the caller does not see, and its tasks, answer
`404 {"error": "Not Found"}`, like a missing one, never 403; a project they see with too low a role
answers `403 {"error": "You are not authorized to perform this action"}`. Ids
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

- `projects:<user id>:stats:count=<n>:updated=<latest updated_at|none>[:filter:<SHA-256 of the status>]:v1`,
  over the projects the user sees (owned and shared)
- `tasks:<project id>:stats:count=<n>:updated=<latest updated_at|none>:v1`

The timestamp is ISO 8601 to the microsecond. Saving or deleting a task touches its project and
the project's owner, and keeps `projects.tasks_count`; saving or deleting a project touches its
owner and keeps `users.projects_count`; saving or deleting a membership touches its project. So a
member's list key changes when a shared project or its tasks change (its `updated_at`), when a
membership is added or its role changes (the touched project is the latest), and when one is
removed (the count drops).

The cached tasks list keeps each task's nested project as it was when the list was cached, until
a task of the project changes.

`GET /api/v1/projects` costs at most 4 queries on a cache miss, whatever the number of projects
and tasks (`apps/projects/tests/test_dashboard_list_cost.py`).
