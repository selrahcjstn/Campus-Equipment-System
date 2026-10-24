from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.borrowing.services import approve_request
from apps.dashboard.models import AuditLog
from apps.inventory.models import EquipmentUnit
from apps.inventory.services import eligible_units as borrowable_units
from apps.loans.services import release_request
from .models import MaintenanceRecord
from .services import create_record, resolve_record, start_repair, update_record
from .tests import MaintenanceFixtures


class MaintenanceQuickActionTests(MaintenanceFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.record = self.create()
        self.client.force_login(self.admin)
        self.start_url = reverse("maintenance_start", args=[self.record.pk])
        self.complete_url = reverse("maintenance_complete", args=[self.record.pk])

    def complete_data(self, **kwargs):
        return {"outcome": "REPAIRED", "repair_notes": "Lens replaced and serviceability checked", "confirm": "on", **kwargs}

    def test_start_preserves_reporting_admin_notes_and_records_start_actor_and_time(self):
        self.record.repair_notes = "Existing assessment must be retained"
        self.record.save(update_fields=["repair_notes"])
        starter = get_user_model().objects.create_user("repairing-admin", role="ADMIN")
        before = timezone.now()
        record = start_repair(self.record.pk, actor=starter)
        entry = AuditLog.objects.get(action="MAINTENANCE_UPDATED", entity_id=record.pk)
        self.assertEqual(entry.actor, starter)
        self.assertGreaterEqual(entry.occurred_at, before)
        self.assertIn("Started repair", entry.description)
        self.assertEqual(record.responsible_admin, self.admin)
        self.assertEqual(record.reported_at, self.record.reported_at)
        self.assertEqual(record.repair_notes, self.record.repair_notes)
        self.assertEqual(record.status, "IN_PROGRESS")
        self.assertIsNone(record.completed_at)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "MAINTENANCE")
        self.assertFalse(borrowable_units().filter(pk=self.unit.pk).exists())

    def test_start_rejects_unauthorized_and_inactive_admin(self):
        inactive = get_user_model().objects.create_user("inactive-repairer", role="ADMIN", is_active=False)
        for actor in [self.basic, AnonymousUser(), inactive]:
            with self.subTest(actor=actor), self.assertRaises(PermissionDenied):
                start_repair(self.record.pk, actor=actor)
        self.assertEqual(MaintenanceRecord.objects.get(pk=self.record.pk).status, "REPORTED")

    def test_start_audit_failure_rolls_back_status_and_inventory(self):
        with patch("apps.maintenance.services.record_event", side_effect=IntegrityError("Unavailable audit")):
            with self.assertRaises(IntegrityError):
                start_repair(self.record.pk, actor=self.admin)
        self.assertEqual(MaintenanceRecord.objects.get(pk=self.record.pk).status, "REPORTED")
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "MAINTENANCE")
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_list_detail_and_history_have_contextual_actions_and_shared_modal(self):
        for name, args in [("maintenance", []), ("maintenance_detail", [self.record.pk]), ("maintenance_history", [self.unit.pk])]:
            page = self.client.get(reverse(name, args=args))
            self.assertContains(page, self.start_url)
            self.assertNotContains(page, self.complete_url)
            self.assertContains(page, 'data-admin-form="Start repair"')
            self.assertContains(page, "data-admin-form-dialog")
            self.assertContains(page, "js/admin-modals.js")
        start_repair(self.record.pk, actor=self.admin)
        page = self.client.get(reverse("maintenance"))
        self.assertContains(page, 'data-admin-form="Complete repair"')
        self.assertNotContains(page, self.start_url)
        page = self.client.get(reverse("maintenance_detail", args=[self.record.pk]))
        self.assertContains(page, "Edit maintenance")
        self.assertContains(page, reverse("maintenance_update", args=[self.record.pk]))
        resolve_record(self.record.pk, actor=self.admin, outcome="REPAIRED", repair_notes="Fixed")
        page = self.client.get(reverse("maintenance"))
        self.assertContains(page, "View record")
        self.assertNotContains(page, self.start_url)
        self.assertNotContains(page, self.complete_url)

    def test_start_get_and_cancel_do_not_mutate_then_confirm_ignores_forged_fields(self):
        for headers in [{}, {"HTTP_X_ADMIN_MODAL": "1"}]:
            page = self.client.get(self.start_url, **headers)
            self.assertEqual(page.status_code, 200)
        self.assertEqual(MaintenanceRecord.objects.get(pk=self.record.pk).status, "REPORTED")
        self.assertEqual(AuditLog.objects.count(), 1)
        invalid = self.client.post(self.start_url, {}, HTTP_X_ADMIN_MODAL="1")
        self.assertEqual(invalid.status_code, 422)
        data = {"confirm": "True", "status": "REPAIRED", "repair_notes": "Forged", "responsible_admin": self.basic.pk}
        response = self.client.post(self.start_url, data, HTTP_X_ADMIN_MODAL="1")
        self.assertJSONEqual(response.content, {"saved": True})
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, "IN_PROGRESS")
        self.assertEqual(self.record.repair_notes, "")
        self.assertEqual(self.record.responsible_admin, self.admin)
        self.assertEqual(self.client.post(self.start_url, data, HTTP_X_ADMIN_MODAL="1").status_code, 409)
        self.assertEqual(AuditLog.objects.filter(action="MAINTENANCE_UPDATED").count(), 1)

    def test_completion_modal_requires_progress_notes_confirmation_and_valid_outcome(self):
        for outcome in ["REPAIRED", "RETIRED"]:
            self.assertEqual(self.client.post(self.complete_url, self.complete_data(outcome=outcome), HTTP_X_ADMIN_MODAL="1").status_code, 409)
        start_repair(self.record.pk, actor=self.admin)
        page = self.client.get(self.complete_url, HTTP_X_ADMIN_MODAL="1")
        self.assertContains(page, "data-admin-modal-form")
        self.assertContains(page, "Repair action taken")
        self.assertContains(page, "Repaired / serviceable")
        self.assertContains(page, "Retired / unserviceable")
        for changes in [{"repair_notes": ""}, {"repair_notes": "   "}, {"repair_notes": "x"*2001}, {"outcome": "AVAILABLE"}, {"outcome": "IN_PROGRESS"}, {"outcome": ""}, {"confirm": ""}]:
            with self.subTest(changes=changes):
                response = self.client.post(self.complete_url, self.complete_data(**changes), HTTP_X_ADMIN_MODAL="1")
                self.assertEqual(response.status_code, 422)
                self.assertTrue(response.context["form"].errors)
        self.assertEqual(MaintenanceRecord.objects.get(pk=self.record.pk).status, "IN_PROGRESS")

    def test_completion_repaired_restores_available_and_records_actor_date_and_work(self):
        start_repair(self.record.pk, actor=self.admin)
        before = timezone.now()
        data = self.complete_data(closed_by=self.basic.pk, completed_at="1990-01-01")
        response = self.client.post(self.complete_url, data, HTTP_X_ADMIN_MODAL="1")
        self.assertJSONEqual(response.content, {"saved": True})
        self.record.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertEqual(self.record.status, "REPAIRED")
        self.assertEqual(self.record.closed_by, self.admin)
        self.assertGreaterEqual(self.record.completed_at, before)
        self.assertEqual(self.record.repair_notes, data["repair_notes"])
        self.assertEqual(self.unit.status, "AVAILABLE")
        self.assertTrue(borrowable_units().filter(pk=self.unit.pk).exists())
        self.assertEqual(AuditLog.objects.filter(action="MAINTENANCE_REPAIRED").count(), 1)
        self.assertEqual(self.client.post(self.complete_url, data, HTTP_X_ADMIN_MODAL="1").status_code, 409)
        self.assertEqual(AuditLog.objects.filter(action="MAINTENANCE_REPAIRED").count(), 1)

    def test_completion_retired_remains_unavailable_and_closed_history_cannot_restart(self):
        start_repair(self.record.pk, actor=self.admin)
        response = self.client.post(self.complete_url, self.complete_data(outcome="RETIRED", repair_notes="Lens cannot be replaced"), HTTP_X_ADMIN_MODAL="1")
        self.assertJSONEqual(response.content, {"saved": True})
        self.record.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertEqual(self.record.status, "RETIRED")
        self.assertEqual(self.unit.status, "RETIRED")
        self.assertEqual(self.record.closed_by, self.admin)
        self.assertIsNotNone(self.record.completed_at)
        self.assertFalse(borrowable_units().filter(pk=self.unit.pk).exists())
        self.assertEqual(self.client.post(self.start_url, {"confirm": "on"}, HTTP_X_ADMIN_MODAL="1").status_code, 409)
        page = self.client.get(self.complete_url, HTTP_X_ADMIN_MODAL="1")
        self.assertContains(page, "data-admin-modal-unavailable")
        self.assertEqual(AuditLog.objects.filter(action="MAINTENANCE_RETIRED").count(), 1)

    def test_completion_audit_failure_preserves_bound_values_and_rolls_back_every_write(self):
        start_repair(self.record.pk, actor=self.admin)
        data = self.complete_data(repair_notes="Keep this repair explanation")
        with patch("apps.maintenance.services.record_event", side_effect=IntegrityError("Audit unavailable")):
            response = self.client.post(self.complete_url, data, HTTP_X_ADMIN_MODAL="1")
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Keep this repair explanation", status_code=409)
        self.record.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertEqual(self.record.status, "IN_PROGRESS")
        self.assertEqual(self.unit.status, "MAINTENANCE")
        self.assertIsNone(self.record.completed_at)
        self.assertIsNone(self.record.closed_by)
        self.assertFalse(AuditLog.objects.filter(action="MAINTENANCE_REPAIRED").exists())

    def test_fallback_start_and_complete_work_without_javascript_and_edit_remains_usable(self):
        response = self.client.post(self.start_url, {"confirm": "True"})
        self.assertRedirects(response, reverse("maintenance_detail", args=[self.record.pk]))
        response = self.client.post(reverse("maintenance_update", args=[self.record.pk]),
                                    {"status": "IN_PROGRESS", "repair_notes": "Corrected internal assessment"})
        self.assertEqual(response.status_code, 302)
        response = self.client.post(self.complete_url, self.complete_data(), follow=True)
        self.assertContains(response, "Equipment repaired.")
        with self.assertRaises(ValidationError):
            start_repair(self.record.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            update_record(self.record.pk, actor=self.admin, status="IN_PROGRESS", repair_notes="Cannot reopen")

    def test_start_rejects_changed_inventory_without_partial_state(self):
        EquipmentUnit.objects.filter(pk=self.unit.pk).update(status="RESERVED")
        response = self.client.post(self.start_url, {"confirm": "on"}, HTTP_X_ADMIN_MODAL="1")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(MaintenanceRecord.objects.get(pk=self.record.pk).status, "REPORTED")
        self.assertFalse(AuditLog.objects.filter(action="MAINTENANCE_UPDATED").exists())


class MaintenanceBorrowingGuardTests(MaintenanceFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.client.force_login(self.admin)

    def test_reserved_and_issued_units_reject_new_maintenance_in_form_and_service(self):
        request = self.pending()
        approve_request(request.pk, actor=self.admin)
        for expected_status in ["RESERVED", "ON_LOAN"]:
            with self.subTest(status=expected_status):
                response = self.client.post(reverse("maintenance_create"), {"unit": self.unit.pk, "reason": "Not eligible"})
                self.assertTrue(response.context["form"].errors)
                with self.assertRaises(ValidationError):
                    create_record(self.unit.pk, actor=self.admin, reason="Not eligible")
                self.assertFalse(MaintenanceRecord.objects.exists())
                self.unit.refresh_from_db()
                self.assertEqual(self.unit.status, expected_status)
            if expected_status == "RESERVED":
                release_request(request.pk, actor=self.admin)
