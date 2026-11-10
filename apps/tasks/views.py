from django.http import Http404, HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import ValidationFailed
from apps.projects.params import permitted, record_id
from apps.projects.views import owned_project
from apps.tasks import serializers, services
from apps.tasks.models import Task

PERMITTED = ("name", "description", "status")


def owned_task(request, project_id, id):
    """A task of the caller's project; any other task answers 404 like a missing one (AC-17)."""
    task = owned_project(request, project_id).tasks.filter(pk=record_id(id)).first()
    if task is None:
        raise Http404
    return task


def task_params(request):
    return permitted(request, "task", Task, PERMITTED)


class TaskListView(APIView):
    def get(self, request, project_id):
        tasks = services.index(owned_project(request, project_id))
        return Response({"data": [serializers.task_json(task) for task in tasks]})

    def post(self, request, project_id):
        project = owned_project(request, project_id)
        result = services.create(project, task_params(request))
        if result.errors:
            raise ValidationFailed(result.errors)
        return Response({"data": serializers.task_json(result.task)}, status=201)


class TaskDetailView(APIView):
    def get(self, request, project_id, id):
        task = services.show(owned_task(request, project_id, id))
        return Response({"data": serializers.task_json(task)})

    def put(self, request, project_id, id):
        task = owned_task(request, project_id, id)
        result = services.update(task, task_params(request))
        if result.errors:
            raise ValidationFailed(result.errors)
        return Response({"data": serializers.task_json(result.task)})

    patch = put

    def delete(self, request, project_id, id):
        result = services.delete(owned_task(request, project_id, id))
        if result.errors:
            raise ValidationFailed(result.errors)
        return HttpResponse(status=204)
