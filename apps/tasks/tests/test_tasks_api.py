"""The tasks endpoints, checked against the contract."""

from datetime import timedelta

import pytest

from apps.projects.tests.test_projects_api import arabic_indic
from apps.tasks.models import Task
from tests.contract import assert_matches_contract

LIST = "/api/v1/projects/{project_id}/tasks"
MEMBER = "/api/v1/projects/{project_id}/tasks/{id}"
INVALID = {"Authorization": "Bearer invalid"}
NOT_FOUND = {"error": "Not Found"}
ALLOWED_STATUSES_ERROR = "Status must be one of: not_started, in_progress, completed"

pytestmark = pytest.mark.django_db


@pytest.fixture
def headers(user, bearer):
    return bearer(user)


@pytest.fixture
def project(user, make_project):
    return make_project(user=user)


@pytest.fixture
def existing_task(project, make_task):
    return make_task(project=project)


def call(client, method, template, headers, data=None, **ids):
    response = getattr(client, method)(
        template.format(**ids), data, content_type="application/json", headers=headers
    )
    assert_matches_contract(response, method, template)
    return response


@pytest.mark.parametrize(
    ("method", "template", "data"),
    [
        ("get", LIST, None),
        ("post", LIST, {"task": {"name": "Test Task", "description": "This is a test task"}}),
        ("get", MEMBER, None),
        ("put", MEMBER, {"task": {"status": "in_progress"}}),
        ("delete", MEMBER, None),
    ],
)
def test_answers_not_authorized_to_an_invalid_bearer(
    client, project, existing_task, method, template, data
):
    response = call(
        client, method, template, INVALID, data, project_id=project.id, id=existing_task.id
    )

    assert response.status_code == 401
    assert response.json() == {"error": "Not Authorized"}


class TestList:
    def test_lists_the_projects_tasks(self, client, headers, project, make_task):
        tasks = [make_task(project=project) for _ in range(3)]

        response = call(client, "get", LIST, headers, project_id=project.id)

        assert response.status_code == 200
        assert [task["id"] for task in response.json()["data"]] == [task.id for task in tasks]

    def test_answers_not_found_for_a_missing_project(self, client, headers):
        response = call(client, "get", LIST, headers, project_id=999999)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    def test_answers_not_found_for_another_users_project(self, client, headers, make_project):
        response = call(client, "get", LIST, headers, project_id=make_project().id)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND


class TestCreate:
    def test_creates_a_task_not_started(self, client, headers, project):
        body = {"task": {"name": "Test Task", "description": "This is a test task"}}

        response = call(client, "post", LIST, headers, body, project_id=project.id)

        assert response.status_code == 201
        assert response.json()["data"]["status"] == "not_started"
        assert Task.objects.get(pk=response.json()["data"]["id"]).status == "not_started"

    def test_answers_not_found_for_a_missing_project(self, client, headers):
        body = {"task": {"name": "Test Task", "description": "This is a test task"}}

        response = call(client, "post", LIST, headers, body, project_id=999999)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    @pytest.mark.parametrize(
        ("task", "messages"),
        [
            (
                {"name": "", "description": ""},
                ["Name can't be blank", "Description can't be blank"],
            ),
            (
                {"name": "Test Task", "description": "This is a test task", "status": ""},
                [ALLOWED_STATUSES_ERROR],
            ),
            (
                {"name": "Test Task", "description": "This is a test task", "status": "archived"},
                [ALLOWED_STATUSES_ERROR],
            ),
        ],
    )
    def test_refuses_an_invalid_task(self, client, headers, project, task, messages):
        response = call(client, "post", LIST, headers, {"task": task}, project_id=project.id)

        assert response.status_code == 422
        assert set(messages) <= set(response.json()["errors"])
        assert Task.objects.count() == 0

    @pytest.mark.parametrize(
        ("task", "errors"),
        [
            (
                {"name": "", "description": "", "status": ""},
                [
                    ALLOWED_STATUSES_ERROR,
                    "Name can't be blank",
                    "Description can't be blank",
                    "Status can't be blank",
                ],
            ),
            (
                {"name": "a", "description": "b", "status": None},
                [ALLOWED_STATUSES_ERROR, "Status can't be blank"],
            ),
            (
                {"name": " ", "description": "b", "status": "archived"},
                [ALLOWED_STATUSES_ERROR, "Name can't be blank"],
            ),
        ],
    )
    def test_names_be_s_errors_in_be_s_order(self, client, headers, project, task, errors):
        response = call(client, "post", LIST, headers, {"task": task}, project_id=project.id)

        assert response.json() == {"errors": errors}

    def test_refuses_a_body_without_a_task(self, client, headers, project):
        response = call(client, "post", LIST, headers, {"task": {}}, project_id=project.id)

        assert response.status_code == 422
        assert response.json() == {"status": 422, "error": "Unprocessable Content"}


