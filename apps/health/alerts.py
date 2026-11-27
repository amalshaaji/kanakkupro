"""Bounded operator alerts containing no request payloads or exception messages."""

import json
import logging
import re
import threading
from datetime import UTC, datetime

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMessage, get_connection

from apps.common.request_context import request_id_context

delivery_logger = logging.getLogger("kanakkupro.runtime_alert_delivery")
RATE_LIMIT_KEY = "runtime-alert:global:v1"
RATE_LIMIT_SECONDS = 300
_emitting = threading.local()


def alert_payload(record):
    request_id = getattr(record, "request_id", request_id_context.get())
    request_id = request_id if re.fullmatch(r"[0-9a-f]{32}", str(request_id)) else "-"
    exception_type = record.exc_info[0].__name__ if record.exc_info else "unknown"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", exception_type):
        exception_type = "unknown"
    status = getattr(record, "status_code", getattr(record, "http_status", None))
    status = status if isinstance(status, int) and 500 <= status <= 599 else None
    environment = getattr(settings, "DEPLOYMENT_ENVIRONMENT", "unknown")
    if environment not in {"development", "staging", "production", "test"}:
        environment = "unknown"
    return {
        "event": (
            "operator_test"
            if record.name == "kanakkupro.alert_test"
            else "runtime_error"
        ),
        "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
        "environment": environment,
        "request_id": request_id,
        "http_status": status,
        "exception_type": exception_type,
    }


def notify_runtime_error(record):
    if not settings.RUNTIME_ALERTS_ENABLED or record.levelno < logging.ERROR:
        return "disabled"
    recipients = settings.RUNTIME_ALERT_EMAILS
    if not recipients:
        return "unconfigured"
    try:
        permitted = cache.add(RATE_LIMIT_KEY, True, timeout=RATE_LIMIT_SECONDS)
    except Exception:
        delivery_logger.warning("runtime_alert_cache_unavailable")
        return "unavailable"
    if not permitted:
        return "throttled"
    try:
        # Bypass SafeSMTPBackend's application logger to avoid recursive alerts.
        backend = settings.EMAIL_BACKEND
        if backend == "apps.accounts.delivery.SafeSMTPBackend":
            backend = "django.core.mail.backends.smtp.EmailBackend"
        with get_connection(backend=backend, timeout=3) as connection:
            accepted = EmailMessage(
                subject="KanakkuPro runtime alert",
                body=json.dumps(alert_payload(record), sort_keys=True),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=recipients,
                connection=connection,
            ).send(fail_silently=False)
        if accepted != 1:
            raise RuntimeError("Alert was not accepted.")
    except Exception:
        # Keep the throttle on failure too: an SMTP outage must not cause a storm.
        delivery_logger.warning("runtime_alert_delivery_unavailable")
        return "unavailable"
    delivery_logger.info("runtime_alert_provider_accepted")
    return "provider_accepted"


class RuntimeAlertHandler(logging.Handler):
    def emit(self, record):
        if getattr(_emitting, "active", False):
            return
        _emitting.active = True
        try:
            notify_runtime_error(record)
        except Exception:
            # Reporting must never replace the original application response.
            delivery_logger.warning("runtime_alert_unavailable")
        finally:
            _emitting.active = False
