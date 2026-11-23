"""The dependency endpoints per role, the completion rule and task deletion, checked against the
contract."""

import pytest

from apps.tasks.models import Task
from tests.contract import assert_matches_contract

LIST = "/api/v1/projects/{project_id}/tasks/{id}/dependencies"
ONE = "/api/v1/projects/{project_id}/tasks/{id}/dependencies/{blocker_id}"
TASK = "/api/v1/projects/{project_id}/tasks/{id}"
INVALID = {"Authorization": "Bearer invalid"}
NOT_FOUND = {"error": "Not Found"}
FORBIDDEN = {"error": "You are not authorized to perform this action"}
PARAMETER_MISSING = {"status": 422, "error": "Unprocessable Content"}
SAME_PROJECT = "Task must belong to the same project"
BLOCKED = "Task is blocked by unfinished tasks"

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(make_project):
    return make_project()


@pytest.fixture
def task(project, make_task):
    return make_task(project=project, name="Blocked")


@pytest.fixture
def blocker(project, make_task):
    return make_task(project=project, name="Blocker")


@pytest.fixture
def users(project, make_user, make_membership):
    return {
        "owner": project.user,
        "member": make_membership(project=project, role="member").user,
        "viewer": make_membership(project=project, role="viewer").user,
        "stranger": make_user(),
    }


@pytest.fixture
def send(client, bearer, users):
    def request(role, method, template, data=None, contract=True, **ids):
        response = getattr(client, method)(
            template.format(**ids),
            data,
            content_type="application/json",
            headers=bearer(users[role]) if role else INVALID,
        )
        if contract:
            assert_matches_contract(response, method, template)
        return response

    return request


def deps(task):
    return {"project_id": task.project_id, "id": task.id}


def dep(task, blocker_id):
    return deps(task) | {"blocker_id": blocker_id}


def body(task_id):
    return {"dependency": {"task_id": task_id}}


def blocker_ids(task):
    return list(task.blocked_by.order_by("id").values_list("id", flat=True))


@pytest.mark.parametrize(
    ("method", "template", "data"),
    [("get", LIST, None), ("post", LIST, {"dependency": {"task_id": 1}}), ("delete", ONE, None)],
)
def test_answers_not_authorized_to_an_invalid_bearer(send, task, blocker, method, template, data):
    task.blocked_by.add(blocker)

    response = send(None, method, template, data, **dep(task, blocker.id))

    assert (response.status_code, response.json()) == (401, {"error": "Not Authorized"})


class TestList:
    @pytest.mark.parametrize("role", ["owner", "member", "viewer"])
    def test_lists_the_blockers_in_id_order_as_tasks(
        self, send, project, task, blocker, make_task, role
    ):
        later = make_task(project=project, name="Later")
        task.blocked_by.add(later, blocker)

        response = send(role, "get", LIST, **deps(task))

        assert response.status_code == 200
        data = response.json()["data"]
        assert [each["id"] for each in data] == [blocker.id, later.id]
        shown = send(role, "get", TASK, **deps(blocker)).json()["data"]
        assert data[0] == shown

    def test_lists_nothing_for_an_unblocked_task(self, send, task):
        assert send("owner", "get", LIST, **deps(task)).json() == {"data": []}

    def test_answers_not_found_to_a_stranger(self, send, task):
        response = send("stranger", "get", LIST, **deps(task))

        assert (response.status_code, response.json()) == (404, NOT_FOUND)

    def test_answers_not_found_for_a_task_of_another_project(self, send, project, make_task):
        other = make_task()

        response = send("owner", "get", LIST, project_id=project.id, id=other.id)

        assert (response.status_code, response.json()) == (404, NOT_FOUND)


