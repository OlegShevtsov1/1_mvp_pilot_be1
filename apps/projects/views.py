from django.http import Http404, HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import ValidationFailed
from apps.projects import serializers, services
from apps.projects.models import Project
from apps.projects.params import permitted, record_id

PERMITTED = ("name", "description")


def owned_project(request, raw_id):
    """The caller's project; another user's project answers 404 like a missing one (AC-17)."""
    project = request.user.projects.filter(pk=record_id(raw_id)).first()
    if project is None:
        raise Http404
    return project


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
        project = services.show(owned_project(request, id))
        return Response({"data": serializers.project_json(project)})

    def put(self, request, id):
        project = owned_project(request, id)
        result = services.update(project, project_params(request))
        if result.errors:
            raise ValidationFailed(result.errors)
        return Response({"data": serializers.project_json(result.project)})

    patch = put

    def delete(self, request, id):
        result = services.delete(owned_project(request, id))
        if result.errors:
            raise ValidationFailed(result.errors)
        return HttpResponse(status=204)
