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


@skipUnless(
    os.environ.get("RUN_FINANCIAL_RESTORE") == "1"
    and bool(os.environ.get("RESTORE_AGE_BIN")),
    "Opt-in encrypted local restore drill",
)
class EncryptedFinancialRestoreTests(FinancialFixtures, TransactionTestCase):
    def test_encrypted_dump_restores_ledger_with_offline_recovery_key(self):
        import io
        import tempfile
        from pathlib import Path

        from scripts.encrypted_backup import backup, command
        from scripts.restore_drill import client_env, snapshot

        from apps.health.management.commands.restore_manifest import manifest
        from apps.health.test_encrypted_backup import storage_client

        params = connection.get_connection_params()
        self.assertIn(params.get("host"), {"localhost", "127.0.0.1", "::1"})
        self.assertTrue(params["dbname"].startswith("test_"))
        source = "postgresql://{}:{}@{}:{}/{}".format(
            quote(str(params.get("user", "")), safe=""),
            quote(str(params.get("password", "")), safe=""),
            "[::1]" if params["host"] == "::1" else params["host"],
            params.get("port") or 5432,
            quote(params["dbname"], safe=""),
        )
        target_name = "test_restore_" + uuid.uuid4().hex
        target = source.rsplit("/", 1)[0] + "/" + target_name
        invoice = self.issue()
        first = self.pay(invoice, "50.00")
        self.pay(invoice, "68.00")
        reverse_payment(
            tenant=self.tenant,
            actor=self.owner,
            payment_id=first.pk,
            reason="Synthetic encrypted restore",
            date=self.today,
            key=uuid.uuid4(),
        )
        self.issue(self.note(invoice))
        expected = manifest()
        client = storage_client()
        age_bin = os.environ["RESTORE_AGE_BIN"]
        keygen = (
            str(Path(age_bin).with_name("age-keygen"))
            if "/" in age_bin
            else "age-keygen"
        )
        pg_bin = Path(os.environ.get("RESTORE_PG_BIN", ""))
        with tempfile.TemporaryDirectory() as folder:
            identity = Path(folder) / "identity.txt"
            command([keygen, "-o", str(identity)], dict(os.environ))
            public = run([keygen, "-y", str(identity)], dict(os.environ)).strip()
            captured = []

            def upload(**kwargs):
                content = kwargs["Body"].read()
                captured.append(content)
                client.head_object.return_value = {"ContentLength": len(content)}
                client.get_object.return_value = {"Body": io.BytesIO(content)}
                return {"VersionId": "synthetic-version"}

            client.put_object.side_effect = upload
            result = backup(
                {
                    **os.environ,
                    "BACKUP_DATABASE_URL": source,
                    "BACKUP_AGE_RECIPIENT": public,
                },
                client,
                pg_bin=str(pg_bin),
                age_bin=age_bin,
                allow_local=True,
            )
            self.assertEqual(result["status"], "uploaded_and_verified")
            self.assertTrue(captured[0].startswith(b"age-encryption.org/v1"))
            encrypted = Path(folder) / "backup.age"
            plain = Path(folder) / "restore.dump"
            encrypted.write_bytes(captured[0])
            command(
                [
                    age_bin,
                    "--decrypt",
                    "--identity",
                    str(identity),
                    "--output",
                    str(plain),
                    str(encrypted),
                ],
                dict(os.environ),
            )
            with psycopg.connect(source, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_name))
                )
                try:
                    command(
                        [
                            str(pg_bin / "pg_restore"),
                            "--exit-on-error",
                            "--single-transaction",
                            "--no-owner",
                            "--no-privileges",
                            "--dbname",
                            target_name,
                            str(plain),
                        ],
                        client_env(target, dict(os.environ)),
                    )
                    self.assertEqual(snapshot(target, dict(os.environ)), expected)
                finally:
                    admin.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                            sql.Identifier(target_name)
                        )
                    )
