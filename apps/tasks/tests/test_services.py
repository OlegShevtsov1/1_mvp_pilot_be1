"""Task services: the cached list and the writes."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import DatabaseError

from apps.tasks import services
from apps.tasks.models import Task

VALID = {"name": "New Task", "description": "Task description", "status": "not_started"}
INVALID = {"name": "", "description": "", "status": None}

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(user, make_project):
    return make_project(user=user)


class TestCreate:
    def test_creates_a_task_of_the_project(self, project):
        result = services.create(project, VALID)

        assert result.errors == []
        assert Task.objects.count() == 1
        assert result.task.project == project

    def test_refuses_invalid_params(self, project):
        result = services.create(project, INVALID)

        assert result.errors
        assert Task.objects.count() == 0


class TestUpdate:
    @pytest.fixture
    def task(self, project, make_task):
        return make_task(
            project=project,
            name="Original Task",
            description="Original description",
            status="not_started",
        )

    def test_updates_the_task(self, task):
        params = {"name": "Updated Task", "description": "Updated description"}

        result = services.update(task, params | {"status": "in_progress"})

        assert result.errors == []
        task.refresh_from_db()
        assert (task.name, task.description, task.status) == (
            "Updated Task",
            "Updated description",
            "in_progress",
        )

    def test_leaves_the_task_on_invalid_params(self, task):
        result = services.update(task, INVALID)

        assert result.errors
        task.refresh_from_db()
        assert (task.name, task.status) == ("Original Task", "not_started")


def test_show_returns_the_task_with_its_project(project, make_task, django_assert_num_queries):
    task = make_task(project=project)

    shown = services.show(task)

    assert shown == task
    with django_assert_num_queries(0):
        assert shown.project == project
        assert shown.project.user.email
        list(shown.project.tasks.all())


class TestDelete:
    def test_deletes_the_task(self, project, make_task):
        task = make_task(project=project)

        result = services.delete(task)

        assert result.errors == []
        assert Task.objects.count() == 0

    def test_reports_a_failed_deletion(self, project, make_task, monkeypatch):
        task = make_task(project=project)

        def fail(self):
            raise DatabaseError("Task cannot be deleted")

        monkeypatch.setattr(Task, "delete", fail)

        result = services.delete(task)

        assert result.errors == ["Task cannot be deleted"]
        assert Task.objects.count() == 1


class TestIndex:
    @pytest.fixture(autouse=True)
    def tasks(self, project, make_task):
        return [make_task(project=project) for _ in range(3)]

    def test_returns_the_projects_tasks_with_their_project(
        self, project, tasks, django_assert_num_queries
    ):
        listed = services.index(project)

        assert listed == tasks
        with django_assert_num_queries(0):
            for task in listed:
                assert task.project == project
                assert task.project.user.email
                list(task.project.tasks.all())

    def test_stores_the_list_for_15_minutes_under_the_cache_key(self, project, monkeypatch):
        calls = []
        get_or_set = cache.get_or_set

        def spy(key, default, timeout):
            calls.append((key, timeout))
            return get_or_set(key, default, timeout)

        monkeypatch.setattr(cache, "get_or_set", spy)

        services.index(project)

        assert calls == [(services.cache_key(project), 15 * 60)]
        assert cache.get(services.cache_key(project)) == project.tasks.order_by("id")[::1]

    def test_builds_the_key_from_the_project_and_its_tasks(self, project):
        latest = project.tasks.order_by("-updated_at")[0].updated_at

        assert services.cache_key(project) == (
            f"tasks:{project.id}:stats:count=3:updated={latest.isoformat()}:v1"
        )

    def test_returns_cached_results_on_subsequent_calls(self, project, monkeypatch):
        fetched = []
        fetch_tasks = services.fetch_tasks

        def spy(*args):
            fetched.append(args)
            return fetch_tasks(*args)

        monkeypatch.setattr(services, "fetch_tasks", spy)

        first = services.index(project)
        second = services.index(project)

        assert len(fetched) == 1
        assert second == first

    def test_changes_the_key_when_a_task_is_updated(self, project, tasks):
        before = services.cache_key(project)
        Task.objects.filter(pk=tasks[0].pk).update(
            updated_at=tasks[0].updated_at + timedelta(days=1)
        )

        assert services.cache_key(project) != before

    def test_changes_the_key_when_a_task_is_added(self, project, make_task):
        before = services.cache_key(project)
        services.index(project)

        make_task(project=project)

        assert services.cache_key(project) != before

    def test_changes_the_key_when_a_task_is_removed(self, project, tasks):
        before = services.cache_key(project)
        services.index(project)

        tasks[0].delete()

        assert services.cache_key(project) != before
