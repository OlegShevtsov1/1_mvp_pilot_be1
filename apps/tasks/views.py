from django.http import Http404, HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import ValidationFailed
from apps.projects.access import READ, WRITE_TASKS, project_for
from apps.projects.params import permitted, record_id
from apps.tasks import dependencies, labels, serializers, services
from apps.tasks.models import Label, Task

PERMITTED = ("name", "description", "status")
DEPENDENCY = ("task_id",)
LABEL_PERMITTED = ("name", "color")
TASK_LABEL = ("label_id",)


def task_for(request, project_id, id, level):
    """A task of a project the caller sees with a role admitted to `level`; a task of another
    project answers 404 like a missing one (AC-17)."""
    task = project_for(request, project_id, level).tasks.filter(pk=record_id(id)).first()
    if task is None:
        raise Http404
    return task


def task_params(request):
    return permitted(request, "task", Task, PERMITTED)


class TaskListView(APIView):
    def get(self, request, project_id):
        tasks = services.index(project_for(request, project_id, READ))
        return Response({"data": [serializers.task_json(task) for task in tasks]})

    def post(self, request, project_id):
        project = project_for(request, project_id, WRITE_TASKS)
        result = services.create(project, task_params(request))
        if result.errors:
            raise ValidationFailed(result.errors)
        return Response({"data": serializers.task_json(result.task)}, status=201)


class TaskDetailView(APIView):
    def get(self, request, project_id, id):
        task = services.show(task_for(request, project_id, id, READ))
        return Response({"data": serializers.task_json(task)})

    def put(self, request, project_id, id):
        task = task_for(request, project_id, id, WRITE_TASKS)
        result = services.update(task, task_params(request))
        if result.errors:
            raise ValidationFailed(result.errors)
        return Response({"data": serializers.task_json(result.task)})

    patch = put

    def delete(self, request, project_id, id):
        result = services.delete(task_for(request, project_id, id, WRITE_TASKS))
        if result.errors:
            raise ValidationFailed(result.errors)
        return HttpResponse(status=204)


def label_for(request, project_id, id, level):
    """A label of a project the caller sees with a role admitted to `level`; a label of another
    project answers 404 like a missing one."""
    label = project_for(request, project_id, level).labels.filter(pk=record_id(id)).first()
    if label is None:
        raise Http404
    return label


def listed(project, tasks):
    return Response(
        {"data": [serializers.task_json(each) for each in services.with_project(project, tasks)]}
    )


class DependencyListView(APIView):
    def get(self, request, project_id, id):
        task = task_for(request, project_id, id, READ)
        return listed(task.project, task.blocked_by.all())

    def post(self, request, project_id, id):
        task = task_for(request, project_id, id, WRITE_TASKS)
        params = permitted(request, "dependency", Task, DEPENDENCY, wrapped=DEPENDENCY)
        blocker = task.project.tasks.filter(pk=record_id(params.get("task_id") or "")).first()
        result = dependencies.add(task, blocker)
        if result.errors:
            raise ValidationFailed(result.errors)
        return Response({"data": serializers.task_json(services.load(blocker.pk))}, status=201)


class DependencyDetailView(APIView):
    def delete(self, request, project_id, id, blocker_id):
        task = task_for(request, project_id, id, WRITE_TASKS)
        blocker = task.blocked_by.filter(pk=record_id(blocker_id)).first()
        if blocker is None:
            raise Http404
        dependencies.remove(task, blocker)
        return HttpResponse(status=204)


def label_params(request):
    return permitted(request, "label", Label, LABEL_PERMITTED)


class LabelListView(APIView):
    def get(self, request, project_id):
        project = project_for(request, project_id, READ)
        return Response({"data": [serializers.label_json(each) for each in labels.index(project)]})

    def post(self, request, project_id):
        project = project_for(request, project_id, WRITE_TASKS)
        result = labels.create(project, label_params(request))
        if result.errors:
            raise ValidationFailed(result.errors)
        return Response({"data": serializers.label_json(result.label)}, status=201)


class LabelDetailView(APIView):
    def get(self, request, project_id, id):
        return Response({"data": serializers.label_json(label_for(request, project_id, id, READ))})

    def put(self, request, project_id, id):
        label = label_for(request, project_id, id, WRITE_TASKS)
        result = labels.update(label, label_params(request))
        if result.errors:
            raise ValidationFailed(result.errors)
        return Response({"data": serializers.label_json(result.label)})

    patch = put

    def delete(self, request, project_id, id):
        labels.delete(label_for(request, project_id, id, WRITE_TASKS))
        return HttpResponse(status=204)


class LabelTasksView(APIView):
    def get(self, request, project_id, id):
        label = label_for(request, project_id, id, READ)
        return listed(label.project, label.tasks.all())


class TaskLabelListView(APIView):
    def get(self, request, project_id, id):
        task = task_for(request, project_id, id, READ)
        return Response({"data": [serializers.label_json(each) for each in labels.of_task(task)]})

    def post(self, request, project_id, id):
        task = task_for(request, project_id, id, WRITE_TASKS)
        params = permitted(request, "label", Label, TASK_LABEL, wrapped=TASK_LABEL)
        label = task.project.labels.filter(pk=record_id(params.get("label_id") or "")).first()
        result = labels.attach(task, label)
        if result.errors:
            raise ValidationFailed(result.errors)
        return Response({"data": serializers.label_json(result.label)}, status=201)


class TaskLabelDetailView(APIView):
    def delete(self, request, project_id, id, label_id):
        task = task_for(request, project_id, id, WRITE_TASKS)
        label = task.labels.filter(pk=record_id(label_id)).first()
        if label is None:
            raise Http404
        labels.detach(task, label)
        return HttpResponse(status=204)
