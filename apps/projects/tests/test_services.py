"""Project services: the cached list and the writes."""

from datetime import timedelta

import pytest
from django.core.cache import cache

from apps.projects import services
from apps.projects.models import Project

VALID = {"name": "New Project", "description": "This is a project description that's long enough."}
INVALID = {"name": "ab", "description": "Too short"}

pytestmark = pytest.mark.django_db


def assert_owner_and_tasks_loaded(project, django_assert_num_queries):
    with django_assert_num_queries(0):
        assert project.user.email
        list(project.tasks.all())


class TestCreate:
    def test_creates_the_users_project_with_its_owner_and_tasks_loaded(
        self, user, django_assert_num_queries
    ):
        result = services.create(user, VALID)

        assert result.errors == []
        assert Project.objects.count() == 1
        assert result.project.user == user
        assert_owner_and_tasks_loaded(result.project, django_assert_num_queries)

    def test_refuses_invalid_params(self, user):
        result = services.create(user, INVALID)

        assert result.errors
        assert Project.objects.count() == 0


class TestUpdate:
    def test_updates_the_project_with_its_owner_and_tasks_loaded(
        self, user, make_project, django_assert_num_queries
    ):
        project = make_project(user=user)

        result = services.update(project, VALID)

        assert result.errors == []
        project.refresh_from_db()
        assert (project.name, project.description) == (VALID["name"], VALID["description"])
        assert_owner_and_tasks_loaded(result.project, django_assert_num_queries)

    def test_leaves_the_project_on_invalid_params(self, user, make_project):
        project = make_project(user=user)

        result = services.update(project, INVALID)

        assert result.errors
        project.refresh_from_db()
        assert project.name == "Sample Project"


def test_show_returns_the_project_with_its_owner_and_tasks_loaded(
    user, make_project, django_assert_num_queries
):
    project = make_project(user=user)

    shown = services.show(project)

    assert shown == project
    assert_owner_and_tasks_loaded(shown, django_assert_num_queries)


class TestDelete:
    def test_deletes_a_project_without_tasks(self, user, make_project):
        project = make_project(user=user)

        result = services.delete(project)

        assert result.errors == []
        assert Project.objects.count() == 0

    def test_keeps_a_project_with_tasks(self, user, make_project, make_task):
        project = make_project(user=user)
        make_task(project=project)

        result = services.delete(project)

        assert result.errors == ["Cannot delete record because dependent tasks exist"]
        assert Project.objects.count() == 1


class TestIndex:
    @pytest.fixture
    def projects(self, user, make_user, make_project):
        other = make_user()
        for _ in range(2):
            make_project(user=other)
        return [make_project(user=user) for _ in range(3)]

    def test_returns_the_users_projects_with_their_owner_and_tasks_loaded(
        self, user, projects, django_assert_num_queries
    ):
        listed = services.index(user)

        assert listed == projects
        assert_owner_and_tasks_loaded(listed[0], django_assert_num_queries)

    @pytest.mark.parametrize("status", ["completed", "in_progress", "not_started"])
    def test_filters_by_task_status(
        self, user, make_project, make_task, status, django_assert_num_queries
    ):
        by_status = {}
        for each in ("completed", "in_progress", "not_started"):
            by_status[each] = make_project(user=user)
            make_task(project=by_status[each], status=each)

        listed = services.index(user, status)

        assert listed == [by_status[status]]
        assert_owner_and_tasks_loaded(listed[0], django_assert_num_queries)

    def test_returns_nothing_for_an_unknown_status(self, user, make_project, make_task):
        make_task(project=make_project(user=user))

        assert services.index(user, "non_existent_status") == []


class TestCache:
    @pytest.fixture(autouse=True)
    def projects(self, user, make_project):
        return [make_project(user=user) for _ in range(3)]

    def test_stores_the_list_for_15_minutes_under_the_cache_key(self, user, monkeypatch):
        calls = []
        get_or_set = cache.get_or_set

        def spy(key, default, timeout):
            calls.append((key, timeout))
            return get_or_set(key, default, timeout)

        monkeypatch.setattr(cache, "get_or_set", spy)

        services.index(user)

        assert calls == [(services.cache_key(user), 15 * 60)]
        assert cache.get(services.cache_key(user)) == user.projects.order_by("id")[::1]

    def test_builds_the_key_from_the_user_their_projects_and_the_filter(self, user):
        latest = user.projects.order_by("-updated_at")[0].updated_at

        assert services.cache_key(user) == (
            f"projects:{user.id}:stats:count=3:updated={latest.isoformat()}:v1"
        )
        assert services.cache_key(user, "completed") == (
            f"projects:{user.id}:stats:count=3:updated={latest.isoformat()}:filter:completed:v1"
        )

    def test_names_no_update_without_projects(self, make_user):
        other = make_user()

        assert services.cache_key(other) == f"projects:{other.id}:stats:count=0:updated=none:v1"

    def test_returns_cached_results_on_subsequent_calls(self, user, monkeypatch):
        fetched = []
        fetch_projects = services.fetch_projects

        def spy(*args):
            fetched.append(args)
            return fetch_projects(*args)

        monkeypatch.setattr(services, "fetch_projects", spy)

        first = services.index(user)
        second = services.index(user)

        assert len(fetched) == 1
        assert second == first

    def test_changes_the_key_when_a_project_is_updated(self, user, projects):
        before = services.cache_key(user)
        Project.objects.filter(pk=projects[0].pk).update(
            updated_at=projects[0].updated_at + timedelta(days=1)
        )

        assert services.cache_key(user) != before

    def test_changes_the_key_when_a_project_is_added(self, user, make_project):
        before = services.cache_key(user)
        services.index(user)

        make_project(user=user)

        assert services.cache_key(user) != before

    def test_changes_the_key_when_a_project_is_removed(self, user, projects):
        before = services.cache_key(user)
        services.index(user)

        projects[0].delete()

        assert services.cache_key(user) != before
