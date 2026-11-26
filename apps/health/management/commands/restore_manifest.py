import hashlib
import json

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder

MODELS = (
    "accounts.User",
    "account.EmailAddress",
    "mfa.Authenticator",
    "tenants.Tenant",
    "tenants.TenantMembership",
    "tenants.Invitation",
    "tenants.PilotCheck",
    "tenants.PilotFeedback",
    "customers.Customer",
    "catalog.CatalogItem",
    "sales.SellerProfile",
    "sales.Invoice",
    "sales.InvoiceLine",
    "sales.InvoiceSequence",
    "sales.FinancialCommand",
    "payments.Payment",
    "payments.PaymentReversal",
    "audit.AuditEvent",
)


def manifest():
    if connection.in_atomic_block:
        raise CommandError("Run the manifest outside an existing transaction.")
    tables = {}
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for label in MODELS:
            model = apps.get_model(label)
            digest = hashlib.sha256()
            count = 0
            for row in model.objects.order_by("pk").values().iterator(chunk_size=1000):
                digest.update(
                    json.dumps(
                        row, sort_keys=True, default=str, separators=(",", ":")
                    ).encode()
                )
                digest.update(b"\n")
                count += 1
            tables[label] = {"count": count, "sha256": digest.hexdigest()}
        migrations = sorted(
            [list(pair) for pair in MigrationRecorder(connection).applied_migrations()]
        )
    return {"version": 1, "tables": tables, "migrations": migrations}


class Command(BaseCommand):
    help = "Read-only counts and digests for authorized restore verification."

    def add_arguments(self, parser):
        parser.add_argument("--all-tenants", action="store_true", required=True)

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(manifest(), sort_keys=True))
