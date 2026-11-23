from django.urls import path

from apps.customers import views

app_name = "customers"

urlpatterns = [
    path("", views.customer_list, name="list"),
    path("new/", views.customer_create, name="create"),
    path("<uuid:customer_id>/", views.customer_detail, name="detail"),
    path("<uuid:customer_id>/edit/", views.customer_update, name="update"),
    path(
        "<uuid:customer_id>/status/<str:status>/",
        views.customer_set_status,
        name="set_status",
    ),
]
