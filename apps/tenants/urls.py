from django.urls import path

from apps.tenants import views

app_name = "tenants"

urlpatterns = [
    path("create/", views.create_tenant, name="create"),
    path("switch/", views.switch_tenant, name="switch"),
    path("team/", views.team, name="team"),
    path("invitations/<uuid:invitation_id>/revoke/", views.revoke, name="revoke"),
    path("invitations/accept/<str:token>/", views.accept, name="accept_invitation"),
]
