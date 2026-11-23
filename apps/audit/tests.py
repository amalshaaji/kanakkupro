from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.test import TestCase

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.tenants.models import Tenant


class AuditEventTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(
            "owner@example.com", password="correct-horse"
        )
        self.tenant = Tenant.objects.create(name="Northwind", slug="northwind")

    def test_event_stores_actor_and_entity_without_customer_payload(self):
        event = record_event(
            tenant=self.tenant,
            actor=self.actor,
            action="customer.created",
            entity_type="customer",
            entity_id="b368a3af-110d-4133-8d0d-0a0cbd42f827",
            correlation_id="request-123",
        )

        self.assertEqual(event.tenant, self.tenant)
        self.assertEqual(event.actor, self.actor)
        self.assertEqual(event.action, "customer.created")
        self.assertEqual(event.correlation_id, "request-123")
        self.assertEqual(event.metadata, {})

    def test_instance_update_and_delete_are_rejected(self):
        event = record_event(
            tenant=self.tenant,
            actor=self.actor,
            action="customer.created",
            entity_type="customer",
        )
        event.action = "changed"
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_database_trigger_rejects_bulk_update_and_delete(self):
        event = record_event(
            tenant=self.tenant,
            actor=self.actor,
            action="customer.created",
            entity_type="customer",
        )
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                AuditEvent.objects.filter(pk=event.pk).update(action="changed")
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                AuditEvent.objects.filter(pk=event.pk).delete()
