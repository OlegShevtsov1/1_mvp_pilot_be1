"""Who may do what with a project: its owner, its members and viewers, and nobody else.

A project the caller can't see answers 404 like a missing one, never 403; a project the caller
sees with too low a role answers 403.
"""

from django.db.models import Q
from django.http import Http404

from apps.common.exceptions import Forbidden
from apps.projects.models import Membership, Project
from apps.projects.params import record_id

OWNER = "owner"
READ = "read"
WRITE_TASKS = "write_tasks"
MANAGE = "manage"

# The roles each level admits.
RIGHTS = {
    READ: {OWNER, "member", "viewer"},
    WRITE_TASKS: {OWNER, "member"},
    MANAGE: {OWNER},
}


def role_of(user, project):
    """`"owner"`, the membership's `"member"` / `"viewer"`, or None for a stranger."""
    if project.user_id == user.id:
        return OWNER
    return (
        Membership.objects.filter(project_id=project.id, user_id=user.id)
        .values_list("role", flat=True)
        .first()
    )


def visible_projects(user):
    """The user's own projects and the projects they are a member of."""
    shared = Membership.objects.filter(user_id=user.id).values("project_id")
    return Project.objects.filter(Q(user_id=user.id) | Q(pk__in=shared))


def allowed(role, level):
    return role in RIGHTS[level]


def project_for(request, raw_id, level):
    """The project of the path id, if the caller sees it (else 404) with a role admitted to
    `level` (else 403)."""
    project = visible_projects(request.user).filter(pk=record_id(raw_id)).first()
    if project is None:
        raise Http404
    if not allowed(role_of(request.user, project), level):
        raise Forbidden()
    return project
