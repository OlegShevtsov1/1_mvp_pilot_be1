"""The label endpoints, a task's labels and a label's tasks, per role, checked against the
contract."""

from datetime import timedelta

import pytest

from apps.projects.models import Project
from apps.tasks.models import Label
from tests.contract import assert_matches_contract

LIST = "/api/v1/projects/{project_id}/labels"
ONE = "/api/v1/projects/{project_id}/labels/{id}"
LABEL_TASKS = "/api/v1/projects/{project_id}/labels/{id}/tasks"
TASK_LABELS = "/api/v1/projects/{project_id}/tasks/{id}/labels"
TASK_LABEL = "/api/v1/projects/{project_id}/tasks/{id}/labels/{label_id}"
TASK = "/api/v1/projects/{project_id}/tasks/{id}"
INVALID = {"Authorization": "Bearer invalid"}
NOT_FOUND = {"error": "Not Found"}
FORBIDDEN = {"error": "You are not authorized to perform this action"}
PARAMETER_MISSING = {"status": 422, "error": "Unprocessable Content"}
BLANK = "Name can't be blank"
TOO_LONG = "Name is too long (maximum is 30 characters)"
TAKEN = "Name has already been taken"
BAD_COLOR = "Color must be a hex color like #1a2b3c"
WRITERS = ["owner", "member"]
READERS = ["owner", "member", "viewer"]

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(make_project):
    return make_project()


@pytest.fixture
def make_label(project):
    def make(**fields):
        return Label.objects.create(project=project, **{"name": "backend"} | fields)

    return make


@pytest.fixture
def label(make_label):
    return make_label(color="#1a2b3c")


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
    def request(role, method, template, data=None, **ids):
        response = getattr(client, method)(
            template.format(**ids),
            data,
            content_type="application/json",
            headers=bearer(users[role]) if role else INVALID,
        )
        if method != "patch":  # PATCH is not in the contract; it behaves as PUT.
            assert_matches_contract(response, method, template)
        return response

    return request


@pytest.fixture
def stale(project):
    """Moves the project's `updated_at` an hour back and answers it."""

    def move():
        past = Project.objects.get(pk=project.pk).updated_at - timedelta(hours=1)
        Project.objects.filter(pk=project.pk).update(updated_at=past)
        return past

    return move


def touched(project, since):
    return Project.objects.get(pk=project.pk).updated_at > since


def label_json(label):
    label.refresh_from_db()
    return {
        "id": label.id,
        "name": label.name,
        "color": label.color,
        "created_at": label.created_at.isoformat(),
        "updated_at": label.updated_at.isoformat(),
    }


def of(label):
    return {"project_id": label.project_id, "id": label.id}


def on(task, **more):
    return {"project_id": task.project_id, "id": task.id, **more}


@pytest.mark.parametrize(
    ("method", "template", "data"),
    [
        ("get", LIST, None),
        ("post", LIST, {"label": {"name": "x"}}),
        ("get", ONE, None),
        ("put", ONE, {"label": {"name": "x"}}),
        ("delete", ONE, None),
        ("get", LABEL_TASKS, None),
        ("get", TASK_LABELS, None),
        ("post", TASK_LABELS, {"label": {"label_id": 1}}),
        ("delete", TASK_LABEL, None),
    ],
)
def test_answers_not_authorized_to_an_invalid_bearer(send, label, task, method, template, data):
    response = send(None, method, template, data, project_id=task.project_id, id=1, label_id=1)

    assert (response.status_code, response.json()) == (401, {"error": "Not Authorized"})


