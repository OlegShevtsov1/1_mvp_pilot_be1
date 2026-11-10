"""What GET /api/v1/projects costs in queries."""

import pytest
from django.core.cache import cache

from apps.projects import serializers
from apps.tasks import serializers as task_serializers

LIST = "/api/v1/projects"
# Bearer token lookup, list cache key, projects with their owner, their tasks.
LIST_QUERIES = 4

pytestmark = pytest.mark.django_db


@pytest.fixture
def headers(user, bearer):
    return bearer(user)


@pytest.fixture
def seed(user, make_project, make_task):
    def make(projects, tasks):
        for _ in range(projects):
            project = make_project(user=user)
            for _ in range(tasks):
                make_task(project=project)

    return make


def list_projects(client, headers):
    """A cache miss every time: the list cache is cleared first."""
    cache.clear()
    response = client.get(LIST, headers=headers)
    assert response.status_code == 200
    return response


def test_runs_the_same_number_of_queries_whatever_the_number_of_projects_and_tasks(
    client, headers, seed, django_assert_max_num_queries
):
    seed(projects=1, tasks=1)
    with django_assert_max_num_queries(LIST_QUERIES):
        list_projects(client, headers)

    seed(projects=4, tasks=5)
    with django_assert_max_num_queries(LIST_QUERIES):
        list_projects(client, headers)


def test_builds_one_json_per_project_none_per_task(client, headers, seed, monkeypatch):
    calls = {"projects": 0, "tasks": 0}

    def counted(name, original):
        def wrapper(record):
            calls[name] += 1
            return original(record)

        return wrapper

    monkeypatch.setattr(serializers, "project_json", counted("projects", serializers.project_json))
    monkeypatch.setattr(task_serializers, "task_json", counted("tasks", task_serializers.task_json))
    seed(projects=3, tasks=4)

    list_projects(client, headers)

    assert calls == {"projects": 3, "tasks": 0}


def test_renders_each_project_with_its_owner_and_its_tasks_and_nothing_else(
    client, user, headers, seed
):
    seed(projects=2, tasks=2)

    data = list_projects(client, headers).json()["data"]

    expected = [
        {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "user": {"id": user.id, "email": user.email},
            "tasks": [
                {
                    "id": task.id,
                    "name": task.name,
                    "description": task.description,
                    "status": task.status,
                }
                for task in project.tasks.order_by("id")
            ],
        }
        for project in user.projects.order_by("id")
    ]
    assert sorted(data, key=lambda project: project["id"]) == expected
