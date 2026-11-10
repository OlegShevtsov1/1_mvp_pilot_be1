"""Project services: the cached list and the writes."""

from dataclasses import dataclass, field

from django.core.cache import cache
from django.db.models import Count, Max, Prefetch

from apps.projects.models import Project, blank
from apps.tasks.models import Task

CACHE_TIMEOUT = 15 * 60


@dataclass
class ProjectResult:
    project: Project | None = None
    errors: list[str] = field(default_factory=list)


def signature(records):
    """The `stats:count=<n>:updated=<latest updated_at|none>` part of a list cache key, with the
    timestamp to the microsecond."""
    stats = records.aggregate(count=Count("id"), updated=Max("updated_at"))
    updated = stats["updated"].isoformat() if stats["updated"] else "none"
    return f"stats:count={stats['count']}:updated={updated}"


def cache_key(user, task_status=None):
    filter_part = [] if task_status is None else [f"filter:{task_status}"]
    parts = [f"projects:{user.id}", signature(user.projects), *filter_part, "v1"]
    return ":".join(parts)


def with_owner_and_tasks(projects, tasks=None):
    tasks = Task.objects.all() if tasks is None else tasks
    return projects.select_related("user").prefetch_related(
        Prefetch("tasks", queryset=tasks.order_by("id"))
    )


def fetch_projects(user, task_status=None):
    """The user's projects; with `task_status`, those having such a task, each with only
    those tasks, loaded in one joined query."""
    projects = user.projects.order_by("id")
    if task_status is None:
        return list(with_owner_and_tasks(projects))
    return list(
        with_owner_and_tasks(
            projects.filter(tasks__status=task_status).distinct(),
            Task.objects.filter(status=task_status),
        )
    )


def index(user, task_status=None):
    task_status = None if blank(task_status) else task_status
    return cache.get_or_set(
        cache_key(user, task_status), lambda: fetch_projects(user, task_status), CACHE_TIMEOUT
    )


def load(project_id):
    return with_owner_and_tasks(Project.objects).get(pk=project_id)


def show(project):
    return load(project.pk)


def create(user, params):
    project = Project(user=user, **params)
    errors = project.full_messages()
    if errors:
        return ProjectResult(project, errors)
    project.save()
    return ProjectResult(load(project.pk))


def update(project, params):
    changed = [name for name, value in params.items() if getattr(project, name) != value]
    for name, value in params.items():
        setattr(project, name, value)
    errors = project.full_messages()
    if errors:
        return ProjectResult(project, errors)
    # Only the changed columns are written, and nothing at all when none changed.
    if changed:
        project.save(update_fields=[*changed, "updated_at"])
    return ProjectResult(load(project.pk))


def delete(project):
    errors = project.deletion_errors()
    if not errors:
        project.delete()
    return ProjectResult(project, errors)
