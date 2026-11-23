"""Dependency services: cycle detection and the project touch."""

from datetime import timedelta

import pytest

from apps.tasks import dependencies

pytestmark = pytest.mark.django_db

CYCLE = ["Dependency would create a cycle"]


@pytest.fixture
def project(make_project):
    return make_project()


@pytest.fixture
def chain(project, make_task):
    """`count` tasks, each blocked by the one after it: chain[0] ← chain[1] ← …"""

    def make(count):
        tasks = [make_task(project=project, name=f"Task {n}") for n in range(count)]
        for waiting, blocker in zip(tasks, tasks[1:], strict=False):
            waiting.blocked_by.add(blocker)
        return tasks

    return make


def test_refuses_a_direct_cycle(chain):
    first, second = chain(2)

    assert dependencies.add(second, first).errors == CYCLE


@pytest.mark.parametrize("length", [3, 4, 5])
def test_refuses_an_indirect_cycle(chain, length):
    tasks = chain(length)

    assert dependencies.add(tasks[-1], tasks[0]).errors == CYCLE
    assert not tasks[-1].blocked_by.exists()


def test_refuses_a_cycle_through_a_branch(project, chain, make_task):
    tasks = chain(3)
    side = make_task(project=project)
    tasks[1].blocked_by.add(side)

    assert dependencies.add(side, tasks[0]).errors == CYCLE


def test_allows_a_diamond(project, make_task):
    top, left, right, bottom = (make_task(project=project) for _ in range(4))
    top.blocked_by.add(left, right)
    left.blocked_by.add(bottom)

    assert dependencies.add(right, bottom).errors == []


def test_walks_a_long_chain_in_a_bounded_number_of_queries(chain, django_assert_max_num_queries):
    tasks = chain(200)

    # The project lock (with its transaction and savepoint statements), the existing and graph
    # checks, then the insert and the project touch: a fixed count, whatever the chain's length.
    with django_assert_max_num_queries(8):
        assert dependencies.add(tasks[-1], tasks[0]).errors == CYCLE
    with django_assert_max_num_queries(12):
        assert dependencies.add(tasks[0], tasks[-1]).errors == []


def test_ignores_the_graph_of_other_projects(project, make_task, make_project):
    task, blocker = make_task(project=project), make_task(project=project)
    other = make_project()
    a, b = make_task(project=other), make_task(project=other)
    a.blocked_by.add(b)

    assert dependencies.blockers_of(project) == {}
    assert dependencies.add(task, blocker).errors == []
    assert dependencies.blockers_of(project) == {task.id: {blocker.id}}


class TestTouch:
    @pytest.fixture
    def stale(self, project):
        """The project's `updated_at` moved an hour back."""
        past = project.updated_at - timedelta(hours=1)
        type(project).objects.filter(pk=project.pk).update(updated_at=past)
        return past

    def test_adding_touches_the_project(self, project, make_task, stale):
        task, blocker = make_task(project=project), make_task(project=project)
        type(project).objects.filter(pk=project.pk).update(updated_at=stale)

        dependencies.add(task, blocker)

        project.refresh_from_db()
        assert project.updated_at > stale

    def test_removing_touches_the_project(self, project, make_task, stale):
        task, blocker = make_task(project=project), make_task(project=project)
        task.blocked_by.add(blocker)
        type(project).objects.filter(pk=project.pk).update(updated_at=stale)

        dependencies.remove(task, blocker)

        project.refresh_from_db()
        assert project.updated_at > stale

    def test_a_refused_dependency_leaves_the_project(self, project, make_task, stale):
        task = make_task(project=project)
        type(project).objects.filter(pk=project.pk).update(updated_at=stale)

        dependencies.add(task, task)

        project.refresh_from_db()
        assert project.updated_at == stale


class TestProjectLock:
    """The dependency checks and the write that follows them run under the project row lock, so
    concurrent requests cannot both pass a check (a no-op on SQLite; asserted on the calls)."""

    @pytest.fixture
    def locks(self, monkeypatch):
        calls = []
        lock = dependencies.lock_project

        def spy(project_id):
            calls.append(project_id)
            return lock(project_id)

        monkeypatch.setattr(dependencies, "lock_project", spy)
        return calls

    def test_adding_a_dependency_takes_the_lock_before_checking(self, project, make_task, locks):
        task, blocker = make_task(project=project), make_task(project=project)

        assert dependencies.add(task, blocker).errors == []
        assert locks == [project.id]

    def test_completing_a_task_takes_the_lock(self, project, make_task, locks):
        from apps.tasks import services

        task = make_task(project=project)
        services.update(task, {"status": "completed"})

        assert locks == [project.id]

    def test_other_updates_take_no_lock(self, project, make_task, locks):
        from apps.tasks import services

        task = make_task(project=project)
        services.update(task, {"name": "Renamed task"})

        assert locks == []
