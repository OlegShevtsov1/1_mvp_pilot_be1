import pytest

from apps.projects.models import Project
from apps.tasks.models import Task
from apps.users.tests import conftest as users

clock = users.clock
make_access_token = users.make_access_token
make_user = users.make_user
user = users.user


@pytest.fixture
def make_project(make_user):
    """A saved project; `fields` override the valid defaults."""

    def make(user=None, **fields):
        return Project.objects.create(
            user=user or make_user(),
            **{
                "name": "Sample Project",
                "description": (
                    "This is a sample project description that meets the minimum length requirement"
                ),
            }
            | fields,
        )

    return make


@pytest.fixture
def make_task(make_project):
    """A saved task; `fields` override the valid defaults."""

    def make(project=None, **fields):
        return Task.objects.create(
            project=project or make_project(),
            **{
                "name": "Sample Task",
                "description": "This is a sample task description",
                "status": "not_started",
            }
            | fields,
        )

    return make


@pytest.fixture
def bearer(make_access_token):
    def headers(user):
        return {"Authorization": f"Bearer {make_access_token(user).plaintext}"}

    return headers