class TestAdd:
    @pytest.mark.parametrize("role", ["owner", "member"])
    def test_adds_the_blocker_and_answers_it(self, send, task, blocker, role):
        response = send(role, "post", LIST, body(blocker.id), **deps(task))

        assert response.status_code == 201
        assert blocker_ids(task) == [blocker.id]
        assert response.json() == {"data": send(role, "get", TASK, **deps(blocker)).json()["data"]}

    def test_reads_an_unwrapped_body_as_the_dependency(self, send, task, blocker):
        response = send("owner", "post", LIST, {"task_id": blocker.id}, **deps(task))

        assert response.status_code == 201
        assert blocker_ids(task) == [blocker.id]

    def test_reads_a_string_id(self, send, task, blocker):
        response = send("owner", "post", LIST, body(str(blocker.id)), **deps(task))

        assert response.status_code == 201

    def test_is_forbidden_to_a_viewer(self, send, task, blocker):
        response = send("viewer", "post", LIST, body(blocker.id), **deps(task))

        assert (response.status_code, response.json()) == (403, FORBIDDEN)
        assert blocker_ids(task) == []

    def test_answers_not_found_to_a_stranger(self, send, task, blocker):
        response = send("stranger", "post", LIST, body(blocker.id), **deps(task))

        assert (response.status_code, response.json()) == (404, NOT_FOUND)
        assert blocker_ids(task) == []

    def test_refuses_a_task_of_another_project(self, send, task, make_task):
        other = make_task()

        response = send("owner", "post", LIST, body(other.id), **deps(task))

        assert (response.status_code, response.json()) == (422, {"errors": [SAME_PROJECT]})
        assert blocker_ids(task) == []

    @pytest.mark.parametrize("task_id", [999999, "abc", None, ""])
    def test_refuses_an_unknown_task(self, send, task, task_id):
        response = send("owner", "post", LIST, body(task_id), **deps(task))

        assert (response.status_code, response.json()) == (422, {"errors": [SAME_PROJECT]})

    def test_refuses_the_task_itself(self, send, task):
        response = send("owner", "post", LIST, body(task.id), **deps(task))

        assert response.status_code == 422
        assert response.json() == {"errors": ["Task cannot depend on itself"]}

    def test_refuses_an_existing_dependency(self, send, task, blocker):
        task.blocked_by.add(blocker)

        response = send("owner", "post", LIST, body(blocker.id), **deps(task))

        assert (response.status_code, response.json()) == (
            422,
            {"errors": ["Dependency already exists"]},
        )
        assert blocker_ids(task) == [blocker.id]

    def test_refuses_a_direct_cycle(self, send, task, blocker):
        task.blocked_by.add(blocker)

        response = send("owner", "post", LIST, body(task.id), **deps(blocker))

        assert response.status_code == 422
        assert response.json() == {"errors": ["Dependency would create a cycle"]}
        assert blocker_ids(blocker) == []

    @pytest.mark.parametrize("body", [{"dependency": {}}, {"dependency": None}, []])
    def test_refuses_a_body_without_a_dependency(self, send, task, body):
        response = send("owner", "post", LIST, body, **deps(task))

        assert (response.status_code, response.json()) == (422, PARAMETER_MISSING)


class TestRemove:
    @pytest.mark.parametrize("role", ["owner", "member"])
    def test_removes_the_dependency(self, send, task, blocker, role):
        task.blocked_by.add(blocker)

        response = send(role, "delete", ONE, **dep(task, blocker.id))

        assert response.status_code == 204
        assert response.content == b""
        assert blocker_ids(task) == []
        assert Task.objects.filter(pk=blocker.id).exists()

    def test_is_forbidden_to_a_viewer(self, send, task, blocker):
        task.blocked_by.add(blocker)

        response = send("viewer", "delete", ONE, **dep(task, blocker.id))

        assert (response.status_code, response.json()) == (403, FORBIDDEN)
        assert blocker_ids(task) == [blocker.id]

    def test_answers_not_found_to_a_stranger(self, send, task, blocker):
        task.blocked_by.add(blocker)

        response = send("stranger", "delete", ONE, **dep(task, blocker.id))

        assert (response.status_code, response.json()) == (404, NOT_FOUND)
        assert blocker_ids(task) == [blocker.id]

    @pytest.mark.parametrize("raw", ["999999", "abc"])
    def test_answers_not_found_for_a_missing_dependency(self, send, task, blocker, raw):
        response = send("owner", "delete", ONE, **dep(task, raw))

        assert (response.status_code, response.json()) == (404, NOT_FOUND)

    def test_answers_not_found_for_the_reverse_direction(self, send, task, blocker):
        task.blocked_by.add(blocker)

        response = send("owner", "delete", ONE, **dep(blocker, task.id))

        assert (response.status_code, response.json()) == (404, NOT_FOUND)
        assert blocker_ids(task) == [blocker.id]


