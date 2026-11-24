import time

from allauth.mfa.signals import (
    authenticator_added,
    authenticator_removed,
    authenticator_reset,
    authenticator_used,
)
from django.dispatch import receiver

from apps.accounts.security import ADMIN_MFA_SESSION_KEY
from apps.audit.services import record_event


@receiver(authenticator_used, dispatch_uid="kanakkupro.mfa.used")
def mfa_used(sender, request, user, authenticator, **kwargs):
    request.session[ADMIN_MFA_SESSION_KEY] = {
        "user": str(user.pk),
        "authenticator": authenticator.pk,
        "at": time.time(),
    }
    record_event(
        tenant=None,
        actor=user,
        action="security.mfa_used",
        entity_type="account",
        entity_id=user.pk,
        correlation_id=getattr(request, "request_id", ""),
        metadata={"type": authenticator.type},
    )


@receiver(authenticator_added, dispatch_uid="kanakkupro.mfa.added")
@receiver(authenticator_removed, dispatch_uid="kanakkupro.mfa.removed")
@receiver(authenticator_reset, dispatch_uid="kanakkupro.mfa.reset")
def mfa_changed(sender, request, user, authenticator, signal, **kwargs):
    request.session.pop(ADMIN_MFA_SESSION_KEY, None)
    actions = {
        authenticator_added: "added",
        authenticator_removed: "removed",
        authenticator_reset: "reset",
    }
    record_event(
        tenant=None,
        actor=user,
        action=f"security.mfa_{actions[signal]}",
        entity_type="account",
        entity_id=user.pk,
        correlation_id=getattr(request, "request_id", ""),
        metadata={"type": authenticator.type},
    )
