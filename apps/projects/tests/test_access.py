"""Who may do what with a project: roles, visibility and the project endpoints per role."""

import pytest
from django.http import Http404
from rest_framework.test import APIRequestFactory

from apps.common.exceptions import Forbidden
from apps.projects import access
from apps.projects.models import Project
from tests.contract import assert_matches_contract

LIST = "/api/v1/projects"
ONE = "/api/v1/projects/{id}"
NOT_FOUND = {"error": "Not Found"}
FORBIDDEN = {"error": "You are not authorized to perform this action"}

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(make_user):
    return make_user()


@pytest.fixture
def project(owner, make_project):
    return make_project(user=owner)


@pytest.fixture
def users(owner, project, make_user, make_membership):
    member = make_membership(project=project, role="member").user
    viewer = make_membership(project=project, role="viewer").user
    return {"owner": owner, "member": member, "viewer": viewer, "stranger": make_user()}


def answer(client, bearer, user, method, path, data=None):
    response = getattr(client, method)(
        path, data, content_type="application/json", headers=bearer(user)
    )
    return response


class TestRoleOf:
    def test_names_each_role(self, project, users):
        assert {name: access.role_of(user, project) for name, user in users.items()} == {
            "owner": "owner",
            "member": "member",
            "viewer": "viewer",
            "stranger": None,
        }

    def test_a_membership_of_another_project_gives_no_role(
        self, project, make_project, make_membership
    ):
        elsewhere = make_membership(project=make_project())

        assert access.role_of(elsewhere.user, project) is None


class TestVisibleProjects:
    def test_are_the_owned_and_the_shared_projects_each_once(
        self, owner, project, make_project, make_membership
    ):
        own = make_project(user=owner)
        shared = make_project()
        make_membership(project=shared, user=owner, role="viewer")
        make_membership(project=own)
        make_membership(project=own)
        make_project()

        assert list(access.visible_projects(owner).order_by("id")) == [project, own, shared]


class TestProjectFor:
    @pytest.fixture
    def request_of(self):
        def build(user):
            request = APIRequestFactory().get("/")
            request.user = user
            return request

        return build

    @pytest.mark.parametrize(
        ("role", "level"),
        [
            ("owner", access.READ),
            ("owner", access.WRITE_TASKS),
            ("owner", access.MANAGE),
            ("member", access.READ),
            ("member", access.WRITE_TASKS),
            ("viewer", access.READ),
        ],
    )
    def test_loads_the_project_for_an_admitted_role(self, request_of, project, users, role, level):
        assert access.project_for(request_of(users[role]), str(project.id), level) == project

    @pytest.mark.parametrize(
        ("role", "level"),
        [
            ("member", access.MANAGE),
            ("viewer", access.WRITE_TASKS),
            ("viewer", access.MANAGE),
        ],
    )
    def test_forbids_too_low_a_role(self, request_of, project, users, role, level):
        with pytest.raises(Forbidden):
            access.project_for(request_of(users[role]), str(project.id), level)

    @pytest.mark.parametrize("level", [access.READ, access.WRITE_TASKS, access.MANAGE])
    def test_hides_the_project_from_a_stranger(self, request_of, project, users, level):
        with pytest.raises(Http404):
            access.project_for(request_of(users["stranger"]), str(project.id), level)


class TestProjectEndpointsPerRole:
    @pytest.mark.parametrize("role", ["owner", "member", "viewer"])
    def test_any_role_shows_the_project(self, client, bearer, project, users, role):
        response = answer(client, bearer, users[role], "get", ONE.format(id=project.id))

        assert_matches_contract(response, "get", ONE)
        assert response.status_code == 200
        assert response.json()["data"]["id"] == project.id
        assert response.json()["data"]["user"]["id"] == project.user_id

    @pytest.mark.parametrize("role", ["member", "viewer"])
    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_only_the_owner_changes_the_project(self, client, bearer, project, users, role, method):
        body = {"project": {"name": "Taken over"}}

        response = answer(client, bearer, users[role], method, ONE.format(id=project.id), body)

        assert (response.status_code, response.json()) == (403, FORBIDDEN)
        project.refresh_from_db()
        assert project.name == "Sample Project"

    @pytest.mark.parametrize("role", ["member", "viewer"])
    def test_only_the_owner_deletes_the_project(self, client, bearer, project, users, role):
        response = answer(client, bearer, users[role], "delete", ONE.format(id=project.id))

        assert (response.status_code, response.json()) == (403, FORBIDDEN)
        assert Project.objects.filter(pk=project.id).exists()

    @pytest.mark.parametrize("method", ["get", "put", "delete"])
    def test_a_stranger_gets_not_found(self, client, bearer, project, users, method):
        data = {"project": {"name": "Taken over"}} if method == "put" else None

        response = answer(
            client, bearer, users["stranger"], method, ONE.format(id=project.id), data
        )

        assert_matches_contract(response, method, ONE)
        assert (response.status_code, response.json()) == (404, NOT_FOUND)

    def test_the_owner_deletes_a_shared_project_and_its_memberships(
        self, client, bearer, project, users
    ):
        response = answer(client, bearer, users["owner"], "delete", ONE.format(id=project.id))

        assert response.status_code == 204
        assert not project.memberships.exists()


class TestListOfSharedProjects:
    def test_lists_owned_and_shared_projects_in_id_order(
        self, client, bearer, make_user, make_project, make_membership
    ):
        user = make_user()
        shared_first = make_project()
        own = make_project(user=user)
        shared_last = make_project()
        make_membership(project=shared_first, user=user, role="viewer")
        make_membership(project=shared_last, user=user, role="member")
        make_project()

        response = answer(client, bearer, user, "get", LIST)

        assert_matches_contract(response, "get", LIST)
        assert [project["id"] for project in response.json()["data"]] == [
            shared_first.id,
            own.id,
            shared_last.id,
        ]
        assert response.json()["data"][0]["user"]["id"] == shared_first.user_id

    def test_filters_shared_projects_by_task_status(
        self, client, bearer, make_user, make_project, make_task, make_membership
    ):
        user = make_user()
        done, open_ = make_project(), make_project()
        for shared in (done, open_):
            make_membership(project=shared, user=user, role="viewer")
        task = make_task(project=done, status="completed")
        make_task(project=done)
        make_task(project=open_)

        response = answer(client, bearer, user, "get", f"{LIST}?task_status=completed")

        assert [(p["id"], [t["id"] for t in p["tasks"]]) for p in response.json()["data"]] == [
            (done.id, [task.id])
        ]

    def test_a_project_shared_with_others_is_listed_once_for_its_owner(
        self, client, bearer, owner, project, users
    ):
        response = answer(client, bearer, owner, "get", LIST)

        assert [each["id"] for each in response.json()["data"]] == [project.id]