class TestList:
    @pytest.mark.parametrize("role", READERS)
    def test_lists_the_labels_in_id_order(self, send, project, make_label, role):
        first, second = make_label(name="b"), make_label(name="a")

        response = send(role, "get", LIST, project_id=project.id)

        assert response.status_code == 200
        assert response.json() == {"data": [label_json(first), label_json(second)]}

    def test_renders_the_label_json_keys_in_order(self, send, project, label):
        data = send("owner", "get", LIST, project_id=project.id).json()["data"][0]

        assert list(data) == ["id", "name", "color", "created_at", "updated_at"]

    def test_lists_only_the_projects_labels(self, send, project, label, make_project):
        Label.objects.create(project=make_project(user=project.user), name="other")

        response = send("owner", "get", LIST, project_id=project.id)

        assert [each["id"] for each in response.json()["data"]] == [label.id]

    def test_answers_not_found_to_a_stranger(self, send, project, label):
        response = send("stranger", "get", LIST, project_id=project.id)

        assert (response.status_code, response.json()) == (404, NOT_FOUND)


class TestCreate:
    @pytest.mark.parametrize("role", WRITERS)
    def test_creates_a_label(self, send, project, role):
        body = {"label": {"name": "frontend", "color": "#A1b2C3"}}

        response = send(role, "post", LIST, body, project_id=project.id)

        assert response.status_code == 201
        label = project.labels.get()
        assert (label.name, label.color) == ("frontend", "#A1b2C3")
        assert response.json() == {"data": label_json(label)}

    def test_defaults_the_color(self, send, project):
        response = send("owner", "post", LIST, {"label": {"name": "x"}}, project_id=project.id)

        assert response.json()["data"]["color"] == "#808080"

    def test_defaults_a_null_color(self, send, project):
        body = {"label": {"name": "x", "color": None}}

        response = send("owner", "post", LIST, body, project_id=project.id)

        assert response.json()["data"]["color"] == "#808080"

    def test_reads_an_unwrapped_body_as_the_label(self, send, project):
        response = send("owner", "post", LIST, {"name": "bare"}, project_id=project.id)

        assert response.status_code == 201
        assert response.json()["data"]["name"] == "bare"

    def test_touches_the_project(self, send, project, stale):
        since = stale()

        send("owner", "post", LIST, {"label": {"name": "x"}}, project_id=project.id)

        assert touched(project, since)

    @pytest.mark.parametrize(
        ("fields", "errors"),
        [
            ({"name": ""}, [BLANK]),
            ({"name": "   "}, [BLANK]),
            ({"color": "#123456"}, [BLANK]),
            ({"name": "x" * 31}, [TOO_LONG]),
            ({"name": "backend"}, [TAKEN]),
            ({"name": "x", "color": "red"}, [BAD_COLOR]),
            ({"name": "x", "color": "#12345"}, [BAD_COLOR]),
            ({"name": "x", "color": "#1234567"}, [BAD_COLOR]),
            ({"name": "x", "color": "#12345g"}, [BAD_COLOR]),
            ({"name": "x", "color": "#123456\n"}, [BAD_COLOR]),
            ({"name": "x", "color": ""}, [BAD_COLOR]),
            ({"name": "backend", "color": "blue"}, [TAKEN, BAD_COLOR]),
            ({"name": "", "color": "blue"}, [BLANK, BAD_COLOR]),
        ],
    )
    def test_refuses_an_invalid_label(self, send, project, label, fields, errors):
        response = send("owner", "post", LIST, {"label": fields}, project_id=project.id)

        assert (response.status_code, response.json()) == (422, {"errors": errors})
        assert project.labels.count() == 1

    def test_accepts_a_name_of_30_characters(self, send, project):
        body = {"label": {"name": "x" * 30}}

        assert send("owner", "post", LIST, body, project_id=project.id).status_code == 201

    def test_accepts_a_name_taken_in_another_project(self, send, project, make_project):
        Label.objects.create(project=make_project(), name="shared")

        response = send("owner", "post", LIST, {"label": {"name": "shared"}}, project_id=project.id)

        assert response.status_code == 201

    @pytest.mark.parametrize("body", [{"label": {}}, {"label": None}, []])
    def test_refuses_a_body_without_a_label(self, send, project, body):
        response = send("owner", "post", LIST, body, project_id=project.id)

        assert (response.status_code, response.json()) == (422, PARAMETER_MISSING)

    def test_is_forbidden_to_a_viewer(self, send, project):
        response = send("viewer", "post", LIST, {"label": {"name": "x"}}, project_id=project.id)

        assert (response.status_code, response.json()) == (403, FORBIDDEN)
        assert not project.labels.exists()

    def test_answers_not_found_to_a_stranger(self, send, project):
        response = send("stranger", "post", LIST, {"label": {"name": "x"}}, project_id=project.id)

        assert (response.status_code, response.json()) == (404, NOT_FOUND)
        assert not project.labels.exists()


