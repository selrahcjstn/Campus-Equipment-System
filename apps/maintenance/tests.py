from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib import import_module
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError, close_old_connections, connection, connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.borrowing.models import Allocation, BorrowingRequest, BorrowingRequestItem
from apps.borrowing.services import approve_request, submit_request
from apps.inventory.models import Equipment, EquipmentUnit
from apps.inventory.services import eligible_units as borrowable_units, inventory_queryset, retire_unit, edit_unit
from apps.loans.models import LoanUnit
from apps.loans.services import process_returns, release_request
from .models import MaintenanceRecord
from .services import create_record, eligible_units, record_damaged_return, resolve_record, update_record


class MaintenanceFixtures:
    def make_records(self):
        User = get_user_model()
        self.admin = User.objects.create_user("maintenance-admin", role="ADMIN")
        self.basic = User.objects.create_user("maintenance-basic", role="BASIC_USER")
        self.equipment = Equipment.objects.create(name="Camera", description="Public camera description")
        self.unit = EquipmentUnit.objects.create(equipment=self.equipment, asset_tag="CAM-001")

    def create(self):
        return create_record(self.unit.pk, actor=self.admin, reason="Lens damage requires assessment")

    def progress(self, record):
        return update_record(record.pk, actor=self.admin, status="IN_PROGRESS", repair_notes="Internal assessment")

    def repair(self, record):
        self.progress(record)
        return resolve_record(record.pk, actor=self.admin, outcome="REPAIRED", repair_notes="Lens replaced and checked")

    def pending(self, quantity=1):
        request = BorrowingRequest.objects.create(borrower=self.basic, purpose="Class project", due_at=timezone.now() + timedelta(days=2))
        BorrowingRequestItem.objects.create(request=request, equipment=self.equipment, quantity=quantity)
        return request

    def issue(self, quantity=1):
        request = self.pending(quantity)
        approve_request(request.pk, actor=self.admin)
        return release_request(request.pk, actor=self.admin)

    def damage(self, loan):
        return process_returns(loan.pk, actor=self.admin, returns=[(item.pk, "DAMAGED", "Return damage report") for item in loan.units.all()])


