import logging

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

logger = logging.getLogger("kanakkupro.health")


@require_GET
@never_cache
def live(request):
    return JsonResponse(
        {"status": "ok", "request_id": getattr(request, "request_id", "-")}
    )


@require_GET
@never_cache
def ready(request):
    dependency = "postgresql"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                raise RuntimeError(
                    "Database readiness probe returned an invalid result."
                )
        dependency = "authentication_cache"
        # Read-only probe: production allauth throttling and TOTP replay
        # protection require the shared cache table, not just a live database.
        cache.get("kanakkupro.health.readiness")
    except Exception:
        logger.warning(
            "readiness_check_failed",
            extra={
                "request_id": getattr(request, "request_id", "-"),
                "dependency": dependency,
            },
        )
        return JsonResponse(
            {
                "status": "unavailable",
                "request_id": getattr(request, "request_id", "-"),
            },
            status=503,
        )

    return JsonResponse(
        {"status": "ok", "request_id": getattr(request, "request_id", "-")}
    )
