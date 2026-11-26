"""Diagnose SMTP setup without sending a message or echoing credentials."""

import json
from smtplib import SMTPAuthenticationError, SMTPException

from django.core.mail import get_connection
from django.core.mail.backends.smtp import EmailBackend
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Verify the configured SMTP TLS connection and authentication; sends no email."
    )

    def handle(self, *args, **options):
        try:
            backend = get_connection(fail_silently=False)
        except Exception:
            raise CommandError(
                "Review the configured SMTP backend privately."
            ) from None
        if not isinstance(backend, EmailBackend):
            raise CommandError("Configure an SMTP backend before running this check.")
        if not backend.host or not backend.username or not backend.password:
            raise CommandError(
                "Set EMAIL_HOST, EMAIL_HOST_USER and EMAIL_HOST_PASSWORD."
            )
        if bool(backend.use_tls) == bool(backend.use_ssl):
            raise CommandError("Enable exactly one of EMAIL_USE_TLS and EMAIL_USE_SSL.")
        outcome = "authenticated"
        try:
            backend.open()
        except SMTPAuthenticationError:
            outcome = "authentication_rejected"
        except (SMTPException, OSError):
            outcome = "connection_or_tls_failed"
        finally:
            try:
                backend.close()
            except Exception:
                pass
        self.stdout.write(
            json.dumps(
                {"smtp": outcome, "email_sent": False, "delivery_verified": False}
            )
        )
        if outcome != "authenticated":
            raise CommandError(
                "SMTP check failed. Review provider access and credentials privately."
            )
