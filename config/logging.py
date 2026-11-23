import json
import logging
import os
from datetime import UTC, datetime

from apps.common.request_context import request_id_context, tenant_id_context


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, "request_id"):
            record.request_id = request_id_context.get()
        if not hasattr(record, "tenant_id"):
            record.tenant_id = tenant_id_context.get()
        return True


class SafeJsonFormatter(logging.Formatter):
    """Emit structured logs without exception text or request/user payloads."""

    def format(self, record):
        event = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "severity": record.levelname,
            "logger": record.name,
            "message": (
                record.getMessage()
                if record.name.startswith("kanakkupro.")
                else "framework_log"
            ),
            "environment": os.environ.get("APP_ENV", "development"),
            "request_id": getattr(record, "request_id", request_id_context.get()),
            "tenant_id": getattr(record, "tenant_id", tenant_id_context.get()),
        }
        for name in (
            "http_method",
            "http_status",
            "duration_ms",
            "route",
            "dependency",
        ):
            value = getattr(record, name, None)
            if value is not None:
                event[name] = value
        if record.exc_info:
            event["exception_type"] = record.exc_info[0].__name__
        return json.dumps(event, separators=(",", ":"), default=str)