class TestShow:
    def test_shows_the_task_with_its_whole_project(
        self, client, user, headers, project, existing_task
    ):
        response = call(client, "get", MEMBER, headers, project_id=project.id, id=existing_task.id)

        assert response.status_code == 200
        task = {
            "id": existing_task.id,
            "name": "Sample Task",
            "description": "This is a sample task description",
            "status": "not_started",
        }
        assert response.json()["data"] == task | {
            "project": {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "user": {"id": user.id, "email": user.email},
                "tasks": [task],
            }
        }
        assert list(response.json()["data"]) == ["id", "name", "description", "status", "project"]

    def test_answers_not_found_for_a_missing_task(self, client, headers, project):
        response = call(client, "get", MEMBER, headers, project_id=project.id, id=999999)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    @pytest.mark.parametrize("id_in", ["project_id", "id"])
    def test_answers_not_found_for_ids_in_non_ascii_digits(
        self, client, headers, project, existing_task, id_in
    ):
        ids = {"project_id": project.id, "id": existing_task.id}
        ids[id_in] = arabic_indic(ids[id_in])

        response = call(client, "get", MEMBER, headers, **ids)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND


class TestUpdate:
    def test_writes_nothing_when_nothing_changed(
        self, client, user, headers, project, existing_task, clock
    ):
        project.refresh_from_db()
        user.refresh_from_db()
        touched = existing_task.updated_at, project.updated_at, user.updated_at
        clock.travel(timedelta(seconds=1))
        body = {"task": {"status": existing_task.status}}

        response = call(
            client, "put", MEMBER, headers, body, project_id=project.id, id=existing_task.id
        )

        assert response.status_code == 200
        for record in (existing_task, project, user):
            record.refresh_from_db()
        assert (existing_task.updated_at, project.updated_at, user.updated_at) == touched

    @pytest.mark.parametrize("status", ["in_progress", "completed"])
    def test_changes_the_status(self, client, headers, project, existing_task, status):
        body = {"task": {"status": status}}

        response = call(
            client, "put", MEMBER, headers, body, project_id=project.id, id=existing_task.id
        )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == status
        existing_task.refresh_from_db()
        assert existing_task.status == status

    def test_answers_not_found_for_a_missing_task(self, client, headers, project):
        body = {"task": {"status": "in_progress"}}

        response = call(client, "put", MEMBER, headers, body, project_id=project.id, id=999999)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    @pytest.mark.parametrize(
        ("task", "message"),
        [
            ({"name": ""}, "Name can't be blank"),
            ({"status": ""}, ALLOWED_STATUSES_ERROR),
            ({"status": "archived"}, ALLOWED_STATUSES_ERROR),
        ],
    )
    def test_refuses_an_invalid_change(
        self, client, headers, project, existing_task, task, message
    ):
        response = call(
            client,
            "put",
            MEMBER,
            headers,
            {"task": task},
            project_id=project.id,
            id=existing_task.id,
        )

        assert response.status_code == 422
        assert message in response.json()["errors"]
        existing_task.refresh_from_db()
        assert existing_task.name == "Sample Task"
        assert existing_task.status == "not_started"


class TestDelete:
    def test_deletes_the_task(self, client, headers, project, existing_task):
        response = call(
            client, "delete", MEMBER, headers, project_id=project.id, id=existing_task.id
        )

        assert response.status_code == 204
        assert not Task.objects.filter(pk=existing_task.id).exists()

    def test_answers_not_found_for_a_missing_task(self, client, headers, project):
        response = call(client, "delete", MEMBER, headers, project_id=project.id, id=999999)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND


class TestProjectsListAfterATaskChange:
    @pytest.fixture
    def listed(self, client, headers, project, existing_task, clock):
        call(client, "get", "/api/v1/projects", headers)
        clock.travel(timedelta(seconds=1))
        return existing_task

    def list_tasks(self, client, headers):
        response = call(client, "get", "/api/v1/projects", headers)
        return response.json()["data"][0]["tasks"]

    def assert_touched(self, user, project, clock):
        user.refresh_from_db()
        project.refresh_from_db()
        assert user.updated_at == clock.now
        assert project.updated_at == clock.now

    def test_renders_an_updated_task(self, client, user, headers, project, listed, clock):
        body = {"task": {"status": "completed"}}
        call(client, "put", MEMBER, headers, body, project_id=project.id, id=listed.id)

        assert [task["status"] for task in self.list_tasks(client, headers)] == ["completed"]
        self.assert_touched(user, project, clock)

    def test_drops_a_deleted_task(self, client, user, headers, project, listed, clock):
        call(client, "delete", MEMBER, headers, project_id=project.id, id=listed.id)

        assert self.list_tasks(client, headers) == []
        self.assert_touched(user, project, clock)