class TestShow:
    @pytest.mark.parametrize("role", READERS)
    def test_shows_the_label(self, send, label, role):
        response = send(role, "get", ONE, **of(label))

        assert (response.status_code, response.json()) == (200, {"data": label_json(label)})

    def test_answers_not_found_to_a_stranger(self, send, label):
        response = send("stranger", "get", ONE, **of(label))

        assert (response.status_code, response.json()) == (404, NOT_FOUND)

    def test_answers_not_found_for_a_label_of_another_project(self, send, project, make_project):
        other = Label.objects.create(project=make_project(user=project.user), name="other")

        response = send("owner", "get", ONE, project_id=project.id, id=other.id)

        assert (response.status_code, response.json()) == (404, NOT_FOUND)

    @pytest.mark.parametrize("raw", ["999999", "abc"])
    def test_answers_not_found_for_a_missing_label(self, send, project, raw):
        response = send("owner", "get", ONE, project_id=project.id, id=raw)

        assert (response.status_code, response.json()) == (404, NOT_FOUND)


class TestUpdate:
    @pytest.mark.parametrize("role", WRITERS)
    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_updates_the_label(self, send, label, role, method):
        body = {"label": {"name": "renamed", "color": "#000000"}}

        response = send(role, method, ONE, body, **of(label))

        assert response.status_code == 200
        label.refresh_from_db()
        assert (label.name, label.color) == ("renamed", "#000000")
        assert response.json() == {"data": label_json(label)}

    def test_keeps_what_the_body_leaves_out(self, send, label):
        response = send("owner", "put", ONE, {"label": {"name": "renamed"}}, **of(label))

        assert response.json()["data"]["color"] == "#1a2b3c"

    def test_keeps_its_own_name(self, send, label):
        response = send("owner", "put", ONE, {"label": {"name": "backend"}}, **of(label))

        assert response.status_code == 200

    @pytest.mark.parametrize(
        ("fields", "errors"),
        [
            ({"name": ""}, [BLANK]),
            ({"name": "x" * 31}, [TOO_LONG]),
            ({"name": "taken"}, [TAKEN]),
            ({"color": "#zzzzzz"}, [BAD_COLOR]),
            ({"color": None}, [BAD_COLOR]),
        ],
    )
    def test_refuses_an_invalid_label(self, send, label, make_label, fields, errors):
        make_label(name="taken")

        response = send("owner", "put", ONE, {"label": fields}, **of(label))

        assert (response.status_code, response.json()) == (422, {"errors": errors})
        label.refresh_from_db()
        assert (label.name, label.color) == ("backend", "#1a2b3c")

    def test_touches_the_project(self, send, project, label, stale):
        since = stale()

        send("owner", "put", ONE, {"label": {"name": "renamed"}}, **of(label))

        assert touched(project, since)

    def test_is_forbidden_to_a_viewer(self, send, label):
        response = send("viewer", "put", ONE, {"label": {"name": "renamed"}}, **of(label))

        assert (response.status_code, response.json()) == (403, FORBIDDEN)
        label.refresh_from_db()
        assert label.name == "backend"

    def test_answers_not_found_to_a_stranger(self, send, label):
        response = send("stranger", "put", ONE, {"label": {"name": "renamed"}}, **of(label))

        assert (response.status_code, response.json()) == (404, NOT_FOUND)