class MaintenanceServiceTests(MaintenanceFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def test_create_changes_unit_status_and_records_admin_and_date(self):
        record = self.create()
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "MAINTENANCE")
        self.assertEqual(record.status, "REPORTED")
        self.assertEqual(record.responsible_admin, self.admin)
        self.assertIsNone(record.completed_at)
        self.assertIsNone(record.closed_by)
        self.assertTrue(record.is_active)
        self.assertEqual(record.reason, "Lens damage requires assessment")

    def test_invalid_reason_does_not_change_unit(self):
        for reason in ["", "   ", "x" * 1001, None, 1]:
            with self.subTest(reason=str(reason)[:20]), self.assertRaises(ValidationError):
                create_record(self.unit.pk, actor=self.admin, reason=reason)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "AVAILABLE")
        self.assertFalse(MaintenanceRecord.objects.exists())

    def test_admin_role_is_required_for_every_service(self):
        record = self.create()
        inactive = get_user_model().objects.create_user("inactive-admin", role="ADMIN", is_active=False)
        self.basic.is_staff = self.basic.is_superuser = True
        for actor in [self.basic, inactive, AnonymousUser()]:
            for operation in [lambda: create_record(self.unit.pk, actor=actor, reason="Issue"), lambda: update_record(record.pk, actor=actor, status="IN_PROGRESS", repair_notes="Work"), lambda: resolve_record(record.pk, actor=actor, outcome="RETIRED", repair_notes="Broken"), lambda: record_damaged_return(1, actor=actor)]:
                with self.subTest(actor=str(actor)), self.assertRaises(PermissionDenied):
                    operation()
        self.assertEqual(MaintenanceRecord.objects.get(pk=record.pk).status, "REPORTED")

    def test_reserved_issued_retired_units_are_ineligible(self):
        for status in ["RESERVED", "ON_LOAN", "RETIRED"]:
            EquipmentUnit.objects.filter(pk=self.unit.pk).update(status=status)
            with self.subTest(status=status), self.assertRaises(ValidationError):
                self.create()
            self.assertFalse(eligible_units().filter(pk=self.unit.pk).exists())
        self.assertFalse(MaintenanceRecord.objects.exists())

    def test_adopt_untracked_maintenance_unit(self):
        EquipmentUnit.objects.filter(pk=self.unit.pk).update(status="MAINTENANCE")
        self.assertTrue(eligible_units().filter(pk=self.unit.pk).exists())
        self.create()
        self.assertFalse(eligible_units().filter(pk=self.unit.pk).exists())

    def test_duplicate_active_record_is_rejected_without_changes(self):
        record = self.create()
        with self.assertRaises(ValidationError):
            self.create()
        self.assertEqual(MaintenanceRecord.objects.count(), 1)
        self.assertEqual(MaintenanceRecord.objects.get(pk=record.pk).reason, record.reason)

    def test_database_blocks_duplicate_active_records(self):
        self.create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            MaintenanceRecord.objects.create(unit=self.unit, reason="Second report", status="IN_PROGRESS")

    def test_database_blocks_unresolved_completed_record(self):
        for changes in [{"status": "REPAIRED"}, {"status": "RETIRED", "completed_at": timezone.now(), "closed_by": self.admin}, {"status": "INVALID"}, {"status": "REPORTED", "completed_at": timezone.now()}]:
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                MaintenanceRecord.objects.create(unit=self.unit, reason="Issue", **changes)

    def test_progress_updates_notes_without_restoring_availability(self):
        record = self.progress(self.create())
        self.assertEqual(record.status, "IN_PROGRESS")
        self.assertEqual(record.repair_notes, "Internal assessment")
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "MAINTENANCE")
        self.assertFalse(borrowable_units().filter(pk=self.unit.pk).exists())

    def test_progress_cannot_reverse_or_complete(self):
        record = self.progress(self.create())
        for status in ["REPORTED", "REPAIRED", "RETIRED", "AVAILABLE", "INVALID"]:
            with self.subTest(status=status), self.assertRaises(ValidationError):
                update_record(record.pk, actor=self.admin, status=status, repair_notes="Notes")
        self.assertEqual(MaintenanceRecord.objects.get(pk=record.pk).status, "IN_PROGRESS")

    def test_notes_are_validated_on_progress_and_resolution(self):
        record = self.progress(self.create())
        for notes in ["x" * 2001, None, 123]:
            with self.subTest(notes=str(notes)[:20]), self.assertRaises(ValidationError):
                update_record(record.pk, actor=self.admin, status="IN_PROGRESS", repair_notes=notes)
        for notes in ["", "   ", "x" * 2001, None]:
            with self.subTest(notes=str(notes)[:20]), self.assertRaises(ValidationError):
                resolve_record(record.pk, actor=self.admin, outcome="REPAIRED", repair_notes=notes)
        self.assertEqual(MaintenanceRecord.objects.get(pk=record.pk).status, "IN_PROGRESS")

    def test_successful_repair_records_resolution_and_restores_available(self):
        record = self.repair(self.create())
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "AVAILABLE")
        self.assertEqual(record.status, "REPAIRED")
        self.assertEqual(record.closed_by, self.admin)
        self.assertGreaterEqual(record.completed_at, record.reported_at)
        self.assertFalse(record.is_active)
        self.assertTrue(borrowable_units().filter(pk=self.unit.pk).exists())
        self.assertEqual(inventory_queryset().get(pk=self.equipment.pk).available_count, 1)

    def test_repair_requires_started_work(self):
        record = self.create()
        with self.assertRaises(ValidationError):
            resolve_record(record.pk, actor=self.admin, outcome="REPAIRED", repair_notes="Claimed fixed")
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "MAINTENANCE")

    def test_retirement_records_outcome_and_never_restores_available(self):
        record = resolve_record(self.create().pk, actor=self.admin, outcome="RETIRED", repair_notes="Irreparable lens assembly")
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "RETIRED")
        self.assertEqual(record.status, "RETIRED")
        self.assertEqual(record.closed_by, self.admin)
        self.assertFalse(borrowable_units().filter(pk=self.unit.pk).exists())
        with self.assertRaises(ValidationError):
            self.create()

    def test_invalid_resolution_outcome_is_rejected(self):
        record = self.create()
        for outcome in ["AVAILABLE", "IN_PROGRESS", "REPORTED", "INVALID"]:
            with self.subTest(outcome=outcome), self.assertRaises(ValidationError):
                resolve_record(record.pk, actor=self.admin, outcome=outcome, repair_notes="Notes")

    def test_closed_records_cannot_be_updated_or_resolved_twice(self):
        record = self.repair(self.create())
        with self.assertRaises(ValidationError):
            self.progress(record)
        with self.assertRaises(ValidationError):
            resolve_record(record.pk, actor=self.admin, outcome="RETIRED", repair_notes="New outcome")
        self.assertEqual(MaintenanceRecord.objects.get(pk=record.pk).repair_notes, "Lens replaced and checked")

    def test_repeated_maintenance_preserves_previous_history(self):
        first = self.repair(self.create())
        second = self.create()
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(self.unit.maintenance_records.count(), 2)
        self.assertEqual(MaintenanceRecord.objects.get(pk=first.pk).status, "REPAIRED")

    def test_linked_units_and_admins_cannot_be_deleted(self):
        self.create()
        for target in [self.unit, self.admin]:
            with self.assertRaises(ProtectedError):
                target.delete()

    def test_completion_before_report_rolls_back(self):
        record = self.progress(self.create())
        with patch("apps.maintenance.services.timezone.now", return_value=record.reported_at - timedelta(seconds=1)), self.assertRaises(ValidationError):
            resolve_record(record.pk, actor=self.admin, outcome="REPAIRED", repair_notes="Fixed")
        self.assertEqual(MaintenanceRecord.objects.get(pk=record.pk).status, "IN_PROGRESS")

    def test_inconsistent_unit_state_blocks_progress_and_resolution(self):
        record = self.create()
        EquipmentUnit.objects.filter(pk=self.unit.pk).update(status="RESERVED")
        with self.assertRaises(ValidationError):
            self.progress(record)
        with self.assertRaises(ValidationError):
            resolve_record(record.pk, actor=self.admin, outcome="RETIRED", repair_notes="Broken")
        self.assertEqual(MaintenanceRecord.objects.get(pk=record.pk).status, "REPORTED")

    def test_archived_catalog_item_can_be_repaired_but_remains_hidden(self):
        Equipment.objects.filter(pk=self.equipment.pk).update(is_active=False)
        self.repair(self.create())
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "AVAILABLE")
        self.assertFalse(borrowable_units().filter(pk=self.unit.pk).exists())
        self.client.force_login(self.basic)
        self.assertEqual(self.client.get(reverse("equipment_detail", args=[self.equipment.pk])).status_code, 404)

    def test_active_record_blocks_borrowing_even_if_unit_state_is_corrupted(self):
        self.create()
        EquipmentUnit.objects.filter(pk=self.unit.pk).update(status="AVAILABLE")
        self.assertFalse(borrowable_units().filter(pk=self.unit.pk).exists())
        self.assertEqual(inventory_queryset().get(pk=self.equipment.pk).available_count, 0)
        self.unit.refresh_from_db()
        self.assertFalse(self.unit.can_edit)
        with self.assertRaises(ValidationError):
            retire_unit(self.unit.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            edit_unit(self.unit.pk, actor=self.admin, asset_tag="NEW-TAG")
        with self.assertRaises(ValidationError):
            submit_request(borrower=self.basic, purpose="Class", due_at=timezone.now() + timedelta(days=1), items=[(self.equipment.pk, 1)])
        request = self.pending()
        with self.assertRaises(ValidationError):
            approve_request(request.pk, actor=self.admin, allocations={request.items.get().pk: [self.unit.pk]})
        request.refresh_from_db()
        self.assertEqual(request.status, "PENDING")
        self.assertFalse(Allocation.objects.exists())

    def test_missing_ids_are_validation_errors(self):
        with self.assertRaises(ValidationError):
            create_record(99999, actor=self.admin, reason="Issue")
        with self.assertRaises(ValidationError):
            update_record(99999, actor=self.admin, status="IN_PROGRESS", repair_notes="Notes")


class MaintenanceIntegrationTests(MaintenanceFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def test_damaged_return_creates_linked_record_atomically(self):
        loan = self.issue()
        self.damage(loan)
        source = loan.units.get()
        record = MaintenanceRecord.objects.get()
        self.assertEqual(record.source_return, source)
        self.assertEqual(record.reason, source.return_notes)
        self.assertEqual(record.reported_at, source.returned_at)
        self.assertEqual(record.responsible_admin, self.admin)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "MAINTENANCE")
        self.assertFalse(Allocation.objects.filter(active=True).exists())
        self.assertFalse(borrowable_units().exists())
        loan.refresh_from_db()
        self.assertIsNotNone(loan.completed_at)

    def test_good_return_does_not_create_maintenance(self):
        loan = self.issue()
        process_returns(loan.pk, actor=self.admin, returns=[(loan.units.get().pk, "GOOD", "")])
        self.assertFalse(MaintenanceRecord.objects.exists())
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "AVAILABLE")

    def test_mixed_partial_returns_keep_other_units_issued(self):
        other = EquipmentUnit.objects.create(equipment=self.equipment, asset_tag="CAM-002")
        loan = self.issue(2)
        selected = loan.units.get(unit=self.unit)
        process_returns(loan.pk, actor=self.admin, returns=[(selected.pk, "DAMAGED", "Damaged lens")])
        self.assertEqual(MaintenanceRecord.objects.count(), 1)
        other.refresh_from_db()
        self.assertEqual(other.status, "ON_LOAN")
        loan.refresh_from_db()
        self.assertIsNone(loan.completed_at)
        self.assertEqual(loan.outstanding_count, 1)
        process_returns(loan.pk, actor=self.admin, returns=[(loan.units.get(unit=other).pk, "GOOD", "")])
        self.assertEqual(MaintenanceRecord.objects.count(), 1)

    def test_maintenance_failure_rolls_back_entire_return(self):
        loan = self.issue()
        with patch("apps.maintenance.services.record_damaged_return", side_effect=ValidationError("Conflict")), self.assertRaises(ValidationError):
            self.damage(loan)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "ON_LOAN")
        self.assertIsNone(loan.units.get().returned_at)
        self.assertTrue(Allocation.objects.get().active)
        loan.refresh_from_db()
        self.assertIsNone(loan.completed_at)

    def test_repair_does_not_change_recorded_return_or_loan_history(self):
        loan = self.issue()
        self.damage(loan)
        source = loan.units.get()
        before = (source.returned_at, source.return_notes, source.return_condition, source.asset_tag)
        record = self.repair(MaintenanceRecord.objects.get())
        source.refresh_from_db()
        self.assertEqual(before, (source.returned_at, source.return_notes, source.return_condition, source.asset_tag))
        self.assertEqual(record.source_return, source)
        self.assertFalse(Allocation.objects.get().active)
        loan.request.refresh_from_db()
        self.assertEqual(loan.request.status, "COMPLETED")
        second = self.issue()
        self.damage(second)
        self.assertEqual(MaintenanceRecord.objects.count(), 2)
        self.assertEqual(MaintenanceRecord.objects.get(pk=record.pk).status, "REPAIRED")

    def test_damaged_return_helper_is_idempotent_and_does_not_reopen_history(self):
        loan = self.issue()
        self.damage(loan)
        source = loan.units.get()
        record = MaintenanceRecord.objects.get()
        self.assertEqual(record_damaged_return(source.pk, actor=self.admin), record)
        self.repair(record)
        self.assertEqual(record_damaged_return(source.pk, actor=self.admin).status, "REPAIRED")
        self.assertEqual(MaintenanceRecord.objects.count(), 1)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "AVAILABLE")

    def test_unreturned_or_good_units_cannot_be_claimed_as_damaged(self):
        loan = self.issue()
        source = loan.units.get()
        with self.assertRaises(ValidationError):
            record_damaged_return(source.pk, actor=self.admin)
        process_returns(loan.pk, actor=self.admin, returns=[(source.pk, "GOOD", "")])
        with self.assertRaises(ValidationError):
            record_damaged_return(source.pk, actor=self.admin)
        self.assertFalse(MaintenanceRecord.objects.exists())

    def test_active_allocation_blocks_manual_creation_even_with_wrong_status(self):
        request = self.pending()
        approve_request(request.pk, actor=self.admin)
        EquipmentUnit.objects.filter(pk=self.unit.pk).update(status="AVAILABLE")
        with self.assertRaises(ValidationError):
            self.create()
        self.assertFalse(eligible_units().exists())

    def test_outstanding_loan_blocks_manual_creation_and_resolution(self):
        loan = self.issue()
        EquipmentUnit.objects.filter(pk=self.unit.pk).update(status="MAINTENANCE")
        Allocation.objects.update(active=False)
        with self.assertRaises(ValidationError):
            self.create()
        self.assertFalse(eligible_units().exists())
        record = MaintenanceRecord.objects.create(unit=self.unit, reason="Conflicting direct write")
        with self.assertRaises(ValidationError):
            resolve_record(record.pk, actor=self.admin, outcome="RETIRED", repair_notes="Broken")
        self.assertIsNone(loan.units.get().returned_at)

    def test_conflicting_maintenance_blocks_loan_release(self):
        request = self.pending()
        approve_request(request.pk, actor=self.admin)
        MaintenanceRecord.objects.create(unit=self.unit, reason="Conflicting active record")
        with self.assertRaises(ValidationError):
            release_request(request.pk, actor=self.admin)
        self.assertFalse(LoanUnit.objects.exists())
        request.refresh_from_db()
        self.assertEqual(request.status, "APPROVED")

    def test_return_with_conflicting_maintenance_does_not_make_unit_available(self):
        loan = self.issue()
        MaintenanceRecord.objects.create(unit=self.unit, reason="Conflicting active record")
        with self.assertRaises(ValidationError):
            process_returns(loan.pk, actor=self.admin, returns=[(loan.units.get().pk, "GOOD", "")])
        self.assertIsNone(loan.units.get().returned_at)

    def test_model_validates_source_unit_condition_and_admin(self):
        loan = self.issue()
        self.damage(loan)
        source = loan.units.get()
        other = EquipmentUnit.objects.create(equipment=self.equipment, asset_tag="OTHER-CAM")
        record = MaintenanceRecord(unit=other, source_return=source, reason="Issue")
        with self.assertRaises(ValidationError):
            record.full_clean()
        record = MaintenanceRecord(unit=other, responsible_admin=self.basic, reason="Issue")
        with self.assertRaises(ValidationError):
            record.full_clean()


