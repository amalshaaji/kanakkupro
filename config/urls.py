from apps.dashboard.views import home
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("tenants/", include("apps.tenants.urls")),
    path("customers/", include("apps.customers.urls")),
    path("catalog/", include("apps.catalog.urls")),
    path("reports/", include("apps.reports.urls")),
    path("health/", include("apps.health.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("", home, name="home"),
]
