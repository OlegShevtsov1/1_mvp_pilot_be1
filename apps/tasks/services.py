"""Task services: the cached list and the writes."""

from dataclasses import dataclass, field

from django.core.cache import cache
from django.db import DatabaseError, transaction
from django.db.models import Prefetch

from apps.projects import services as projects
from apps.tasks import dependencies
from apps.tasks.models import Task

CACHE_TIMEOUT = 15 * 60


@dataclass
class TaskResult:
    task: Task | None = None
    errors: list[str] = field(default_factory=list)


def cache_key(project):
    return f"tasks:{project.id}:{projects.signature(project.tasks)}:v1"


def fetch_tasks(project):
    """The project's tasks, all sharing one project instance with its owner and tasks loaded,
    so rendering each task's nested project costs no query."""
    project = projects.load(project.pk)
    tasks = list(project.tasks.all())
    for task in tasks:
        task.project = project
    return tasks


def with_project(project, tasks):
    """`tasks` of the project in id order, all sharing one project instance with its owner and
    tasks loaded, so rendering each task's nested project costs no query."""
    project = projects.load(project.pk)
    tasks = list(tasks.order_by("id"))
    for task in tasks:
        task.project = project
    return tasks


def index(project):
    return cache.get_or_set(cache_key(project), lambda: fetch_tasks(project), CACHE_TIMEOUT)


def load(task_id):
    return (
        Task.objects.select_related("project__user")
        .prefetch_related(Prefetch("project__tasks", queryset=Task.objects.order_by("id")))
        .get(pk=task_id)
    )


def show(task):
    return load(task.pk)


def create(project, params):
    task = Task(project=project, **params)
    errors = task.full_messages()
    if errors:
        return TaskResult(task, errors)
    task.save()
    return TaskResult(load(task.pk))


def update(task, params):
    changed = [name for name, value in params.items() if getattr(task, name) != value]
    completing = "status" in changed and params["status"] == "completed"
    for name, value in params.items():
        setattr(task, name, value)
    # Completing checks the blockers under the project lock that adding a dependency takes, so
    # a blocker added concurrently is either seen here or refused there.
    with transaction.atomic():
        errors = task.full_messages()
        if completing:
            dependencies.lock_project(task.project_id)
            errors += dependencies.unfinished_blockers(task)
        if errors:
            return TaskResult(task, errors)
        # Only the changed columns are written, and nothing at all when none changed.
        if changed:
            task.save(update_fields=[*changed, "updated_at"])
    return TaskResult(load(task.pk))


def delete(task):
    try:
        task.delete()
    except DatabaseError as error:
        return TaskResult(task, [str(error)])
    return TaskResult(task)
