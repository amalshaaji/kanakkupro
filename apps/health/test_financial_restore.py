"""Opt-in real dump/restore check; creates only a UUID-named local test database."""

import json
import os
import sys
import uuid
from unittest import skipUnless
from urllib.parse import quote

import psycopg
from django.db import connection
from django.test import TransactionTestCase
from psycopg import sql
from scripts.restore_drill import drill, run

from apps.payments.services import reverse_payment
from apps.sales.test_workflow import FinancialFixtures


@skipUnless(
    os.environ.get("RUN_FINANCIAL_RESTORE") == "1", "Opt-in local restore drill"
)
class FinancialRestoreTests(FinancialFixtures, TransactionTestCase):
    def test_nonempty_financial_ledger_survives_real_dump_and_restore(self):
        params = connection.get_connection_params()
        # Never create/drop databases on a hosted or production connection.
        self.assertIn(params.get("host"), {"localhost", "127.0.0.1", "::1"})
        self.assertTrue(params["dbname"].startswith("test_"))
        target_name = "test_restore_" + uuid.uuid4().hex

        def database_url(name):
            user = quote(str(params.get("user", "")), safe="")
            password = quote(str(params.get("password", "")), safe="")
            host = params["host"]
            if ":" in host:
                host = f"[{host}]"
            return (
                f"postgresql://{user}:{password}@{host}:"
                f"{params.get('port') or 5432}/{quote(name, safe='')}"
            )

        source = database_url(params["dbname"])
        target = database_url(target_name)
        invoice = self.issue()
        first = self.pay(invoice, "50.00")
        self.pay(invoice, "68.00")
        reverse_payment(
            tenant=self.tenant,
            actor=self.owner,
            payment_id=first.pk,
            reason="Synthetic restore correction",
            date=self.today,
            key=uuid.uuid4(),
        )
        self.issue(self.note(invoice))
        env = {**os.environ, "DATABASE_URL": source, "RESTORE_DATABASE_URL": target}
        with psycopg.connect(source, autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_name))
            )
            try:
                result = drill(env, pg_bin=os.environ.get("RESTORE_PG_BIN", ""))
                self.assertEqual(result["status"], "verified")
                tables = result["manifest"]["tables"]
                for label, count in {
                    "sales.Invoice": 2,
                    "sales.InvoiceLine": 2,
                    "payments.Payment": 2,
                    "payments.PaymentReversal": 1,
                }.items():
                    self.assertEqual(tables[label]["count"], count)
                self.assertGreater(tables["audit.AuditEvent"]["count"], 0)
                # Recompute balances using application selectors in a new process
                # connected to the restored database, not the source test connection.
                code = """
import django, json
from decimal import Decimal

django.setup()
from apps.tenants.models import Tenant
from apps.sales.models import Invoice
from apps.sales.selectors import financial_summary, invoice_financials
summary = financial_summary(Tenant.objects.get())
invoice = Invoice.objects.get(kind='invoice')
balance = invoice_financials(invoice)
assert summary['invoiced'] == Decimal('88.50')
assert summary['receipts'] == Decimal('68.00')
assert summary['receivables'] == Decimal('20.50')
assert balance['outstanding'] == Decimal('20.50')
assert balance['status'] == 'Partially paid'
print(json.dumps({'financial_reconciliation': 'verified'}))
"""
                output = run(
                    [sys.executable, "-c", code],
                    {
                        **env,
                        "DATABASE_URL": target,
                        "DJANGO_SETTINGS_MODULE": "config.settings.restore",
                    },
                )
                self.assertEqual(
                    json.loads(output)["financial_reconciliation"], "verified"
                )
            finally:
                # This name was generated and created by this test only.
                admin.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(target_name)
                    )
                )
