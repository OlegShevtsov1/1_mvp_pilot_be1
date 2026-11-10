from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

from apps.users.models import User

# The Unicode White_Space set; `str.isspace()` would also count U+001C-U+001F.
WHITE_SPACE = (
    "\t\n\v\f\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007"
    "\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
)


def blank(value):
    """Blank: missing or whitespace only."""
    return value is None or not value.strip(WHITE_SPACE)


def _presence_and_length(label, value, minimum, maximum):
    messages = [f"{label} can't be blank"] if blank(value) else []
    length = len(value or "")
    if length < minimum:
        messages.append(f"{label} is too short (minimum is {minimum} characters)")
    elif length > maximum:
        messages.append(f"{label} is too long (maximum is {maximum} characters)")
    return messages


class Project(models.Model):
    """The projects table; saving and deleting keep the owner's `projects_count` and `updated_at`
    current."""

    NAME_MIN_LENGTH = 5
    NAME_MAX_LENGTH = 20
    DESCRIPTION_MIN_LENGTH = 20
    DESCRIPTION_MAX_LENGTH = 120

    name = models.CharField(null=True)
    description = models.TextField(null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="projects")
    tasks_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def full_messages(self):
        """The validation messages, in order; empty when the project is valid."""
        return _presence_and_length(
            "Name", self.name, self.NAME_MIN_LENGTH, self.NAME_MAX_LENGTH
        ) + _presence_and_length(
            "Description",
            self.description,
            self.DESCRIPTION_MIN_LENGTH,
            self.DESCRIPTION_MAX_LENGTH,
        )

    def deletion_errors(self):
        """A project with tasks cannot be deleted."""
        if self.tasks.exists():
            return ["Cannot delete record because dependent tasks exist"]
        return []

    def save(self, *args, **kwargs):
        creating = self._state.adding
        with transaction.atomic():
            super().save(*args, **kwargs)
            owner = User.objects.filter(pk=self.user_id)
            if creating:
                owner.update(projects_count=F("projects_count") + 1, updated_at=self.updated_at)
            else:
                owner.update(updated_at=self.updated_at)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            deleted = super().delete(*args, **kwargs)
            User.objects.filter(pk=self.user_id).update(
                projects_count=F("projects_count") - 1, updated_at=timezone.now()
            )
        return deleted
