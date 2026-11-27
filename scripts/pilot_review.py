"""Seed only a new local review database with synthetic, tenant-isolated records."""

import argparse
import json
import os
import sys
import uuid
from decimal import Decimal


def guard_database(params):
    if params.get("HOST") not in {"127.0.0.1", "localhost", "::1"} or not str(
        params.get("NAME", "")
    ).startswith("test_pilot_review_"):
        raise ValueError("Use a disposable local test_pilot_review_ database.")
    options = params.get("OPTIONS", {})
    if any(
        key in options for key in ("host", "hostaddr", "service", "servicefile")
    ) or any(
        os.environ.get(key) for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")
    ):
        raise ValueError("Review tools refuse connection-host and service overrides.")


def seed_review(invoices, password):
    from allauth.account.models import EmailAddress
    from apps.catalog.models import CatalogItem
    from apps.customers.models import Customer
    from apps.payments.services import record_payment, reverse_payment
    from apps.sales.models import Invoice
    from apps.sales.selectors import financial_summary
    from apps.sales.services import (
        issue_invoice,
        save_draft,
        save_seller_profile,
        today_for,
    )
    from apps.tenants.models import Tenant, TenantMembership
    from django.contrib.auth import get_user_model
    from django.db import connection, transaction

    guard_database(connection.settings_dict)
    if not 1 <= invoices <= 250 or len(password) < 16:
        raise ValueError(
            "Use 1–250 invoices and an ephemeral password of 16+ characters."
        )
    User = get_user_model()
    if User.objects.exists() or Tenant.objects.exists():
        raise ValueError("Review seeding requires an empty database.")
    summaries = []
    with transaction.atomic():
        for label in ("a", "b"):
            owner = User.objects.create_user(
                f"owner-{label}@pilot.example.test", password=password
            )
            EmailAddress.objects.create(
                user=owner, email=owner.email, verified=True, primary=True
            )
            tenant = Tenant.objects.create(
                name=f"Review business {label.upper()}", slug=f"review-{label}"
            )
            TenantMembership.objects.create(tenant=tenant, user=owner, role="owner")
            if label == "a":
                viewer = User.objects.create_user(
                    "viewer@pilot.example.test", password=password
                )
                EmailAddress.objects.create(
                    user=viewer, email=viewer.email, verified=True, primary=True
                )
                TenantMembership.objects.create(
                    tenant=tenant, user=viewer, role="viewer"
                )
            customers = [
                Customer.objects.create(
                    tenant=tenant,
                    created_by=owner,
                    name=f"Review {label.upper()} customer {n:03}",
                    country="IN",
                    billing_address="12 Synthetic Road, Mumbai 400001",
                )
                for n in range(50)
            ]
            items = [
                CatalogItem.objects.create(
                    tenant=tenant,
                    created_by=owner,
                    name=f"Review {label.upper()} service {n:02}",
                    kind="service",
                    unit="hour",
                    price=Decimal("100"),
                    hsn_sac="998314",
                    tax_treatment="taxable",
                    tax_rate=Decimal("18"),
                )
                for n in range(10)
            ]
            save_seller_profile(
                tenant=tenant,
                actor=owner,
                values={
                    "legal_name": tenant.name,
                    "address": "1 Synthetic Road, Mumbai 400001",
                    "gstin": "27AAPFU0939F1ZV",
                    "state_code": "27",
                    "payment_instructions": "Synthetic review data only",
                    "signatory": "Review operator",
                },
            )
            today = today_for(tenant)
            for n in range(invoices):
                customer = customers[n % len(customers)]
                header = {
                    "customer_id": customer.pk,
                    "kind": "invoice",
                    "issue_date": today,
                    "due_date": today,
                    "buyer_gstin": "",
                    "buyer_state": "27",
                    "place_of_supply": "27",
                    "supply_type": "intra_state",
                    "supported_supply": True,
                    "delivery_address": customer.billing_address,
                }
                lines = [
                    {
                        "item_id": items[(n + j) % len(items)].pk,
                        "quantity": "1",
                        "unit_price": "100",
                        "discount": "0",
                    }
                    for j in range(5)
                ]
                draft = save_draft(
                    tenant=tenant,
                    actor=owner,
                    data=header,
                    lines=lines,
                    key=uuid.uuid4(),
                )
                invoice = issue_invoice(
                    tenant=tenant,
                    actor=owner,
                    invoice_id=draft.pk,
                    revision=draft.revision,
                    key=uuid.uuid4(),
                )
                if n % 3:
                    payment = record_payment(
                        tenant=tenant,
                        actor=owner,
                        invoice_id=invoice.pk,
                        values={"amount": "295", "date": today, "method": "bank"},
                        key=uuid.uuid4(),
                    )
                    if n % 10 == 0:
                        reverse_payment(
                            tenant=tenant,
                            actor=owner,
                            payment_id=payment.pk,
                            reason="Synthetic review reversal",
                            date=today,
                            key=uuid.uuid4(),
                        )
                if n % 20 == 0:
                    note = save_draft(
                        tenant=tenant,
                        actor=owner,
                        data={
                            **header,
                            "kind": "credit_note",
                            "parent_id": invoice.pk,
                            "reason": "Synthetic review correction",
                        },
                        lines=[
                            {
                                **lines[0],
                                "quantity": "0.25",
                                "source_line_id": invoice.lines.first().pk,
                            }
                        ],
                        key=uuid.uuid4(),
                    )
                    issue_invoice(
                        tenant=tenant,
                        actor=owner,
                        invoice_id=note.pk,
                        revision=note.revision,
                        key=uuid.uuid4(),
                    )
            summary = financial_summary(tenant)
            summaries.append(
                {
                    key: str(summary[key])
                    for key in ("invoiced", "receipts", "receivables")
                }
            )
    return {
        "status": "synthetic_review_ready",
        "tenants": 2,
        "customers": 100,
        "catalog_items": 20,
        "issued_documents": Invoice.objects.count(),
        "financial_summaries": summaries,
        "outbound_email_enabled": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--invoices", type=int, default=100)
    args = parser.parse_args()
    try:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.review")
        if os.environ["DJANGO_SETTINGS_MODULE"] != "config.settings.review":
            raise ValueError("Use the isolated review settings.")
        import django

        django.setup()
        from django.conf import settings
        from django.core.management import call_command

        guard_database(settings.DATABASES["default"])
        call_command("migrate", verbosity=0)
        print(
            json.dumps(
                seed_review(args.invoices, os.environ.get("PILOT_REVIEW_PASSWORD", ""))
            )
        )
    except Exception:
        print(
            "Review setup failed; use an empty local review database "
            "and private ephemeral password.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
