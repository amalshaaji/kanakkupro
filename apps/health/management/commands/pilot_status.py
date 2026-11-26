import json
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from apps.tenants.models import Tenant
from apps.tenants.pilot import pilot_progress


class Command(BaseCommand):
    help = "Read-only business pilot preparation report; never grants pilot admission."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=uuid.UUID, required=True)
        parser.add_argument("--reviewer", type=uuid.UUID, required=True)

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(pk=options["tenant"])
            reviewer = get_user_model().objects.get(pk=options["reviewer"])
            progress = pilot_progress(tenant, reviewer)
        except (Tenant.DoesNotExist, get_user_model().DoesNotExist, PermissionDenied):
            raise CommandError(
                "An active Owner/Admin reviewer for this business is required."
            ) from None
        report = {
            "business_checks_complete": progress["business_checks_complete"],
            "completed": progress["completed"],
            "total": progress["total"],
            "open_high_issues": progress["open_high_issues"],
            "first_invoice_minutes_since_business_creation": progress[
                "first_invoice_minutes"
            ],
            "operator_admission_verified": False,
            "remaining_operator_evidence": [
                "live_email_delivery",
                "monitoring_alert_delivery",
                "provider_backup_restore",
                "security_and_acceptance_review",
            ],
        }
        self.stdout.write(json.dumps(report, sort_keys=True))
