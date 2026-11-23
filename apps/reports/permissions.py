from functools import wraps

from django.core.exceptions import PermissionDenied

from apps.tenants.permissions import membership_has_permission


def tenant_permission_required(permission):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not membership_has_permission(
                getattr(request, "tenant_membership", None), permission
            ):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
