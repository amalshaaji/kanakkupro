from contextvars import ContextVar

request_id_context = ContextVar("request_id", default="-")
tenant_id_context = ContextVar("tenant_id", default="-")
