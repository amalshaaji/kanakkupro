from django.conf import settings
from django.core.checks import Error, Tags, register
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


@register(Tags.security, deploy=True)
def check_runtime_alert_configuration(app_configs, **kwargs):
    if not settings.RUNTIME_ALERTS_ENABLED:
        return []
    try:
        if not settings.RUNTIME_ALERT_EMAILS:
            raise ValidationError("Missing operator inbox.")
        for address in settings.RUNTIME_ALERT_EMAILS:
            validate_email(address)
    except ValidationError:
        return [
            Error(
                "Configure valid operator inboxes before enabling runtime alerts.",
                id="health.E001",
            )
        ]
    return []