class TestDelete:
    @pytest.mark.parametrize("role", WRITERS)
    def test_deletes_the_label(self, send, label, role):
        response = send(role, "delete", ONE, **of(label))

        assert (response.status_code, response.content) == (204, b"")
        assert not Label.objects.filter(pk=label.id).exists()

    def test_detaches_it_from_its_tasks_and_keeps_them(self, send, project, label, task):
        task.labels.add(label)

        send("owner", "delete", ONE, **of(label))

        assert not task.labels.exists()
        assert not Label.tasks.through.objects.filter(label_id=label.id).exists()
        assert project.tasks.filter(pk=task.id).exists()

    def test_touches_the_project(self, send, project, label, stale):
        since = stale()

        send("owner", "delete", ONE, **of(label))

        assert touched(project, since)

    def test_is_forbidden_to_a_viewer(self, send, label):
        response = send("viewer", "delete", ONE, **of(label))

        assert (response.status_code, response.json()) == (403, FORBIDDEN)
        assert Label.objects.filter(pk=label.id).exists()

    def test_answers_not_found_to_a_stranger(self, send, label):
        response = send("stranger", "delete", ONE, **of(label))

        assert (response.status_code, response.json()) == (404, NOT_FOUND)
        assert Label.objects.filter(pk=label.id).exists()

    def test_deleting_a_project_deletes_its_labels(self, send, project, label):
        response = send("owner", "delete", "/api/v1/projects/{id}", id=project.id)

        assert response.status_code == 204
        assert not Label.objects.filter(pk=label.id).exists()


class TestLabelTasks:
    @pytest.mark.parametrize("role", READERS)
    def test_lists_the_tasks_carrying_the_label_in_id_order(
        self, send, project, label, make_task, make_label, role
    ):
        first, unlabelled, second = (make_task(project=project) for _ in range(3))
        second.labels.add(label)
        first.labels.add(label)
        unlabelled.labels.add(make_label(name="other"))

        response = send(role, "get", LABEL_TASKS, **of(label))

        assert response.status_code == 200
        data = response.json()["data"]
        assert [each["id"] for each in data] == [first.id, second.id]
        assert data[0] == send(role, "get", TASK, **on(first)).json()["data"]

    def test_lists_nothing_for_an_unused_label(self, send, label, task):
        assert send("owner", "get", LABEL_TASKS, **of(label)).json() == {"data": []}

    def test_answers_not_found_to_a_stranger(self, send, label):
        response = send("stranger", "get", LABEL_TASKS, **of(label))

        assert (response.status_code, response.json()) == (404, NOT_FOUND)

    def test_answers_not_found_for_a_missing_label(self, send, project):
        response = send("owner", "get", LABEL_TASKS, project_id=project.id, id=999999)

        assert (response.status_code, response.json()) == (404, NOT_FOUND)


class TestTaskLabels:
    @pytest.mark.parametrize("role", READERS)
    def test_lists_the_tasks_labels_in_id_order(self, send, task, label, make_label, role):
        other = make_label(name="other")
        make_label(name="unused")
        task.labels.add(other, label)

        response = send(role, "get", TASK_LABELS, **on(task))

        assert response.status_code == 200
        assert response.json() == {"data": [label_json(label), label_json(other)]}

    def test_answers_not_found_to_a_stranger(self, send, task):
        response = send("stranger", "get", TASK_LABELS, **on(task))

        assert (response.status_code, response.json()) == (404, NOT_FOUND)


