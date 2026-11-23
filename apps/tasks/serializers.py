from apps.projects.serializers import project_json, task_attributes


def task_json(task):
    """The task's JSON: the task with its whole project, owner and tasks included."""
    return task_attributes(task) | {"project": project_json(task.project)}


def label_json(label):
    return {
        "id": label.id,
        "name": label.name,
        "color": label.color,
        "created_at": label.created_at.isoformat(),
        "updated_at": label.updated_at.isoformat(),
    }
