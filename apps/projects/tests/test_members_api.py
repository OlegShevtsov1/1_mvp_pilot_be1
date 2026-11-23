"""The members endpoints, per role, checked against the contract."""

import pytest

from apps.projects.models import Membership
from tests.contract import assert_matches_contract

LIST = "/api/v1/projects/{project_id}/members"
ONE = "/api/v1/projects/{project_id}/members/{id}"
INVALID = {"Authorization": "Bearer invalid"}
NOT_FOUND = {"error": "Not Found"}
FORBIDDEN = {"error": "You are not authorized to perform this action"}
USER_NOT_FOUND = {"error": "User not found"}
BAD_ROLE = "Role must be one of: member, viewer"
PARAMETER_MISSING = {"status": 422, "error": "Unprocessable Content"}

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(make_user):
    return make_user()


@pytest.fixture
def project(owner, make_project):
    return make_project(user=owner)


@pytest.fixture
def member(project, make_membership):
    return make_membership(project=project, role="member")


@pytest.fixture
def viewer(project, make_membership):
    return make_membership(project=project, role="viewer")


@pytest.fixture
def stranger(make_user):
    return make_user()


@pytest.fixture
def headers_of(owner, member, viewer, stranger, bearer):
    """The bearer headers of the caller in the given role."""
    users = {"owner": owner, "member": member.user, "viewer": viewer.user, "stranger": stranger}
    return lambda role: bearer(users[role])


def call(client, method, path, template, headers, data=None):
    response = getattr(client, method)(path, data, content_type="application/json", headers=headers)
    if method != "patch":  # PATCH is not in the contract; it behaves as PUT.
        assert_matches_contract(response, method, template)
    return response


def members_of(project_id):
    return LIST.format(project_id=project_id)


def one(project_id, membership_id):
    return ONE.format(project_id=project_id, id=membership_id)


def member_json(membership):
    membership.refresh_from_db()
    return {
        "id": membership.id,
        "role": membership.role,
        "user": {"id": membership.user.id, "email": membership.user.email},
        "created_at": membership.created_at.isoformat(),
        "updated_at": membership.updated_at.isoformat(),
    }


@pytest.mark.parametrize(
    ("method", "template", "data"),
    [
        ("get", LIST, None),
        ("post", LIST, {"member": {"email": "a@example.com", "role": "viewer"}}),
        ("put", ONE, {"member": {"role": "viewer"}}),
        ("delete", ONE, None),
    ],
)
def test_answers_not_authorized_to_an_invalid_bearer(
    client, project, member, method, template, data
):
    path = template.format(project_id=project.id, id=member.id)

    response = call(client, method, path, template, INVALID, data)

    assert response.status_code == 401
    assert response.json() == {"error": "Not Authorized"}


class TestList:
    @pytest.mark.parametrize("role", ["owner", "member", "viewer"])
    def test_lists_the_members_in_id_order_to_any_role(
        self, client, headers_of, project, member, viewer, role
    ):
        response = call(client, "get", members_of(project.id), LIST, headers_of(role))

        assert response.status_code == 200
        assert response.json() == {"data": [member_json(member), member_json(viewer)]}

    def test_renders_the_member_json_keys_in_order(self, client, headers_of, project, member):
        response = call(client, "get", members_of(project.id), LIST, headers_of("owner"))

        data = response.json()["data"][0]
        assert list(data) == ["id", "role", "user", "created_at", "updated_at"]
        assert list(data["user"]) == ["id", "email"]

    def test_lists_nothing_for_a_project_without_members(self, client, owner, bearer, make_project):
        lonely = make_project(user=owner)

        response = call(client, "get", members_of(lonely.id), LIST, bearer(owner))

        assert response.json() == {"data": []}

    def test_answers_not_found_to_a_stranger(self, client, headers_of, project):
        response = call(client, "get", members_of(project.id), LIST, headers_of("stranger"))

        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    @pytest.mark.parametrize("raw", ["999999", "abc", "0"])
    def test_answers_not_found_for_a_missing_project(self, client, headers_of, raw):
        response = call(client, "get", members_of(raw), LIST, headers_of("owner"))

        assert response.status_code == 404
        assert response.json() == NOT_FOUND


