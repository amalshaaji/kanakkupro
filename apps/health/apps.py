from django.apps import AppConfig


class HealthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.health"
    label = "health"

    def ready(self):
        from . import checks  # noqa: F401