class MaintenanceViewTests(MaintenanceFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.record = self.create()
        self.client.force_login(self.admin)

    def endpoints(self):
        return [("maintenance", []), ("maintenance_create", []), ("maintenance_detail", [self.record.pk]), ("maintenance_history", [self.unit.pk]), ("maintenance_update", [self.record.pk]), ("maintenance_complete", [self.record.pk]), ("maintenance_retire", [self.record.pk])]

    def test_all_pages_render_and_reuse_admin_navigation(self):
        for name, args in self.endpoints():
            with self.subTest(name=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Admin Portal")
                self.assertContains(response, 'href="/manage/maintenance/"')
                self.assertContains(response, 'aria-current="page"')

    def test_anonymous_users_redirect_to_login_on_every_endpoint(self):
        self.client.logout()
        for name, args in self.endpoints():
            for method in [self.client.get, self.client.post]:
                with self.subTest(name=name):
                    response = method(reverse(name, args=args))
                    self.assertEqual(response.status_code, 302)
                    self.assertIn(reverse("login"), response.url)

    def test_basic_users_denied_on_all_endpoints_even_if_superuser(self):
        self.basic.is_staff = self.basic.is_superuser = True
        self.basic.save()
        self.client.force_login(self.basic)
        for name, args in self.endpoints():
            for method in [self.client.get, self.client.post]:
                with self.subTest(name=name):
                    self.assertEqual(method(reverse(name, args=args)).status_code, 403)

    def test_csrf_is_required_on_every_mutation(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        for name in ["maintenance_create", "maintenance_update", "maintenance_complete", "maintenance_retire"]:
            args = [] if name == "maintenance_create" else [self.record.pk]
            self.assertEqual(client.post(reverse(name, args=args), {"confirm": "on"}).status_code, 403)

    def test_dashboard_stats_are_database_driven(self):
        response = self.client.get(reverse("maintenance"))
        self.assertEqual(response.context["counts"], {"active": 1, "completed": 0})
        self.assertEqual(response.context["maintenance_count"], 1)
        self.repair(self.record)
        response = self.client.get(reverse("maintenance"))
        self.assertEqual(response.context["counts"], {"active": 0, "completed": 1})
        self.assertEqual(response.context["maintenance_count"], 0)

    def test_search_status_and_equipment_filters(self):
        other_equipment = Equipment.objects.create(name="Tripod")
        other = EquipmentUnit.objects.create(equipment=other_equipment, asset_tag="TRIPOD-001")
        create_record(other.pk, actor=self.admin, reason="Foot issue")
        self.repair(self.record)
        for query in [{"q": "CAM-001"}, {"q": "Camera"}, {"q": "Lens damage"}, {"equipment": self.equipment.pk}, {"status": "REPAIRED"}]:
            response = self.client.get(reverse("maintenance"), query)
            self.assertEqual([r.pk for r in response.context["page_obj"]], [self.record.pk])
        response = self.client.get(reverse("maintenance"), {"status": "active"})
        self.assertEqual(len(response.context["page_obj"]), 1)
        self.assertEqual(response.context["page_obj"][0].unit, other)

    def test_invalid_filters_show_errors_and_empty_results(self):
        for query in [{"status": "INVALID"}, {"equipment": 999999}, {"q": "x" * 151}]:
            response = self.client.get(reverse("maintenance"), query)
            self.assertTrue(response.context["filter_form"].errors)
            self.assertContains(response, "No maintenance records in this view")

    def test_create_post_uses_only_safe_fields_and_preselects_unit(self):
        other = EquipmentUnit.objects.create(equipment=self.equipment, asset_tag="CAM-002")
        response = self.client.get(reverse("maintenance_create"), {"unit": other.pk})
        self.assertEqual(str(response.context["form"].initial["unit"]), str(other.pk))
        response = self.client.post(reverse("maintenance_create"), {"unit": other.pk, "reason": "New fault", "status": "REPAIRED", "responsible_admin": self.basic.pk})
        self.assertEqual(response.status_code, 302)
        record = MaintenanceRecord.objects.get(unit=other)
        self.assertEqual(record.status, "REPORTED")
        self.assertEqual(record.responsible_admin, self.admin)

    def test_create_invalid_duplicate_or_ineligible_unit_changes_nothing(self):
        for data in [{"unit": self.unit.pk, "reason": "Second issue"}, {"unit": 999999, "reason": "Issue"}, {"unit": self.unit.pk, "reason": ""}]:
            response = self.client.post(reverse("maintenance_create"), data)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
        self.assertEqual(MaintenanceRecord.objects.count(), 1)

    def test_update_post_and_forged_resolution(self):
        response = self.client.post(reverse("maintenance_update", args=[self.record.pk]), {"status": "IN_PROGRESS", "repair_notes": "Inspecting"})
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("maintenance_update", args=[self.record.pk]), {"status": "REPAIRED", "repair_notes": "Done"})
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(MaintenanceRecord.objects.get(pk=self.record.pk).status, "IN_PROGRESS")

    def test_completion_requires_notes_confirmation_and_progress(self):
        url = reverse("maintenance_complete", args=[self.record.pk])
        self.assertEqual(self.client.post(url, {"repair_notes": "Repaired", "confirm": "on"}).status_code, 409)
        self.progress(self.record)
        for data in [{"repair_notes": "Repaired"}, {"repair_notes": "", "confirm": "on"}]:
            response = self.client.post(url, data)
            self.assertTrue(response.context["form"].errors)
            self.assertEqual(MaintenanceRecord.objects.get(pk=self.record.pk).status, "IN_PROGRESS")
        response = self.client.post(url, {"repair_notes": "Repaired and checked", "confirm": "on"}, follow=True)
        self.assertContains(response, "Equipment repaired.")
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "AVAILABLE")

    def test_retire_post_and_resubmission_conflict(self):
        url = reverse("maintenance_retire", args=[self.record.pk])
        data = {"repair_notes": "Cannot be repaired", "confirm": "on"}
        response = self.client.post(url, data, follow=True)
        self.assertContains(response, "Equipment retired.")
        self.assertEqual(self.client.post(url, data).status_code, 409)
        self.assertEqual(self.client.post(reverse("maintenance_update", args=[self.record.pk]), {"status": "IN_PROGRESS", "repair_notes": "Override"}).status_code, 409)

    def test_get_actions_never_mutate_and_dialog_uses_shared_components(self):
        self.progress(self.record)
        for name in ["maintenance_complete", "maintenance_retire"]:
            response = self.client.get(reverse(name, args=[self.record.pk]))
            self.assertContains(response, '<dialog class="modal"')
            self.assertContains(response, 'data-confirm-dialog="maintenance-confirmation"')
            self.assertContains(response, 'class="form-checkbox"')
            self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertEqual(MaintenanceRecord.objects.get(pk=self.record.pk).status, "IN_PROGRESS")

    def test_completed_history_is_preserved_and_linked_from_inventory(self):
        self.repair(self.record)
        second = self.create()
        response = self.client.get(reverse("maintenance_history", args=[self.unit.pk]))
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        self.assertEqual(response.context["active_record"], second)
        response = self.client.get(reverse("admin_equipment_detail", args=[self.equipment.pk]))
        self.assertContains(response, reverse("maintenance_history", args=[self.unit.pk]))

    def test_public_catalog_never_exposes_internal_notes_or_repair_actions(self):
        update_record(self.record.pk, actor=self.admin, status="IN_PROGRESS", repair_notes="PRIVATE-INTERNAL-REPAIR")
        self.client.force_login(self.basic)
        for name, args in [("equipment_catalog", []), ("equipment_detail", [self.equipment.pk])]:
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 200)
            for secret in ["PRIVATE-INTERNAL-REPAIR", self.record.reason, self.unit.asset_tag, "/manage/maintenance/"]:
                self.assertNotContains(response, secret)
        self.assertEqual(inventory_queryset().get(pk=self.equipment.pk).available_count, 0)

    def test_untracked_maintenance_units_are_visible_and_adoptable(self):
        other = EquipmentUnit.objects.create(equipment=self.equipment, asset_tag="UNTRACKED", status="MAINTENANCE")
        response = self.client.get(reverse("maintenance"))
        self.assertEqual(response.context["untracked_count"], 1)
        self.assertContains(response, "needs a record")
        self.assertContains(response, "UNTRACKED")
        response = self.client.get(reverse("maintenance_history", args=[other.pk]))
        self.assertContains(response, f'?unit={other.pk}')

    def test_missing_records_are_404_and_delete_endpoints_do_not_exist(self):
        for name in ["maintenance_detail", "maintenance_update", "maintenance_complete", "maintenance_retire", "maintenance_history"]:
            self.assertEqual(self.client.get(reverse(name, args=[99999])).status_code, 404)
        self.assertEqual(self.client.post(f"/manage/maintenance/{self.record.pk}/delete/").status_code, 404)
        self.assertTrue(MaintenanceRecord.objects.filter(pk=self.record.pk).exists())

    def test_read_only_pages_reject_posts_and_actions_reject_delete(self):
        for name in ["maintenance", "maintenance_detail", "maintenance_history"]:
            args = [] if name == "maintenance" else [self.record.pk if name == "maintenance_detail" else self.unit.pk]
            self.assertEqual(self.client.post(reverse(name, args=args)).status_code, 405)
        self.assertEqual(self.client.delete(reverse("maintenance_retire", args=[self.record.pk])).status_code, 405)

    def test_pagination_preserves_filters_and_units_page_independently(self):
        for index in range(20):
            unit = EquipmentUnit.objects.create(equipment=self.equipment, asset_tag=f"EXTRA-{index}")
            create_record(unit.pk, actor=self.admin, reason="Extra issue")
        response = self.client.get(reverse("maintenance"), {"equipment": self.equipment.pk})
        self.assertEqual(len(response.context["page_obj"]), 20)
        self.assertEqual(len(response.context["unit_page"]), 20)
        self.assertContains(response, f"equipment={self.equipment.pk}&amp;page=2")
        self.assertContains(response, f"equipment={self.equipment.pk}&amp;units_page=2")
        response = self.client.get(reverse("maintenance"), {"page": 2, "units_page": 2})
        self.assertEqual(len(response.context["page_obj"]), 1)
        self.assertEqual(len(response.context["unit_page"]), 1)


