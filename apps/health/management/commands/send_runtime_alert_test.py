import json
import logging
import uuid

from django.core.management.base import BaseCommand, CommandError

from apps.health.alerts import notify_runtime_error


class Command(BaseCommand):
    help = "Send a payload-free test to the configured operator alert inboxes."

    def add_arguments(self, parser):
        parser.add_argument("--send", action="store_true", required=True)

    def handle(self, *args, **options):
        record = logging.LogRecord(
            "kanakkupro.alert_test", logging.ERROR, "", 0, "operator_test", (), None
        )
        record.request_id = uuid.uuid4().hex
        result = notify_runtime_error(record)
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
