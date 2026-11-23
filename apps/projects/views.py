from django.http import Http404, HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import Forbidden, ResourceNotFound, ValidationFailed
from apps.projects import members, serializers, services
from apps.projects.access import MANAGE, READ, allowed, project_for, role_of
from apps.projects.models import Membership, Project
from apps.projects.params import permitted, record_id

PERMITTED = ("name", "description")
MEMBER_CREATE = ("email", "role")
MEMBER_UPDATE = ("role",)


def project_params(request):
    return permitted(request, "project", Project, PERMITTED)


class ProjectListView(APIView):
    def get(self, request):
        projects = services.index(request.user, request.query_params.get("task_status"))
        return Response({"data": [serializers.project_json(project) for project in projects]})

    def post(self, request):
        result = services.create(request.user, project_params(request))
        if result.errors:
            raise ValidationFailed(result.errors)
        return Response({"data": serializers.project_json(result.project)}, status=201)


class ProjectDetailView(APIView):
    def get(self, request, id):
        project = services.show(project_for(request, id, READ))
        return Response({"data": serializers.project_json(project)})

    def put(self, request, id):
        project = project_for(request, id, MANAGE)
        result = services.update(project, project_params(request))
        if result.errors:
            raise ValidationFailed(result.errors)
        return Response({"data": serializers.project_json(result.project)})

    patch = put

    def delete(self, request, id):
        result = services.delete(project_for(request, id, MANAGE))
        if result.errors:
            raise ValidationFailed(result.errors)
        return HttpResponse(status=204)


def project_membership(project, raw_id):
    """A membership of the project; one of another project answers 404 like a missing one."""
    membership = project.memberships.filter(pk=record_id(raw_id)).first()
    if membership is None:
        raise Http404
    return membership


class MemberListView(APIView):
    def get(self, request, project_id):
        memberships = members.index(project_for(request, project_id, READ))
        return Response({"data": [serializers.member_json(each) for each in memberships]})

    def post(self, request, project_id):
        project = project_for(request, project_id, MANAGE)
        params = permitted(request, "member", Membership, MEMBER_CREATE, wrapped=MEMBER_CREATE)
        user = members.user_by_email(params.get("email"))
        if user is None:
            raise ResourceNotFound("User")
        result = members.add(project, user, params.get("role"))
        if result.errors:
            raise ValidationFailed(result.errors)
        return Response({"data": serializers.member_json(result.membership)}, status=201)


class MemberDetailView(APIView):
    def put(self, request, project_id, id):
        membership = project_membership(project_for(request, project_id, MANAGE), id)
        result = members.update(membership, permitted(request, "member", Membership, MEMBER_UPDATE))
        if result.errors:
            raise ValidationFailed(result.errors)
        return Response({"data": serializers.member_json(result.membership)})

    patch = put

    def delete(self, request, project_id, id):
        """The owner removes anyone; a member or viewer may remove only themselves (leave)."""
        project = project_for(request, project_id, READ)
        membership = project_membership(project, id)
        if membership.user_id != request.user.id and not allowed(
            role_of(request.user, project), MANAGE
        ):
            raise Forbidden()
        members.remove(membership)
        return HttpResponse(status=204)
