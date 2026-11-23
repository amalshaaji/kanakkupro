from apps.dashboard.views import home
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("tenants/", include("apps.tenants.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("", home, name="home"),
]