class ExistingMaintenanceMigrationTests(MaintenanceFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def backfill(self):
        migration = import_module("apps.maintenance.migrations.0002_track_existing_maintenance")
        migration.track_existing_units(apps, SimpleNamespace(connection=connection))

    def test_existing_damaged_returns_are_linked_without_changing_old_records(self):
        loan = self.issue()
        with patch("apps.maintenance.services.record_damaged_return"):
            self.damage(loan)
        source = loan.units.get()
        original = (source.returned_at, source.return_condition, source.return_notes)
        self.backfill()
        record = MaintenanceRecord.objects.get()
        self.assertEqual(record.source_return, source)
        self.assertEqual(record.reason, "Return damage report")
        self.assertEqual(record.responsible_admin, self.admin)
        source.refresh_from_db()
        self.assertEqual(original, (source.returned_at, source.return_condition, source.return_notes))
        self.backfill()
        self.assertEqual(MaintenanceRecord.objects.count(), 1)

    def test_units_without_returns_are_adopted_with_legacy_reason(self):
        EquipmentUnit.objects.filter(pk=self.unit.pk).update(status="MAINTENANCE")
        other = EquipmentUnit.objects.create(equipment=self.equipment, asset_tag="UNRELATED")
        self.backfill()
        record = MaintenanceRecord.objects.get()
        self.assertIsNone(record.source_return)
        self.assertIsNone(record.responsible_admin)
        self.assertEqual(record.unit, self.unit)
        self.assertFalse(MaintenanceRecord.objects.filter(unit=other).exists())

    def test_old_damage_is_not_reused_after_a_newer_good_return(self):
        loan = self.issue()
        self.damage(loan)
        old = self.repair(MaintenanceRecord.objects.get())
        later = self.issue()
        process_returns(later.pk, actor=self.admin, returns=[(later.units.get().pk, "GOOD", "")])
        EquipmentUnit.objects.filter(pk=self.unit.pk).update(status="MAINTENANCE")
        self.backfill()
        new = MaintenanceRecord.objects.exclude(pk=old.pk).get()
        self.assertIsNone(new.source_return)
        self.assertEqual(MaintenanceRecord.objects.get(pk=old.pk).status, "REPAIRED")


class ConcurrentMaintenanceTests(MaintenanceFixtures, TransactionTestCase):
    def setUp(self):
        self.make_records()

    def race(self, operations):
        barrier = Barrier(2)

        def worker(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                operation()
                return "saved"
            except (ValidationError, IntegrityError, OperationalError):
                return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(worker, operations))
        self.assertEqual(sorted(results), ["rejected", "saved"])

    def test_two_creations_cannot_duplicate_active_maintenance(self):
        self.race([self.create, self.create])
        self.assertEqual(MaintenanceRecord.objects.count(), 1)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "MAINTENANCE")

    def test_repair_and_retirement_cannot_both_complete(self):
        record = self.progress(self.create())
        self.race([lambda: resolve_record(record.pk, actor=self.admin, outcome="REPAIRED", repair_notes="Fixed"), lambda: resolve_record(record.pk, actor=self.admin, outcome="RETIRED", repair_notes="Irreparable")])
        record.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, "AVAILABLE" if record.status == "REPAIRED" else "RETIRED")
        self.assertIsNotNone(record.completed_at)

    def test_approval_and_maintenance_cannot_take_the_same_unit(self):
        request = self.pending()
        self.race([self.create, lambda: approve_request(request.pk, actor=self.admin)])
        self.unit.refresh_from_db()
        request.refresh_from_db()
        if request.status == "APPROVED":
            self.assertEqual(self.unit.status, "RESERVED")
            self.assertFalse(MaintenanceRecord.objects.exists())
        else:
            self.assertEqual(self.unit.status, "MAINTENANCE")
            self.assertFalse(Allocation.objects.exists())
