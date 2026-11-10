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