class TestCreate:
    @pytest.fixture
    def newcomer(self, make_user):
        return make_user()

    def test_adds_a_user_by_email_with_the_role(self, client, headers_of, project, newcomer):
        body = {"member": {"email": newcomer.email, "role": "viewer"}}

        response = call(client, "post", members_of(project.id), LIST, headers_of("owner"), body)

        assert response.status_code == 201
        membership = Membership.objects.get(project=project, user=newcomer)
        assert membership.role == "viewer"
        assert response.json() == {"data": member_json(membership)}

    def test_reads_an_unwrapped_body_as_the_member(self, client, headers_of, project, newcomer):
        body = {"email": newcomer.email, "role": "member"}

        response = call(client, "post", members_of(project.id), LIST, headers_of("owner"), body)

        assert response.status_code == 201
        assert response.json()["data"]["role"] == "member"
        assert response.json()["data"]["user"]["id"] == newcomer.id

    def test_finds_the_user_whatever_the_case_and_surrounding_spaces_of_the_email(
        self, client, headers_of, project, newcomer
    ):
        body = {"member": {"email": f"  {newcomer.email.upper()} ", "role": "viewer"}}

        response = call(client, "post", members_of(project.id), LIST, headers_of("owner"), body)

        assert response.status_code == 201
        assert response.json()["data"]["user"]["id"] == newcomer.id

    @pytest.mark.parametrize("email", ["nobody@example.com", "", None])
    def test_answers_user_not_found_for_an_unknown_email(self, client, headers_of, project, email):
        body = {"member": {"email": email, "role": "viewer"}}

        response = call(client, "post", members_of(project.id), LIST, headers_of("owner"), body)

        assert response.status_code == 404
        assert response.json() == USER_NOT_FOUND

    def test_refuses_the_owner(self, client, owner, headers_of, project):
        body = {"member": {"email": owner.email, "role": "member"}}

        response = call(client, "post", members_of(project.id), LIST, headers_of("owner"), body)

        assert response.status_code == 422
        assert response.json() == {"errors": ["User is the project owner"]}
        assert project.memberships.filter(user=owner).count() == 0

    def test_refuses_a_user_who_is_already_a_member(self, client, headers_of, project, viewer):
        body = {"member": {"email": viewer.user.email, "role": "member"}}

        response = call(client, "post", members_of(project.id), LIST, headers_of("owner"), body)

        assert response.status_code == 422
        assert response.json() == {"errors": ["User is already a member"]}
        viewer.refresh_from_db()
        assert viewer.role == "viewer"

    @pytest.mark.parametrize("role", ["owner", "admin", "", None, 1, ["member"]])
    def test_refuses_a_bad_role(self, client, headers_of, project, newcomer, role):
        body = {"member": {"email": newcomer.email, "role": role}}

        response = call(client, "post", members_of(project.id), LIST, headers_of("owner"), body)

        assert response.status_code == 422
        assert response.json() == {"errors": [BAD_ROLE]}
        assert not Membership.objects.filter(user=newcomer).exists()

    def test_refuses_a_missing_role(self, client, headers_of, project, newcomer):
        body = {"member": {"email": newcomer.email}}

        response = call(client, "post", members_of(project.id), LIST, headers_of("owner"), body)

        assert response.status_code == 422
        assert response.json() == {"errors": [BAD_ROLE]}

    def test_lists_every_reason_in_order(self, client, owner, headers_of, project):
        body = {"member": {"email": owner.email, "role": "boss"}}

        response = call(client, "post", members_of(project.id), LIST, headers_of("owner"), body)

        assert response.json() == {"errors": ["User is the project owner", BAD_ROLE]}

    @pytest.mark.parametrize("body", [{"member": {}}, {"member": None}, {"foo": 1}, []])
    def test_refuses_a_body_without_a_member(self, client, headers_of, project, body):
        response = call(client, "post", members_of(project.id), LIST, headers_of("owner"), body)

        assert response.status_code == 422
        assert response.json() == PARAMETER_MISSING

    @pytest.mark.parametrize("role", ["member", "viewer"])
    def test_is_forbidden_to_a_member_or_viewer(self, client, headers_of, project, newcomer, role):
        body = {"member": {"email": newcomer.email, "role": "viewer"}}

        response = call(client, "post", members_of(project.id), LIST, headers_of(role), body)

        assert response.status_code == 403
        assert response.json() == FORBIDDEN
        assert not Membership.objects.filter(user=newcomer).exists()

    def test_answers_not_found_to_a_stranger(self, client, headers_of, project, newcomer):
        body = {"member": {"email": newcomer.email, "role": "viewer"}}

        response = call(client, "post", members_of(project.id), LIST, headers_of("stranger"), body)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND
        assert not Membership.objects.filter(user=newcomer).exists()


