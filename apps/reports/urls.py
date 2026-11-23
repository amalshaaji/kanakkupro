from django.urls import path

from apps.reports import views

app_name = "reports"

urlpatterns = [
    path("", views.report_home, name="home"),
    path("exports/customers.csv", views.export_customers, name="export_customers"),
    path("exports/catalog.csv", views.export_catalog, name="export_catalog"),
]
