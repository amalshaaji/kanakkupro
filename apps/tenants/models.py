import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone


class Tenant(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        SUSPENDED = "suspended", "Suspended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    country = models.CharField(max_length=2, default="IN")
    currency = models.CharField(max_length=3, default="INR")
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class TenantMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MANAGER = "manager", "Manager"
        STAFF = "staff", "Staff"
        VIEWER = "viewer", "Viewer"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.PROTECT, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="tenant_memberships",
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "user"], name="uq_membership_tenant_user"
            )
        ]
        indexes = [
            models.Index(fields=["user", "status"], name="membership_user_status_idx")
        ]

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    def __str__(self):
        return f"{self.user} — {self.tenant} ({self.get_role_display()})"


class Invitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.PROTECT, related_name="invitations"
    )
    email = models.EmailField(max_length=254)
    role = models.CharField(
        max_length=20,
        choices=[
            choice
            for choice in TenantMembership.Role.choices
            if choice[0] != TenantMembership.Role.OWNER
        ],
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_tenant_invitations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_tenant_invitations",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                "tenant",
                Lower("email"),
                condition=Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name="uq_pending_invite_tenant_email_ci",
            )
        ]
        indexes = [
            models.Index(
                fields=["tenant", "expires_at"], name="invitation_tenant_expiry_idx"
            )
        ]

    @property
    def is_pending(self):
        return (
            self.accepted_at is None
            and self.revoked_at is None
            and self.expires_at > timezone.now()
        )

    def __str__(self):
        return f"{self.email} → {self.tenant} ({self.get_role_display()})"


class PilotCheck(models.Model):
    class Code(models.TextChoices):
        VERIFICATION = "verification", "Verification email received"
        RESET = "reset", "Password reset email received"
        INVITATION = "invitation", "Invitation email received"
        PDF = "pdf", "Invoice PDF reviewed"
        RECONCILIATION = (
            "reconciliation",
            "Invoice, payment and report totals reconciled",
        )

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    code = models.CharField(max_length=20, choices=Code.choices)
    confirmed = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reviewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uq_pilot_check_tenant_code"
            ),
            models.CheckConstraint(
                condition=Q(
                    code__in=[
                        "verification",
                        "reset",
                        "invitation",
                        "pdf",
                        "reconciliation",
                    ]
                ),
                name="pilot_check_valid_code",
            ),
        ]


class PilotFeedback(models.Model):
    class Kind(models.TextChoices):
        ISSUE = "issue", "Something isn't working"
        IDEA = "idea", "Improvement idea"

    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High — blocks a workflow"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        INVESTIGATING = "investigating", "Investigating"
        RESOLVED = "resolved", "Resolved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    severity = models.CharField(max_length=8, choices=Severity.choices)
    description = models.TextField(max_length=2000)
    request_id = models.CharField(max_length=32, blank=True)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.OPEN
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(
                fields=["tenant", "status", "created_at"],
                name="pilot_feedback_tenant_status",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=["issue", "idea"]),
                name="pilot_feedback_valid_kind",
            ),
            models.CheckConstraint(
                condition=Q(severity__in=["low", "medium", "high"]),
                name="pilot_feedback_valid_severity",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["open", "investigating", "resolved"]),
                name="pilot_feedback_valid_status",
            ),
        ]
