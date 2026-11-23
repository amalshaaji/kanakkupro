import logging
import time
import uuid

from apps.common.request_context import request_id_context

http_logger = logging.getLogger("kanakkupro.http")


class RequestIDMiddleware:
    """Assign an untrusted-input-independent request ID for support and audit."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid.uuid4().hex
        context_token = request_id_context.set(request.request_id)
        started_at = time.perf_counter()
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request.request_id
            tenant = getattr(request, "tenant", None)
            resolver_match = getattr(request, "resolver_match", None)
            http_logger.info(
                "http_request_completed",
                extra={
                    "http_method": request.method,
                    "http_status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "route": getattr(resolver_match, "view_name", "unresolved"),
                    "tenant_id": str(tenant.pk) if tenant else "-",
                },
            )
            return response
        finally:
            request_id_context.reset(context_token)
