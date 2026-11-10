"""The projects endpoints, checked against the contract."""

from datetime import timedelta

import pytest

from apps.projects.models import Project
from apps.tasks.models import Task
from tests.contract import assert_matches_contract

LIST = "/api/v1/projects"
MEMBER = "/api/v1/projects/{id}"
INVALID = {"Authorization": "Bearer invalid"}
NOT_FOUND = {"error": "Not Found"}

pytestmark = pytest.mark.django_db


@pytest.fixture
def headers(user, bearer):
    return bearer(user)


@pytest.fixture
def existing_project(user, make_project):
    return make_project(user=user)


def call(client, method, path, template, headers, data=None):
    response = getattr(client, method)(path, data, content_type="application/json", headers=headers)
    assert_matches_contract(response, method, template)
    return response


def member(project_id):
    return f"/api/v1/projects/{project_id}"


def arabic_indic(number):
    return str(number).translate(
        str.maketrans("0123456789", "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669")
    )


@pytest.mark.parametrize(
    ("method", "template", "data"),
    [
        ("get", LIST, None),
        ("post", LIST, {"project": {"name": "Test Project", "description": "x" * 30}}),
        ("get", MEMBER, None),
        ("put", MEMBER, {"project": {"name": "Updated Project"}}),
        ("delete", MEMBER, None),
    ],
)
def test_answers_not_authorized_to_an_invalid_bearer(
    client, existing_project, method, template, data
):
    path = template.format(id=existing_project.id)

    response = call(client, method, path, template, INVALID, data)

    assert response.status_code == 401
    assert response.json() == {"error": "Not Authorized"}


class TestList:
    @pytest.fixture
    def projects(self, user, make_project, make_task):
        completed = make_project(user=user)
        not_started = make_project(user=user)
        make_task(project=completed, status="completed")
        make_task(project=not_started)
        make_task(status="completed")
        return completed, not_started

    def test_lists_the_callers_projects_with_their_tasks(self, client, headers, projects):
        completed, not_started = projects

        response = call(client, "get", LIST, LIST, headers)

        assert response.status_code == 200
        data = response.json()["data"]
        assert [project["id"] for project in data] == [completed.id, not_started.id]
        assert {
            project["id"]: [task["status"] for task in project["tasks"]] for project in data
        } == {
            completed.id: ["completed"],
            not_started.id: ["not_started"],
        }

    def test_keeps_the_projects_having_a_task_of_the_status(self, client, headers, projects):
        completed, _ = projects

        response = call(client, "get", f"{LIST}?task_status=completed", LIST, headers)

        assert response.status_code == 200
        assert [project["id"] for project in response.json()["data"]] == [completed.id]

    def test_renders_only_the_tasks_of_the_status_in_a_filtered_project(
        self, client, user, headers, make_project, make_task
    ):
        project = make_project(user=user)
        done = make_task(project=project, status="completed")
        make_task(project=project)

        response = call(client, "get", f"{LIST}?task_status=completed", LIST, headers)

        assert [task["id"] for task in response.json()["data"][0]["tasks"]] == [done.id]

    @pytest.mark.parametrize("status", ["bogus", "%1C"])
    def test_lists_nothing_for_an_unknown_status(self, client, headers, projects, status):
        response = call(client, "get", f"{LIST}?task_status={status}", LIST, headers)

        assert response.json() == {"data": []}

    def test_renders_be_s_project_json(self, client, user, headers, make_project, make_task):
        project = make_project(user=user)
        task = make_task(project=project, status="completed")

        response = call(client, "get", LIST, LIST, headers)

        project_json = response.json()["data"][0]
        assert project_json == {
            "id": project.id,
            "name": "Sample Project",
            "description": project.description,
            "user": {"id": user.id, "email": user.email},
            "tasks": [
                {
                    "id": task.id,
                    "name": "Sample Task",
                    "description": "This is a sample task description",
                    "status": "completed",
                }
            ],
        }
        assert list(project_json) == ["id", "name", "description", "user", "tasks"]
        assert list(project_json["tasks"][0]) == ["id", "name", "description", "status"]


class TestCreate:
    def test_creates_a_project_owned_by_the_caller(self, client, user, headers):
        body = {"project": {"name": "Test Project", "description": "This is a test description"}}

        response = call(client, "post", LIST, LIST, headers, body)

        assert response.status_code == 201
        assert response.json()["data"]["name"] == "Test Project"
        assert response.json()["data"]["tasks"] == []
        assert Project.objects.get(pk=response.json()["data"]["id"]).user_id == user.id

    def test_ignores_an_owner_in_the_params(self, client, user, make_user, headers):
        body = {"project": {"name": "Hello World", "description": "x" * 25, "user_id": 0}}
        make_user()

        response = call(client, "post", LIST, LIST, headers, body)

        assert response.status_code == 201
        assert response.json()["data"]["user"] == {"id": user.id, "email": user.email}

    def test_reads_an_unwrapped_json_body_as_the_project(self, client, headers):
        body = {"name": "Hello World", "description": "x" * 25}

        response = call(client, "post", LIST, LIST, headers, body)

        assert response.status_code == 201
        assert response.json()["data"]["name"] == "Hello World"

    def test_takes_a_name_of_separator_characters_as_present(self, client, headers):
        body = {"project": {"name": "\x1c" * 5, "description": "x" * 25}}

        response = call(client, "post", LIST, LIST, headers, body)

        assert response.status_code == 201
        assert response.json()["data"]["name"] == "\x1c" * 5

    @pytest.mark.parametrize(
        ("project", "message"),
        [
            (
                {"name": "abcd", "description": "x" * 30},
                "Name is too short (minimum is 5 characters)",
            ),
            (
                {"name": "Test Project", "description": "x" * 121},
                "Description is too long (maximum is 120 characters)",
            ),
        ],
    )
    def test_refuses_an_invalid_project(self, client, headers, project, message):
        response = call(client, "post", LIST, LIST, headers, {"project": project})

        assert response.status_code == 422
        assert message in response.json()["errors"]
        assert Project.objects.count() == 0

    @pytest.mark.parametrize("body", [{"project": {}}, {"project": None}, {"foo": 1}, []])
    def test_refuses_a_body_without_a_project(self, client, headers, body):
        response = call(client, "post", LIST, LIST, headers, body)

        assert response.status_code == 422
        assert response.json() == {"status": 422, "error": "Unprocessable Content"}

    @pytest.mark.parametrize(
        ("project", "errors"),
        [
            (
                {"name": None},
                [
                    "Name can't be blank",
                    "Name is too short (minimum is 5 characters)",
                    "Description can't be blank",
                    "Description is too short (minimum is 20 characters)",
                ],
            ),
            (
                {"name": 12345, "description": True},
                ["Description is too short (minimum is 20 characters)"],
            ),
            (
                {"name": ["abcdef"], "description": "x" * 25},
                ["Name can't be blank", "Name is too short (minimum is 5 characters)"],
            ),
        ],
    )
    def test_reads_permitted_scalar_params_only(self, client, headers, project, errors):
        response = call(client, "post", LIST, LIST, headers, {"project": project})

        assert response.status_code == 422
        assert response.json() == {"errors": errors}


