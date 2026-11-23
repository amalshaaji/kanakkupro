from django.urls import path

from apps.sales import views

app_name = "sales"
urlpatterns = [
    path("", views.invoice_list, name="list"),
    path("new/", views.invoice_edit, name="create"),
    path("settings/", views.invoice_settings, name="settings"),
    path("<uuid:invoice_id>/", views.invoice_detail, name="detail"),
    path("<uuid:invoice_id>/edit/", views.invoice_edit, name="update"),
    path("<uuid:invoice_id>/issue/", views.issue, name="issue"),
    path("<uuid:invoice_id>/pdf/", views.invoice_pdf, name="pdf"),
]
