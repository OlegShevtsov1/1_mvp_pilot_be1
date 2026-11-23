"""The project's and membership's JSON: plain dicts, so the dashboard list builds one per
project."""

USER_FIELDS = ("id", "email")
TASK_FIELDS = ("id", "name", "description", "status")


def _fields(record, names):
    return {name: getattr(record, name) for name in names}


def task_attributes(task):
    return _fields(task, TASK_FIELDS)


def project_json(project):
    """Reads `project.user` and `project.tasks`, which the caller has loaded."""
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "user": _fields(project.user, USER_FIELDS),
        "tasks": [task_attributes(task) for task in project.tasks.all()],
    }


def member_json(membership):
    """Reads `membership.user`, which the caller has loaded."""
    return {
        "id": membership.id,
        "role": membership.role,
        "user": _fields(membership.user, USER_FIELDS),
        "created_at": membership.created_at.isoformat(),
        "updated_at": membership.updated_at.isoformat(),
    }
