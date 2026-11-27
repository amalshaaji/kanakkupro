import json
import logging
import uuid

from django.core.management.base import BaseCommand, CommandError

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.health.alerts import notify_runtime_error


class Command(BaseCommand):
    help = "Send a payload-free test to the configured operator alert inboxes."

    def add_arguments(self, parser):
        parser.add_argument("--send", action="store_true", required=True)
        parser.add_argument("--probe-id", type=uuid.UUID)

    def handle(self, *args, **options):
        record = logging.LogRecord(
            "kanakkupro.alert_test", logging.ERROR, "", 0, "operator_test", (), None
        )
        probe_id = options.get("probe_id")
        record.request_id = probe_id.hex if probe_id else uuid.uuid4().hex
        if probe_id:
            try:
                _, created = AuditEvent.objects.get_or_create(
                    pk=probe_id,
                    defaults={
                        "action": "runtime_alert_probe.requested",
                        "entity_type": "RuntimeAlertProbe",
                        "entity_id": probe_id,
                        "correlation_id": record.request_id,
                    },
                )
            except Exception:
                raise CommandError(
                    "Could not claim the probe; no mail was sent."
                ) from None
            if not created:
                self.stdout.write(
                    json.dumps(
                        {
                            "status": "already_requested",
                            "request_id": record.request_id,
                            "inbox_delivery_verified": False,
                        }
                    )
                )
                return
        result = notify_runtime_error(record)
        if probe_id:
            record_event(
                tenant=None,
                actor=None,
                action="runtime_alert_probe.result",
                entity_type="RuntimeAlertProbe",
                entity_id=probe_id,
                correlation_id=record.request_id,
                metadata={"status": result},
            )
        self.stdout.write(
            json.dumps(
                {
                    "status": result,
                    "request_id": record.request_id,
                    "inbox_delivery_verified": False,
                }
            )
        )
        if result != "provider_accepted":
            raise CommandError("Runtime alert not accepted; review safe status output.")
