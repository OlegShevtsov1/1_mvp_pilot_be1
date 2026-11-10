"""Task model validations and counters."""

import pytest

from apps.tasks.models import Task

ALLOWED_STATUSES_ERROR = "Status must be one of: not_started, in_progress, completed"


def build(**fields):
    return Task(**{"name": "Test", "description": "Test", "status": "not_started"} | fields)


def test_names_the_three_statuses():
    assert Task.STATUSES == ("not_started", "in_progress", "completed")


@pytest.mark.parametrize("field", ["name", "description"])
def test_needs_a(field):
    assert f"{field.capitalize()} can't be blank" in build(**{field: ""}).full_messages()


@pytest.mark.parametrize("status", Task.STATUSES)
def test_is_valid_with_each_status(status):
    assert build(status=status).full_messages() == []


def test_needs_a_status():
    assert build(status=None).full_messages() == [ALLOWED_STATUSES_ERROR, "Status can't be blank"]


def test_starts_a_task_as_not_started_when_no_status_is_given():
    assert Task(name="Test", description="Test").status == "not_started"


def test_rejects_a_status_outside_the_three_and_names_the_allowed_ones():
    assert build(status="archived").full_messages() == [ALLOWED_STATUSES_ERROR]
