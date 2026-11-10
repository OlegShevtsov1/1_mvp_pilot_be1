from django.urls import path

from apps.admin_smoke.views import glitchtip_smoke

urlpatterns = [
    path("admin/glitchtip_smoke/<str:kind>", glitchtip_smoke),
]
