from django.urls import include, path
from drf_spectacular.views import SpectacularSwaggerView

from config.views import api_docs, health

urlpatterns = [
    path("health", health),
    path("api-docs/v1/swagger.json", api_docs, name="schema"),
    path("api-docs", SpectacularSwaggerView.as_view(url_name="schema")),
    path("", include("apps.users.urls")),
    path("", include("apps.projects.urls")),
    path("", include("apps.tasks.urls")),
    path("", include("apps.errors.urls")),
    path("", include("apps.admin_smoke.urls")),
]

handler404 = "apps.common.views.not_found"
handler500 = "apps.common.views.server_error"