class TestShow:
    def test_shows_the_project(self, client, user, headers, existing_project):
        path = member(existing_project.id)

        response = call(client, "get", path, MEMBER, headers)

        assert response.status_code == 200
        assert response.json()["data"] == {
            "id": existing_project.id,
            "name": existing_project.name,
            "description": existing_project.description,
            "user": {"id": user.id, "email": user.email},
            "tasks": [],
        }

    def test_answers_not_found_for_a_missing_project(self, client, headers):
        response = call(client, "get", member(999999), MEMBER, headers)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    def test_answers_not_found_for_another_users_project(self, client, headers, make_project):
        response = call(client, "get", member(make_project().id), MEMBER, headers)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    @pytest.mark.parametrize("suffix", ["abc", ".json"])
    def test_reads_the_id_by_its_leading_digits(self, client, headers, existing_project, suffix):
        response = call(client, "get", f"{member(existing_project.id)}{suffix}", MEMBER, headers)

        assert response.status_code == 200
        assert response.json()["data"]["id"] == existing_project.id

    @pytest.mark.parametrize("raw", ["abc", "0", "-1", "99999999999999999999999"])
    def test_answers_not_found_for_an_id_naming_no_project(self, client, headers, raw):
        response = call(client, "get", member(raw), MEMBER, headers)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    def test_answers_not_found_for_an_id_in_non_ascii_digits(
        self, client, headers, existing_project
    ):
        response = call(client, "get", member(arabic_indic(existing_project.id)), MEMBER, headers)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND


class TestUpdate:
    def test_writes_nothing_when_nothing_changed(
        self, client, user, headers, existing_project, clock
    ):
        user.refresh_from_db()
        touched = existing_project.updated_at, user.updated_at
        clock.travel(timedelta(seconds=1))
        body = {"project": {"name": existing_project.name}}

        response = call(client, "put", member(existing_project.id), MEMBER, headers, body)

        assert response.status_code == 200
        existing_project.refresh_from_db()
        user.refresh_from_db()
        assert (existing_project.updated_at, user.updated_at) == touched

    def test_updates_the_project(self, client, headers, existing_project):
        body = {"project": {"name": "Updated Project"}}

        response = call(client, "put", member(existing_project.id), MEMBER, headers, body)

        assert response.status_code == 200
        assert response.json()["data"]["name"] == "Updated Project"
        existing_project.refresh_from_db()
        assert existing_project.name == "Updated Project"

    def test_answers_not_found_for_a_missing_project(self, client, headers):
        body = {"project": {"name": "Updated Project"}}

        response = call(client, "put", member(999999), MEMBER, headers, body)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    def test_refuses_a_name_longer_than_20_characters(self, client, headers, existing_project):
        body = {"project": {"name": "x" * 21}}

        response = call(client, "put", member(existing_project.id), MEMBER, headers, body)

        assert response.status_code == 422
        assert "Name is too long (maximum is 20 characters)" in response.json()["errors"]
        existing_project.refresh_from_db()
        assert existing_project.name != "x" * 21

    def test_patch_updates_like_put(self, client, headers, existing_project):
        response = client.patch(
            member(existing_project.id),
            {"project": {"name": "Patched"}},
            content_type="application/json",
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["data"]["name"] == "Patched"


class TestDelete:
    def test_deletes_the_project(self, client, headers, existing_project):
        response = call(client, "delete", member(existing_project.id), MEMBER, headers)

        assert response.status_code == 204
        assert response.content == b""
        assert not Project.objects.filter(pk=existing_project.id).exists()

    def test_answers_not_found_for_a_missing_project(self, client, headers):
        response = call(client, "delete", member(999999), MEMBER, headers)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    def test_keeps_a_project_that_still_has_tasks(
        self, client, headers, existing_project, make_task
    ):
        task = make_task(project=existing_project)

        response = call(client, "delete", member(existing_project.id), MEMBER, headers)

        assert response.status_code == 422
        assert response.json() == {"errors": ["Cannot delete record because dependent tasks exist"]}
        assert Project.objects.filter(pk=existing_project.id).exists()
        assert Task.objects.filter(pk=task.id).exists()
