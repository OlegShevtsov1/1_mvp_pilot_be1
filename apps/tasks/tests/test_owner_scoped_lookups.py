"""Project and task lookups scoped to the owner."""

import pytest
from django.forms.models import model_to_dict

from apps.projects.models import Project
from apps.tasks.models import Task

NOT_FOUND = (404, {"error": "Not Found"})
NOT_AUTHORIZED = (401, {"error": "Not Authorized"})

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(make_user):
    return make_user()


@pytest.fixture
def intruder(make_user):
    return make_user()


@pytest.fixture
def project(owner, make_project):
    return make_project(user=owner)


@pytest.fixture
def task(project, make_task):
    return make_task(project=project)


@pytest.fixture
def intruder_project(intruder, make_project):
    return make_project(user=intruder)


@pytest.fixture
def answer_to(client, intruder, bearer):
    headers = bearer(intruder)

    def answer(method, path, data=None):
        response = getattr(client, method)(
            path, data, content_type="application/json", headers=headers
        )
        return answer_of(response)

    return answer


def answer_of(response):
    return response.status_code, response.json()


def snapshot(record):
    record.refresh_from_db()
    return model_to_dict(record) | {"updated_at": record.updated_at}


class TestAnotherUsersProjectOrTask:
    def test_shows_a_project_like_a_missing_one(self, answer_to, project):
        assert answer_to("get", f"/api/v1/projects/{project.id}") == NOT_FOUND
        assert answer_to("get", "/api/v1/projects/0") == NOT_FOUND

    def test_refuses_to_change_a_project_like_a_missing_one(self, answer_to, project):
        before = snapshot(project)
        body = {"project": {"name": "Taken over"}}

        assert answer_to("patch", f"/api/v1/projects/{project.id}", body) == NOT_FOUND
        assert snapshot(project) == before
        assert answer_to("patch", "/api/v1/projects/0", body) == NOT_FOUND

    def test_refuses_to_delete_a_project_like_a_missing_one(self, answer_to, project):
        assert answer_to("delete", f"/api/v1/projects/{project.id}") == NOT_FOUND
        assert Project.objects.filter(pk=project.id).exists()
        assert answer_to("delete", "/api/v1/projects/0") == NOT_FOUND

    def test_lists_the_tasks_of_a_project_like_a_missing_one(self, answer_to, project):
        assert answer_to("get", f"/api/v1/projects/{project.id}/tasks") == NOT_FOUND
        assert answer_to("get", "/api/v1/projects/0/tasks") == NOT_FOUND

    def test_shows_a_task_like_a_missing_one(self, answer_to, project, task, intruder_project):
        assert answer_to("get", f"/api/v1/projects/{project.id}/tasks/{task.id}") == NOT_FOUND
        assert (
            answer_to("get", f"/api/v1/projects/{intruder_project.id}/tasks/{task.id}") == NOT_FOUND
        )
        assert answer_to("get", f"/api/v1/projects/{intruder_project.id}/tasks/0") == NOT_FOUND

    def test_refuses_to_change_a_task_like_a_missing_one(
        self, answer_to, project, task, intruder_project
    ):
        before = snapshot(task)
        body = {"task": {"status": "completed"}}

        assert (
            answer_to("patch", f"/api/v1/projects/{project.id}/tasks/{task.id}", body) == NOT_FOUND
        )
        assert (
            answer_to("patch", f"/api/v1/projects/{intruder_project.id}/tasks/{task.id}", body)
            == NOT_FOUND
        )
        assert snapshot(task) == before

    def test_refuses_to_delete_a_task_like_a_missing_one(
        self, answer_to, project, task, intruder_project
    ):
        assert answer_to("delete", f"/api/v1/projects/{project.id}/tasks/{task.id}") == NOT_FOUND
        assert (
            answer_to("delete", f"/api/v1/projects/{intruder_project.id}/tasks/{task.id}")
            == NOT_FOUND
        )
        assert Task.objects.filter(pk=task.id).exists()

    def test_refuses_to_add_a_task_to_another_users_project_like_a_missing_one(
        self, answer_to, project
    ):
        body = {"task": {"name": "Planted", "description": "x" * 20, "status": "not_started"}}

        assert answer_to("post", f"/api/v1/projects/{project.id}/tasks", body) == NOT_FOUND
        assert project.tasks.count() == 0


def test_the_owner_still_shows_and_changes_their_project_and_shows_its_task(
    client, owner, bearer, project, task
):
    headers = bearer(owner)

    assert client.get(f"/api/v1/projects/{project.id}", headers=headers).status_code == 200
    renamed = client.patch(
        f"/api/v1/projects/{project.id}",
        {"project": {"name": "Renamed"}},
        content_type="application/json",
        headers=headers,
    )
    assert renamed.status_code == 200
    project.refresh_from_db()
    assert project.name == "Renamed"
    shown = client.get(f"/api/v1/projects/{project.id}/tasks/{task.id}", headers=headers)
    assert shown.status_code == 200
    assert shown.json()["data"]["id"] == task.id


@pytest.mark.parametrize(
    "template", ["/api/v1/projects", "/api/v1/projects/{id}", "/api/v1/projects/{id}/tasks"]
)
def test_a_signed_out_device_is_not_authorized_and_sees_nothing(
    client, owner, project, make_access_token, template
):
    token = make_access_token(owner)
    token.revoke()
    path = template.format(id=project.id)

    assert answer_of(client.get(path)) == NOT_AUTHORIZED
    assert (
        answer_of(client.get(path, headers={"Authorization": f"Bearer {token.plaintext}"}))
        == NOT_AUTHORIZED
    )