class TestCompletionRule:
    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_refuses_to_complete_a_task_with_an_unfinished_blocker(
        self, send, task, blocker, method
    ):
        task.blocked_by.add(blocker)

        response = send(
            "owner", method, TASK, {"task": {"status": "completed"}}, contract=False, **deps(task)
        )

        assert (response.status_code, response.json()) == (422, {"errors": [BLOCKED]})
        task.refresh_from_db()
        assert task.status == "not_started"

    def test_refusal_matches_the_contract(self, send, task, blocker):
        task.blocked_by.add(blocker)

        response = send("owner", "put", TASK, {"task": {"status": "completed"}}, **deps(task))

        assert response.status_code == 422

    def test_completes_a_task_once_every_blocker_is_completed(
        self, send, project, task, blocker, make_task
    ):
        done = make_task(project=project, status="completed")
        task.blocked_by.add(blocker, done)
        send("owner", "put", TASK, {"task": {"status": "completed"}}, **deps(blocker))

        response = send("owner", "put", TASK, {"task": {"status": "completed"}}, **deps(task))

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "completed"

    @pytest.mark.parametrize("status", ["in_progress", "not_started"])
    def test_lets_a_blocked_task_take_another_status(self, send, task, blocker, status):
        task.blocked_by.add(blocker)

        response = send("owner", "put", TASK, {"task": {"status": status}}, **deps(task))

        assert response.status_code == 200

    def test_lets_a_blocked_task_change_other_fields(self, send, task, blocker):
        task.blocked_by.add(blocker)

        response = send("owner", "put", TASK, {"task": {"name": "Renamed"}}, **deps(task))

        assert response.status_code == 200

    def test_only_blockers_count_not_the_tasks_it_blocks(self, send, task, blocker):
        task.blocked_by.add(blocker)

        response = send("owner", "put", TASK, {"task": {"status": "completed"}}, **deps(blocker))

        assert response.status_code == 200

    def test_follows_the_other_messages(self, send, task, blocker):
        task.blocked_by.add(blocker)
        data = {"task": {"status": "completed", "name": " "}}

        response = send("owner", "put", TASK, data, **deps(task))

        assert response.json() == {"errors": ["Name can't be blank", BLOCKED]}


class TestTaskDeletion:
    def test_deleting_a_task_removes_its_dependencies_in_both_directions(
        self, send, project, task, blocker, make_task
    ):
        waiting = make_task(project=project, name="Waiting")
        task.blocked_by.add(blocker)
        waiting.blocked_by.add(task)

        response = send("owner", "delete", TASK, **deps(task))

        assert response.status_code == 204
        edges = Task.blocked_by.through.objects
        assert not edges.filter(from_task_id=task.id).exists()
        assert not edges.filter(to_task_id=task.id).exists()
        assert blocker_ids(waiting) == []
        assert set(project.tasks.values_list("id", flat=True)) == {blocker.id, waiting.id}

    def test_a_task_freed_by_a_deleted_blocker_completes(self, send, task, blocker):
        task.blocked_by.add(blocker)
        send("owner", "delete", TASK, **deps(blocker))

        response = send("owner", "put", TASK, {"task": {"status": "completed"}}, **deps(task))

        assert response.status_code == 200

    def test_a_project_still_refuses_deletion_while_it_has_tasks(self, send, project, task):
        response = send("owner", "delete", "/api/v1/projects/{id}", contract=False, id=project.id)

        assert response.status_code == 422
