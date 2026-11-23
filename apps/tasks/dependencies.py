"""Dependency services: a task is blocked by other tasks of its project."""

from dataclasses import dataclass, field

from django.db import IntegrityError, transaction

from apps.projects.models import Project
from apps.tasks.models import Task, touch

SAME_PROJECT_MESSAGE = "Task must belong to the same project"
SELF_MESSAGE = "Task cannot depend on itself"
ALREADY_MESSAGE = "Dependency already exists"
CYCLE_MESSAGE = "Dependency would create a cycle"
BLOCKED_MESSAGE = "Task is blocked by unfinished tasks"

Edge = Task.blocked_by.through


@dataclass
class DependencyResult:
    blocker: Task | None = None
    errors: list[str] = field(default_factory=list)


def blockers_of(project):
    """The project's dependency graph, `{task id: {blocker ids}}`, read in one query."""
    graph = {}
    edges = Edge.objects.filter(from_task__project_id=project.id).values_list(
        "from_task_id", "to_task_id"
    )
    for task_id, blocker_id in edges:
        graph.setdefault(task_id, set()).add(blocker_id)
    return graph


def creates_cycle(task, blocker):
    """Whether `task` blocked by `blocker` closes a cycle: whether `task` is already among the
    tasks `blocker` waits for, directly or not. Walks the project's graph iteratively, after one
    query, whatever its depth."""
    graph = blockers_of(task.project)
    seen = set()
    pending = [blocker.id]
    while pending:
        current = pending.pop()
        if current == task.id:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(graph.get(current, ()))
    return False


def lock_project(project_id):
    """Locks the project row for the rest of the transaction, so the dependency checks and the
    write that follows them run one request at a time per project (a no-op on SQLite, which
    serialises writes anyway)."""
    Project.objects.select_for_update().filter(pk=project_id).first()


def add(task, blocker):
    """Makes `blocker` (a task of the project, or None for an id outside it) block `task`. The
    checks and the insert run under the project lock, so two concurrent requests cannot both
    pass the cycle check and store a cycle."""
    if blocker is None:
        return DependencyResult(None, [SAME_PROJECT_MESSAGE])
    if blocker.id == task.id:
        return DependencyResult(blocker, [SELF_MESSAGE])
    with transaction.atomic():
        lock_project(task.project_id)
        if task.blocked_by.filter(pk=blocker.id).exists():
            return DependencyResult(blocker, [ALREADY_MESSAGE])
        if creates_cycle(task, blocker):
            return DependencyResult(blocker, [CYCLE_MESSAGE])
        try:
            with transaction.atomic():
                Edge.objects.create(from_task_id=task.id, to_task_id=blocker.id)
                touch(task.project_id)
        except IntegrityError:
            # Another request added the same dependency in between.
            return DependencyResult(blocker, [ALREADY_MESSAGE])
    return DependencyResult(blocker)


def remove(task, blocker):
    with transaction.atomic():
        task.blocked_by.remove(blocker)
        touch(task.project_id)
    return DependencyResult(blocker)


def unfinished_blockers(task):
    """Completing a task needs every blocker completed; the message when one is not."""
    if task.blocked_by.exclude(status="completed").exists():
        return [BLOCKED_MESSAGE]
    return []
