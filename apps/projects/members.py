"""Membership services: the list and the writes."""

from dataclasses import dataclass, field

from django.db import IntegrityError

from apps.projects.models import Membership
from apps.users.models import User

OWNER_MESSAGE = "User is the project owner"
ALREADY_MESSAGE = "User is already a member"


@dataclass
class MemberResult:
    membership: Membership | None = None
    errors: list[str] = field(default_factory=list)


def index(project):
    return list(project.memberships.select_related("user").order_by("id"))


def load(membership_id):
    return Membership.objects.select_related("user").get(pk=membership_id)


def user_by_email(email):
    """The user of the email, compared as stored (stripped and lowercased), or None."""
    email = (email or "").strip().lower()
    return User.objects.filter(email=email).first() if email else None


def add(project, user, role):
    membership = Membership(project=project, user=user, role=role)
    errors = []
    if user.id == project.user_id:
        errors.append(OWNER_MESSAGE)
    elif project.memberships.filter(user_id=user.id).exists():
        errors.append(ALREADY_MESSAGE)
    errors += membership.full_messages()
    if errors:
        return MemberResult(membership, errors)
    try:
        membership.save()
    except IntegrityError:
        # Another request added the same user in between.
        return MemberResult(membership, [ALREADY_MESSAGE])
    return MemberResult(load(membership.pk))


def update(membership, params):
    changed = [name for name, value in params.items() if getattr(membership, name) != value]
    for name, value in params.items():
        setattr(membership, name, value)
    errors = membership.full_messages()
    if errors:
        return MemberResult(membership, errors)
    # Only the changed columns are written, and nothing at all when none changed.
    if changed:
        membership.save(update_fields=[*changed, "updated_at"])
    return MemberResult(load(membership.pk))


def remove(membership):
    membership.delete()
    return MemberResult(membership)
