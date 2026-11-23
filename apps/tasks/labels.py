"""Label services: a project's labels, and the labels attached to its tasks."""

from dataclasses import dataclass, field

from django.db import IntegrityError, transaction

from apps.tasks.models import Label, touch

TAKEN_MESSAGE = "Name has already been taken"
SAME_PROJECT_MESSAGE = "Label must belong to the same project"
ATTACHED_MESSAGE = "Label already attached"


@dataclass
class LabelResult:
    label: Label | None = None
    errors: list[str] = field(default_factory=list)


def index(project):
    return list(project.labels.order_by("id"))


def of_task(task):
    return list(task.labels.order_by("id"))


def create(project, params):
    params = {name: value for name, value in params.items() if value is not None}
    label = Label(project=project, **params)
    errors = label.full_messages()
    if errors:
        return LabelResult(label, errors)
    return _saved(label)


def update(label, params):
    changed = [name for name, value in params.items() if getattr(label, name) != value]
    for name, value in params.items():
        setattr(label, name, value)
    errors = label.full_messages()
    if errors:
        return LabelResult(label, errors)
    # Only the changed columns are written, and nothing at all when none changed.
    if changed:
        return _saved(label, update_fields=[*changed, "updated_at"])
    return LabelResult(label)


def _saved(label, **options):
    try:
        with transaction.atomic():
            label.save(**options)
    except IntegrityError:
        # Another request took the name in between.
        return LabelResult(label, [TAKEN_MESSAGE])
    return LabelResult(label)


def delete(label):
    label.delete()
    return LabelResult(label)


def attach(task, label):
    """Attaches `label` (a label of the task's project, or None for an id outside it)."""
    if label is None:
        return LabelResult(None, [SAME_PROJECT_MESSAGE])
    if task.labels.filter(pk=label.id).exists():
        return LabelResult(label, [ATTACHED_MESSAGE])
    try:
        with transaction.atomic():
            task.labels.through.objects.create(task_id=task.id, label_id=label.id)
            touch(task.project_id)
    except IntegrityError:
        # Another request attached it in between.
        return LabelResult(label, [ATTACHED_MESSAGE])
    return LabelResult(label)


def detach(task, label):
    with transaction.atomic():
        task.labels.remove(label)
        touch(task.project_id)
    return LabelResult(label)
