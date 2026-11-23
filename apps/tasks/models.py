import re

from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

from apps.projects.models import Project, blank
from apps.users.models import User


class Task(models.Model):
    """The tasks table; saving and deleting keep the project's `tasks_count` and touch the
    project and its owner."""

    STATUSES = ("not_started", "in_progress", "completed")

    name = models.CharField(null=True)
    description = models.TextField(null=True)
    # The status default lives in the model, not the column.
    status = models.CharField(null=True, default="not_started")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="tasks")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # The tasks this task waits for; `blocks` lists the tasks waiting for this one. Deleting a
    # task deletes its rows in both directions.
    blocked_by = models.ManyToManyField(
        "self", symmetrical=False, related_name="blocks", blank=True
    )
    labels = models.ManyToManyField("tasks.Label", related_name="tasks", blank=True)

    def full_messages(self):
        """The validation messages, in order; empty when the task is valid."""
        messages = []
        if self.status not in self.STATUSES:
            messages.append(f"Status must be one of: {', '.join(self.STATUSES)}")
        if blank(self.name):
            messages.append("Name can't be blank")
        if blank(self.description):
            messages.append("Description can't be blank")
        if blank(self.status):
            messages.append("Status can't be blank")
        return messages

    def save(self, *args, **kwargs):
        creating = self._state.adding
        with transaction.atomic():
            super().save(*args, **kwargs)
            counter = {"tasks_count": F("tasks_count") + 1} if creating else {}
            self._touch_parents(self.updated_at, **counter)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            deleted = super().delete(*args, **kwargs)
            self._touch_parents(timezone.now(), tasks_count=F("tasks_count") - 1)
        return deleted

    def _touch_parents(self, now, **project_fields):
        Project.objects.filter(pk=self.project_id).update(updated_at=now, **project_fields)
        User.objects.filter(projects__pk=self.project_id).update(updated_at=now)


class Label(models.Model):
    """A project's label, named uniquely in the project and attached to any of its tasks.
    Saving and deleting touch the project, so the list caches of its owner and members change;
    deleting a label detaches it from its tasks."""

    NAME_MAX_LENGTH = 30
    DEFAULT_COLOR = "#808080"
    COLOR = re.compile(r"#[0-9a-fA-F]{6}", re.ASCII)

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="labels")
    name = models.CharField(null=True)
    color = models.CharField(null=True, default=DEFAULT_COLOR)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="unique_project_label_name")
        ]

    def full_messages(self):
        """The validation messages, in order; empty when the label is valid."""
        messages = []
        if blank(self.name):
            messages.append("Name can't be blank")
        elif len(self.name) > self.NAME_MAX_LENGTH:
            messages.append(f"Name is too long (maximum is {self.NAME_MAX_LENGTH} characters)")
        if not blank(self.name) and self.name_taken():
            messages.append("Name has already been taken")
        if not isinstance(self.color, str) or not self.COLOR.fullmatch(self.color):
            messages.append("Color must be a hex color like #1a2b3c")
        return messages

    def name_taken(self):
        return (
            Label.objects.filter(project_id=self.project_id, name=self.name)
            .exclude(pk=self.pk)
            .exists()
        )

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            touch(self.project_id, self.updated_at)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            deleted = super().delete(*args, **kwargs)
            touch(self.project_id)
        return deleted


def touch(project_id, now=None):
    """Moves the project's `updated_at`, so the cached lists that cover it change."""
    Project.objects.filter(pk=project_id).update(updated_at=now or timezone.now())
