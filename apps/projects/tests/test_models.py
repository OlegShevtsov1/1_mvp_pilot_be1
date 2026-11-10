"""Project model validations, counters and the deletion rule."""

from datetime import timedelta

import pytest
from django.db.models import CASCADE, PROTECT, ProtectedError

from apps.projects.models import Project
from apps.tasks.models import Task

VALID_DESCRIPTION = "This is a sample project description that meets the minimum length requirement"


def build(**fields):
    return Project(**{"name": "Sample Project", "description": VALID_DESCRIPTION} | fields)


def test_belongs_to_a_user_and_goes_with_them():
    assert Project._meta.get_field("user").remote_field.on_delete is CASCADE


def test_restricts_deleting_a_project_with_tasks():
    assert Task._meta.get_field("project").remote_field.on_delete is PROTECT


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"name": None}, "Name can't be blank"),
        ({"name": "   "}, "Name can't be blank"),
        ({"name": "\u3000\xa0\t\u2028"}, "Name can't be blank"),
        ({"description": None}, "Description can't be blank"),
        ({"name": "a" * 4}, "Name is too short (minimum is 5 characters)"),
        ({"name": "a" * 21}, "Name is too long (maximum is 20 characters)"),
        ({"description": "a" * 19}, "Description is too short (minimum is 20 characters)"),
        ({"description": "a" * 121}, "Description is too long (maximum is 120 characters)"),
    ],
)
def test_is_invalid(fields, message):
    assert message in build(**fields).full_messages()


@pytest.mark.parametrize(
    "fields",
    [{"name": "a" * 5}, {"name": "a" * 20}, {"description": "a" * 20}, {"description": "a" * 120}],
)
def test_is_valid_at_the_length_limits(fields):
    assert build(**fields).full_messages() == []


@pytest.mark.django_db
class TestCounters:
    def test_keeps_track_of_the_tasks_count(self, make_project, make_task):
        project = make_project()
        tasks = [make_task(project=project) for _ in range(3)]

        project.refresh_from_db()
        assert project.tasks.count() == 3
        assert project.tasks_count == 3

        tasks[0].delete()
        project.refresh_from_db()
        assert project.tasks_count == 2

    def test_keeps_track_of_the_owners_projects_count(self, user, make_project):
        projects = [make_project(user=user) for _ in range(2)]
        user.refresh_from_db()
        assert user.projects_count == 2

        projects[0].delete()
        user.refresh_from_db()
        assert user.projects_count == 1

    def test_touches_the_project_and_its_owner_when_a_task_is_saved(
        self, user, make_project, make_task, clock
    ):
        project = make_project(user=user)
        clock.travel(timedelta(seconds=1))

        make_task(project=project)

        project.refresh_from_db()
        user.refresh_from_db()
        assert project.updated_at == clock.now
        assert user.updated_at == clock.now


@pytest.mark.django_db
class TestDeletion:
    def test_keeps_a_project_with_tasks(self, make_project, make_task):
        project = make_project()
        make_task(project=project)

        assert project.deletion_errors() == ["Cannot delete record because dependent tasks exist"]
        with pytest.raises(ProtectedError):
            project.delete()
        assert Project.objects.filter(pk=project.pk).exists()

    def test_deletes_a_project_without_tasks(self, make_project):
        project = make_project()

        assert project.deletion_errors() == []
        project.delete()
        assert Project.objects.count() == 0
