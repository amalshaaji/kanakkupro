from allauth.account.decorators import secure_admin_login
from allauth.mfa.models import Authenticator
from apps.dashboard.views import home
from django.contrib import admin
from django.urls import include, path

admin.site.login = secure_admin_login(admin.site.login)
if admin.site.is_registered(Authenticator):
    admin.site.unregister(Authenticator)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("tenants/", include("apps.tenants.urls")),
    path("customers/", include("apps.customers.urls")),
    path("catalog/", include("apps.catalog.urls")),
    path("invoices/", include("apps.sales.urls")),
    path("payments/", include("apps.payments.urls")),
    path("reports/", include("apps.reports.urls")),
    path("health/", include("apps.health.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("", home, name="home"),
]
