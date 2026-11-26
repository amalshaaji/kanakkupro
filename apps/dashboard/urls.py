from django.urls import path

from .pilot_views import feedback_status, pilot_guide
from .views import dashboard

app_name = "dashboard"

urlpatterns = [
    path("", dashboard, name="index"),
    path("pilot/", pilot_guide, name="pilot"),
    path(
        "pilot/feedback/<uuid:feedback_id>/status/",
        feedback_status,
        name="feedback_status",
    ),
]
