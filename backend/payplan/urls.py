from django.contrib import admin
from django.urls import include, path

from .health import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/", include("apps.plans.urls")),
    path("api/", include("apps.payments.urls")),
    path("api/ops/", include("apps.ops.urls")),
]
