---
name: Django Patterns
description: "Use when building Python web applications with Django — covers models, views, ORM, migrations, admin, Django REST Framework, and testing."
---

## Overview

Django is a batteries-included Python web framework that follows the model-template-view (MTV) pattern, providing an ORM, admin interface, authentication, and migrations out of the box.

## When to Use

- **Django** -- Full-featured web apps with admin, auth, ORM, and rapid prototyping
- **FastAPI** -- API-only services needing async and automatic OpenAPI docs
- **Flask** -- Lightweight apps where you want to pick your own components

## Core Patterns

### Models and ORM

```python
from django.db import models


class Article(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey("auth.User", on_delete=models.CASCADE)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-published_at"]


# Queries
articles = Article.objects.filter(author=user).select_related("author")
```

### Views (Class-Based and Function-Based)

```python
from django.views.generic import ListView
from django.http import JsonResponse


class ArticleList(ListView):
    model = Article
    paginate_by = 20


def api_articles(request):
    qs = Article.objects.values("id", "title")
    return JsonResponse(list(qs), safe=False)
```

### Django REST Framework Serializers

```python
from rest_framework import serializers, viewsets


class ArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Article
        fields = ["id", "title", "author", "published_at"]


class ArticleViewSet(viewsets.ModelViewSet):
    queryset = Article.objects.all()
    serializer_class = ArticleSerializer
```

### Middleware

```python
class TimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        import time

        start = time.time()
        response = self.get_response(request)
        response["X-Request-Time"] = f"{time.time() - start:.3f}s"
        return response
```

## Project Structure

```
myproject/
  manage.py
  config/              # Project settings package
    settings/
      base.py, dev.py, prod.py
    urls.py, wsgi.py
  apps/
    articles/
      models.py, views.py, urls.py
      serializers.py, admin.py
      tests/, migrations/
```

## Testing

```python
from django.test import TestCase, Client


class ArticleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("testuser", password="pass")

    def test_list_articles(self):
        resp = self.client.get("/articles/")
        self.assertEqual(resp.status_code, 200)


# Use pytest-django for fixtures
@pytest.mark.django_db
def test_create_article(client, django_user_model):
    user = django_user_model.objects.create_user("u", password="p")
    assert Article.objects.count() == 0
```

## Common Pitfalls

| Pitfall | Fix |
|---|---|
| N+1 queries | Use `select_related()` (FK) and `prefetch_related()` (M2M) |
| Fat views | Move logic into model methods, managers, or service layers |
| Forgetting migrations | Run `makemigrations` after every model change; commit migration files |
| Hardcoded settings | Use `django-environ` or split settings for dev/prod |
| Ignoring `on_delete` | Always set explicit `on_delete` on ForeignKey fields |

## Attribution

**Original** -- Datatide, MIT licensed.