class TestUpdate:
    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_changes_the_role(self, client, headers_of, project, viewer, method):
        body = {"member": {"role": "member"}}

        response = call(client, method, one(project.id, viewer.id), ONE, headers_of("owner"), body)

        assert response.status_code == 200
        viewer.refresh_from_db()
        assert viewer.role == "member"
        assert response.json() == {"data": member_json(viewer)}

    def test_reads_an_unwrapped_body_as_the_member(self, client, headers_of, project, viewer):
        response = call(
            client, "put", one(project.id, viewer.id), ONE, headers_of("owner"), {"role": "member"}
        )

        assert response.status_code == 200
        assert response.json()["data"]["role"] == "member"

    @pytest.mark.parametrize("role", ["owner", "", None])
    def test_refuses_a_bad_role(self, client, headers_of, project, viewer, role):
        body = {"member": {"role": role}}

        response = call(client, "put", one(project.id, viewer.id), ONE, headers_of("owner"), body)

        assert response.status_code == 422
        assert response.json() == {"errors": [BAD_ROLE]}
        viewer.refresh_from_db()
        assert viewer.role == "viewer"

    @pytest.mark.parametrize("role", ["member", "viewer"])
    def test_is_forbidden_to_a_member_or_viewer(self, client, headers_of, project, viewer, role):
        body = {"member": {"role": "member"}}

        response = call(client, "put", one(project.id, viewer.id), ONE, headers_of(role), body)

        assert response.status_code == 403
        assert response.json() == FORBIDDEN
        viewer.refresh_from_db()
        assert viewer.role == "viewer"

    def test_answers_not_found_to_a_stranger(self, client, headers_of, project, viewer):
        body = {"member": {"role": "member"}}

        response = call(
            client, "put", one(project.id, viewer.id), ONE, headers_of("stranger"), body
        )

        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    def test_answers_not_found_for_a_membership_of_another_project(
        self, client, owner, headers_of, project, make_project, make_membership
    ):
        elsewhere = make_membership(project=make_project(user=owner), role="viewer")
        body = {"member": {"role": "member"}}

        response = call(
            client, "put", one(project.id, elsewhere.id), ONE, headers_of("owner"), body
        )

        assert response.status_code == 404
        assert response.json() == NOT_FOUND
        elsewhere.refresh_from_db()
        assert elsewhere.role == "viewer"

    @pytest.mark.parametrize("raw", ["999999", "abc"])
    def test_answers_not_found_for_a_missing_membership(self, client, headers_of, project, raw):
        body = {"member": {"role": "member"}}

        response = call(client, "put", one(project.id, raw), ONE, headers_of("owner"), body)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND


class TestDelete:
    def test_the_owner_removes_a_member(self, client, headers_of, project, member):
        response = call(client, "delete", one(project.id, member.id), ONE, headers_of("owner"))

        assert response.status_code == 204
        assert response.content == b""
        assert not Membership.objects.filter(pk=member.id).exists()

    @pytest.mark.parametrize("role", ["member", "viewer"])
    def test_a_member_or_viewer_leaves(self, client, headers_of, project, member, viewer, role):
        own = {"member": member, "viewer": viewer}[role]

        response = call(client, "delete", one(project.id, own.id), ONE, headers_of(role))

        assert response.status_code == 204
        assert not Membership.objects.filter(pk=own.id).exists()

    @pytest.mark.parametrize(("role", "other"), [("member", "viewer"), ("viewer", "member")])
    def test_is_forbidden_to_remove_someone_else_unless_owner(
        self, client, headers_of, project, member, viewer, role, other
    ):
        target = {"member": member, "viewer": viewer}[other]

        response = call(client, "delete", one(project.id, target.id), ONE, headers_of(role))

        assert response.status_code == 403
        assert response.json() == FORBIDDEN
        assert Membership.objects.filter(pk=target.id).exists()

    def test_answers_not_found_to_a_stranger(self, client, headers_of, project, member):
        response = call(client, "delete", one(project.id, member.id), ONE, headers_of("stranger"))

        assert response.status_code == 404
        assert response.json() == NOT_FOUND
        assert Membership.objects.filter(pk=member.id).exists()

    def test_answers_not_found_for_a_membership_of_another_project(
        self, client, owner, headers_of, project, make_project, make_membership
    ):
        elsewhere = make_membership(project=make_project(user=owner))

        response = call(client, "delete", one(project.id, elsewhere.id), ONE, headers_of("owner"))

        assert response.status_code == 404
        assert response.json() == NOT_FOUND
        assert Membership.objects.filter(pk=elsewhere.id).exists()

    def test_a_former_member_no_longer_sees_the_project(self, client, headers_of, project, member):
        headers = headers_of("member")
        call(client, "delete", one(project.id, member.id), ONE, headers)

        response = call(client, "get", members_of(project.id), LIST, headers)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND
