from django.urls import path

from apps.catalog import views

app_name = "catalog"

urlpatterns = [
    path("", views.item_list, name="list"),
    path("new/", views.item_create, name="create"),
    path("<uuid:item_id>/", views.item_detail, name="detail"),
    path("<uuid:item_id>/edit/", views.item_update, name="update"),
    path(
        "<uuid:item_id>/active/<str:active>/", views.item_set_active, name="set_active"
    ),
]
