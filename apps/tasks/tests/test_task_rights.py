"""The task endpoints per role: any role reads, the owner and members write, strangers see
nothing."""

import pytest

from apps.tasks.models import Task
from tests.contract import assert_matches_contract

LIST = "/api/v1/projects/{project_id}/tasks"
ONE = "/api/v1/projects/{project_id}/tasks/{id}"
NOT_FOUND = {"error": "Not Found"}
FORBIDDEN = {"error": "You are not authorized to perform this action"}
NEW_TASK = {"task": {"name": "Shared task", "description": "Added by a collaborator"}}

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(make_project):
    return make_project()


@pytest.fixture
def task(project, make_task):
    return make_task(project=project)


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
    def request(role, method, path, data=None):
        return getattr(client, method)(
            path, data, content_type="application/json", headers=bearer(users[role])
        )

    return request


def tasks_of(project):
    return LIST.format(project_id=project.id)


def one(task):
    return ONE.format(project_id=task.project_id, id=task.id)


@pytest.mark.parametrize("role", ["owner", "member", "viewer"])
class TestAnyRoleReads:
    def test_lists_the_tasks(self, send, project, task, role):
        response = send(role, "get", tasks_of(project))

        assert_matches_contract(response, "get", LIST)
        assert [each["id"] for each in response.json()["data"]] == [task.id]

    def test_shows_a_task(self, send, task, role):
        response = send(role, "get", one(task))

        assert_matches_contract(response, "get", ONE)
        assert response.json()["data"]["id"] == task.id


@pytest.mark.parametrize("role", ["owner", "member"])
class TestOwnerAndMemberWrite:
    def test_create_a_task(self, send, project, role):
        response = send(role, "post", tasks_of(project), NEW_TASK)

        assert_matches_contract(response, "post", LIST)
        assert response.status_code == 201
        assert project.tasks.filter(name="Shared task").exists()

    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_change_a_task(self, send, task, role, method):
        response = send(role, method, one(task), {"task": {"status": "completed"}})

        assert response.status_code == 200
        task.refresh_from_db()
        assert task.status == "completed"

    def test_delete_a_task(self, send, task, role):
        response = send(role, "delete", one(task))

        assert_matches_contract(response, "delete", ONE)
        assert response.status_code == 204
        assert not Task.objects.filter(pk=task.id).exists()


class TestViewerCannotWrite:
    def test_create_a_task(self, send, project):
        response = send("viewer", "post", tasks_of(project), NEW_TASK)

        assert (response.status_code, response.json()) == (403, FORBIDDEN)
        assert not project.tasks.exists()

    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_change_a_task(self, send, task, method):
        response = send("viewer", method, one(task), {"task": {"status": "completed"}})

        assert (response.status_code, response.json()) == (403, FORBIDDEN)
        task.refresh_from_db()
        assert task.status == "not_started"

    def test_delete_a_task(self, send, task):
        response = send("viewer", "delete", one(task))

        assert (response.status_code, response.json()) == (403, FORBIDDEN)
        assert Task.objects.filter(pk=task.id).exists()


class TestStrangerSeesNothing:
    @pytest.mark.parametrize(
        ("method", "template", "data"),
        [
            ("get", LIST, None),
            ("post", LIST, NEW_TASK),
            ("get", ONE, None),
            ("put", ONE, {"task": {"status": "completed"}}),
            ("delete", ONE, None),
        ],
    )
    def test_answers_not_found(self, send, task, method, template, data):
        path = template.format(project_id=task.project_id, id=task.id)

        response = send("stranger", method, path, data)

        assert_matches_contract(response, method, template)
        assert (response.status_code, response.json()) == (404, NOT_FOUND)
        assert Task.objects.filter(project_id=task.project_id).count() == 1


@pytest.mark.parametrize("role", ["member", "viewer"])
def test_a_task_of_another_project_is_not_found_for_a_member(send, task, make_task, role):
    other = make_task()

    response = send(role, "get", ONE.format(project_id=task.project_id, id=other.id))

    assert (response.status_code, response.json()) == (404, NOT_FOUND)