class TestAttach:
    @pytest.mark.parametrize("role", WRITERS)
    def test_attaches_the_label(self, send, task, label, role):
        response = send(role, "post", TASK_LABELS, {"label": {"label_id": label.id}}, **on(task))

        assert (response.status_code, response.json()) == (201, {"data": label_json(label)})
        assert list(task.labels.all()) == [label]

    def test_reads_an_unwrapped_body(self, send, task, label):
        response = send("owner", "post", TASK_LABELS, {"label_id": label.id}, **on(task))

        assert response.status_code == 201

    def test_touches_the_project(self, send, project, task, label, stale):
        since = stale()

        send("owner", "post", TASK_LABELS, {"label": {"label_id": label.id}}, **on(task))

        assert touched(project, since)

    def test_refuses_a_label_of_another_project(self, send, project, task, make_project):
        other = Label.objects.create(project=make_project(user=project.user), name="other")

        response = send("owner", "post", TASK_LABELS, {"label": {"label_id": other.id}}, **on(task))

        assert response.status_code == 422
        assert response.json() == {"errors": ["Label must belong to the same project"]}
        assert not task.labels.exists()

    @pytest.mark.parametrize("label_id", [999999, "abc", None])
    def test_refuses_an_unknown_label(self, send, task, label_id):
        response = send("owner", "post", TASK_LABELS, {"label": {"label_id": label_id}}, **on(task))

        assert response.status_code == 422
        assert response.json() == {"errors": ["Label must belong to the same project"]}

    def test_refuses_an_attached_label(self, send, task, label):
        task.labels.add(label)

        response = send("owner", "post", TASK_LABELS, {"label": {"label_id": label.id}}, **on(task))

        assert (response.status_code, response.json()) == (
            422,
            {"errors": ["Label already attached"]},
        )

    def test_is_forbidden_to_a_viewer(self, send, task, label):
        response = send(
            "viewer", "post", TASK_LABELS, {"label": {"label_id": label.id}}, **on(task)
        )

        assert (response.status_code, response.json()) == (403, FORBIDDEN)
        assert not task.labels.exists()

    def test_answers_not_found_to_a_stranger(self, send, task, label):
        body = {"label": {"label_id": label.id}}

        response = send("stranger", "post", TASK_LABELS, body, **on(task))

        assert (response.status_code, response.json()) == (404, NOT_FOUND)
        assert not task.labels.exists()


class TestDetach:
    @pytest.mark.parametrize("role", WRITERS)
    def test_detaches_the_label(self, send, task, label, role):
        task.labels.add(label)

        response = send(role, "delete", TASK_LABEL, **on(task, label_id=label.id))

        assert (response.status_code, response.content) == (204, b"")
        assert not task.labels.exists()
        assert Label.objects.filter(pk=label.id).exists()

    def test_touches_the_project(self, send, project, task, label, stale):
        task.labels.add(label)
        since = stale()

        send("owner", "delete", TASK_LABEL, **on(task, label_id=label.id))

        assert touched(project, since)

    def test_answers_not_found_for_a_label_not_attached(self, send, task, label):
        response = send("owner", "delete", TASK_LABEL, **on(task, label_id=label.id))

        assert (response.status_code, response.json()) == (404, NOT_FOUND)

    def test_is_forbidden_to_a_viewer(self, send, task, label):
        task.labels.add(label)

        response = send("viewer", "delete", TASK_LABEL, **on(task, label_id=label.id))

        assert (response.status_code, response.json()) == (403, FORBIDDEN)
        assert task.labels.exists()

    def test_answers_not_found_to_a_stranger(self, send, task, label):
        task.labels.add(label)

        response = send("stranger", "delete", TASK_LABEL, **on(task, label_id=label.id))

        assert (response.status_code, response.json()) == (404, NOT_FOUND)
        assert task.labels.exists()


def test_deleting_a_task_detaches_its_labels(send, task, label):
    task.labels.add(label)

    send("owner", "delete", TASK, **on(task))

    assert not Label.tasks.through.objects.filter(label_id=label.id).exists()
    assert Label.objects.filter(pk=label.id).exists()


def test_task_and_project_json_stay_without_labels_and_dependencies(
    send, project, task, label, make_task
):
    task.labels.add(label)
    task.blocked_by.add(make_task(project=project))

    data = send("owner", "get", TASK, **on(task)).json()["data"]

    assert list(data) == ["id", "name", "description", "status", "project"]
    assert list(data["project"]) == ["id", "name", "description", "user", "tasks"]
    assert list(data["project"]["tasks"][0]) == ["id", "name", "description", "status"]
