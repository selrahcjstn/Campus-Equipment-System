from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command, CommandError
from django.db import IntegrityError, OperationalError, close_old_connections, connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.borrowing.models import Allocation, BorrowingRequest, BorrowingRequestItem
from apps.borrowing.services import approve_request
from apps.inventory.models import Equipment, EquipmentUnit
from .models import Loan, LoanUnit
from .services import process_returns, release_request


class LoanFixtures:
    def make_records(self):
        User = get_user_model()
        self.admin = User.objects.create_user("loan-admin", role="ADMIN")
        self.borrower = User.objects.create_user("loan-borrower", role="BASIC_USER")
        self.other = User.objects.create_user("other-borrower", role="BASIC_USER")
        self.equipment = Equipment.objects.create(name="Projector", description="Classroom projector with case")
        self.units = [EquipmentUnit.objects.create(equipment=self.equipment, asset_tag=f"PROJECTOR-{i}") for i in range(2)]
        self.request = BorrowingRequest.objects.create(borrower=self.borrower, purpose="Class presentation", due_at=timezone.now() + timedelta(days=3))
        self.item = BorrowingRequestItem.objects.create(request=self.request, equipment=self.equipment, quantity=2)

    def approve(self):
        return approve_request(self.request.pk, reason="Approved for the test borrowing activity.", actor=self.admin, allocations={self.item.pk: [unit.pk for unit in self.units]})

    def issue(self):
        self.approve()
        return release_request(self.request.pk, actor=self.admin)

    def return_all(self, loan):
        return process_returns(loan.pk, actor=self.admin, returns=[(unit.pk, LoanUnit.Condition.GOOD, "") for unit in loan.units.filter(returned_at__isnull=True)])

    def make_other_loan(self):
        equipment = Equipment.objects.create(name="Private equipment")
        unit = EquipmentUnit.objects.create(equipment=equipment, asset_tag="OTHER-SECRET-UNIT")
        request = BorrowingRequest.objects.create(borrower=self.other, purpose="Other person's request", due_at=timezone.now() + timedelta(days=3))
        item = BorrowingRequestItem.objects.create(request=request, equipment=equipment, quantity=1)
        approve_request(request.pk, reason="Approved for the test borrowing activity.", actor=self.admin, allocations={item.pk: [unit.pk]})
        return release_request(request.pk, actor=self.admin)

    def return_post(self, loan, selected=None):
        units = list(loan.units.filter(returned_at__isnull=True))
        selected = selected if selected is not None else [unit.pk for unit in units]
        data = {"units-TOTAL_FORMS": str(len(units)), "units-INITIAL_FORMS": str(len(units)), "units-MIN_NUM_FORMS": "0", "units-MAX_NUM_FORMS": "1000", "confirm": "on"}
        for i, unit in enumerate(units):
            data[f"units-{i}-loan_unit_id"] = str(unit.pk)
            data[f"units-{i}-condition"] = "GOOD"
            data[f"units-{i}-notes"] = ""
            if unit.pk in selected:
                data[f"units-{i}-return_now"] = "on"
        return data


class LoanServiceTests(LoanFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def test_successful_release_and_snapshots(self):
        loan = self.issue()
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, BorrowingRequest.Status.ISSUED)
        self.assertEqual(loan.borrower, self.borrower)
        self.assertEqual(loan.issued_by, self.admin)
        self.assertEqual(loan.due_at, self.request.due_at)
        self.assertEqual(loan.quantity, 2)
        self.assertEqual(loan.outstanding_count, 2)
        self.assertEqual(loan.status, "Active")
        self.assertEqual(EquipmentUnit.objects.filter(status="ON_LOAN").count(), 2)
        self.assertEqual(Allocation.objects.filter(active=True).count(), 2)
        Equipment.objects.filter(pk=self.equipment.pk).update(name="Renamed equipment")
        EquipmentUnit.objects.filter(pk=self.units[0].pk).update(asset_tag="RENAMED-TAG")
        self.assertEqual(loan.units.first().equipment_name, "Projector")
        self.assertEqual(loan.units.first().asset_tag, "PROJECTOR-0")

    def test_unauthorized_release_and_inactive_admin(self):
        self.approve()
        for actor in [self.borrower, self.other]:
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                release_request(self.request.pk, actor=actor)
        self.admin.is_active = False
        with self.assertRaises(PermissionDenied):
            release_request(self.request.pk, actor=self.admin)
        self.assertFalse(Loan.objects.exists())

    def test_duplicate_release(self):
        self.issue()
        with self.assertRaises(ValidationError):
            release_request(self.request.pk, actor=self.admin)
        self.assertEqual(Loan.objects.count(), 1)
        self.assertEqual(LoanUnit.objects.count(), 2)

    def test_non_approved_requests_cannot_be_released(self):
        for status in ["PENDING", "REJECTED", "CANCELLED", "COMPLETED", "ISSUED"]:
            BorrowingRequest.objects.filter(pk=self.request.pk).update(status=status)
            with self.subTest(status=status), self.assertRaises(ValidationError):
                release_request(self.request.pk, actor=self.admin)
        self.assertFalse(Loan.objects.exists())

    def test_release_requires_approval_metadata(self):
        self.approve()
        BorrowingRequest.objects.filter(pk=self.request.pk).update(approved_by=None)
        with self.assertRaises(ValidationError):
            release_request(self.request.pk, actor=self.admin)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, "APPROVED")

    def test_return_cannot_precede_issue_date(self):
        loan = self.issue()
        with patch("apps.loans.services.timezone.now", return_value=loan.issued_at - timedelta(seconds=1)):
            with self.assertRaises(ValidationError):
                self.return_all(loan)
        self.assertEqual(loan.outstanding_count, 2)

    def test_release_rejects_incomplete_allocation(self):
        self.approve()
        Allocation.objects.filter(unit=self.units[1]).update(active=False)
        with self.assertRaises(ValidationError):
            release_request(self.request.pk, actor=self.admin)
        self.assertFalse(Loan.objects.exists())

    def test_release_rejects_request_without_items(self):
        self.request.status = "APPROVED"
        self.request.approved_by = self.admin
        self.request.approved_at = timezone.now()
        self.request.save()
        self.item.delete()
        with self.assertRaises(ValidationError):
            release_request(self.request.pk, actor=self.admin)

    def test_release_rejects_wrong_equipment_allocation(self):
        self.approve()
        other_equipment = Equipment.objects.create(name="Laptop")
        EquipmentUnit.objects.filter(pk=self.units[1].pk).update(equipment=other_equipment)
        with self.assertRaises(ValidationError):
            release_request(self.request.pk, actor=self.admin)
        self.units[0].refresh_from_db()
        self.assertEqual(self.units[0].status, "RESERVED")

    def test_release_rolls_back_when_one_unit_is_unavailable(self):
        self.approve()
        EquipmentUnit.objects.filter(pk=self.units[1].pk).update(status="MAINTENANCE")
        with self.assertRaises(ValidationError):
            release_request(self.request.pk, actor=self.admin)
        self.units[0].refresh_from_db()
        self.request.refresh_from_db()
        self.assertEqual(self.units[0].status, "RESERVED")
        self.assertEqual(self.request.status, "APPROVED")
        self.assertFalse(Loan.objects.exists())

    def test_release_rejects_expired_due_date(self):
        self.approve()
        with patch("apps.loans.services.timezone.now", return_value=self.request.due_at + timedelta(seconds=1)):
            with self.assertRaises(ValidationError):
                release_request(self.request.pk, actor=self.admin)
        self.assertFalse(Loan.objects.exists())

    def test_release_rejects_inactive_borrower(self):
        self.approve()
        get_user_model().objects.filter(pk=self.borrower.pk).update(is_active=False)
        with self.assertRaises(ValidationError):
            release_request(self.request.pk, actor=self.admin)

    def test_partial_return(self):
        loan = self.issue()
        item = loan.units.first()
        process_returns(loan.pk, actor=self.admin, returns=[(item.pk, "GOOD", "Case included")])
        loan.refresh_from_db()
        item.refresh_from_db()
        self.request.refresh_from_db()
        self.assertIsNone(loan.completed_at)
        self.assertEqual(loan.outstanding_count, 1)
        self.assertEqual(loan.status, "Partially returned")
        self.assertEqual(self.request.status, "ISSUED")
        self.assertIsNotNone(item.returned_at)
        self.assertEqual(item.received_by, self.admin)
        self.assertEqual(item.return_notes, "Case included")
        self.assertEqual(item.unit.status, "AVAILABLE")
        self.assertFalse(item.allocation.active)

    def test_full_return_completes_loan_and_request(self):
        loan = self.issue()
        self.return_all(loan)
        loan.refresh_from_db()
        self.request.refresh_from_db()
        self.assertIsNotNone(loan.completed_at)
        self.assertEqual(self.request.status, "COMPLETED")
        self.assertEqual(loan.outstanding_count, 0)
        self.assertEqual(loan.status, "Completed")
        self.assertEqual(EquipmentUnit.objects.filter(status="AVAILABLE").count(), 2)
        self.assertFalse(Allocation.objects.filter(active=True).exists())

    def test_last_partial_return_completes_loan(self):
        loan = self.issue()
        items = list(loan.units.all())
        process_returns(loan.pk, actor=self.admin, returns=[(items[0].pk, "GOOD", "")])
        process_returns(loan.pk, actor=self.admin, returns=[(items[1].pk, "GOOD", "")])
        loan.refresh_from_db()
        self.assertIsNotNone(loan.completed_at)

    def test_damaged_return_routes_unit_to_maintenance(self):
        loan = self.issue()
        item = loan.units.first()
        process_returns(loan.pk, actor=self.admin, returns=[(item.pk, "DAMAGED", "Lens cracked")])
        item.refresh_from_db()
        self.assertEqual(item.unit.status, "MAINTENANCE")
        self.assertEqual(item.return_condition, "DAMAGED")
        self.assertEqual(item.return_notes, "Lens cracked")
        self.assertFalse(item.allocation.active)

    def test_duplicate_return_is_rejected_without_overwriting_record(self):
        loan = self.issue()
        item = loan.units.first()
        process_returns(loan.pk, actor=self.admin, returns=[(item.pk, "GOOD", "Original record")])
        item.refresh_from_db()
        original_date = item.returned_at
        with self.assertRaises(ValidationError):
            process_returns(loan.pk, actor=self.admin, returns=[(item.pk, "DAMAGED", "Overwritten")])
        item.refresh_from_db()
        self.assertEqual(item.return_notes, "Original record")
        self.assertEqual(item.returned_at, original_date)

    def test_return_from_completed_loan_is_rejected(self):
        loan = self.issue()
        self.return_all(loan)
        with self.assertRaises(ValidationError):
            process_returns(loan.pk, actor=self.admin, returns=[(loan.units.first().pk, "GOOD", "")])

    def test_unauthorized_return(self):
        loan = self.issue()
        with self.assertRaises(PermissionDenied):
            process_returns(loan.pk, actor=self.borrower, returns=[(loan.units.first().pk, "GOOD", "")])
        self.assertEqual(loan.outstanding_count, 2)

    def test_return_validation_rejects_empty_duplicate_invalid_condition_and_notes(self):
        loan = self.issue()
        item_id = loan.units.first().pk
        cases = [[], [(item_id, "GOOD", ""), (item_id, "GOOD", "")], [(item_id, "INVALID", "")], [(item_id, "DAMAGED", "  ")], [(item_id, "GOOD", "x" * 1001)]]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                process_returns(loan.pk, actor=self.admin, returns=data)
        self.assertEqual(loan.outstanding_count, 2)

    def test_units_cannot_be_returned_against_another_loan(self):
        loan = self.issue()
        other_loan = self.make_other_loan()
        with self.assertRaises(ValidationError):
            process_returns(loan.pk, actor=self.admin, returns=[(other_loan.units.first().pk, "GOOD", "")])
        self.assertEqual(other_loan.outstanding_count, 1)

    def test_return_rolls_back_every_unit_on_invalid_inventory_status(self):
        loan = self.issue()
        items = list(loan.units.all())
        EquipmentUnit.objects.filter(pk=items[1].unit_id).update(status="MAINTENANCE")
        with self.assertRaises(ValidationError):
            process_returns(loan.pk, actor=self.admin, returns=[(item.pk, "GOOD", "") for item in items])
        items[0].refresh_from_db()
        self.assertIsNone(items[0].returned_at)
        self.assertEqual(items[0].unit.status, "ON_LOAN")
        self.assertTrue(items[0].allocation.active)

    def test_return_rejects_invalid_request_transition(self):
        loan = self.issue()
        BorrowingRequest.objects.filter(pk=self.request.pk).update(status="CANCELLED")
        with self.assertRaises(ValidationError):
            self.return_all(loan)
        self.assertEqual(loan.outstanding_count, 2)

    def test_returned_available_unit_can_be_issued_in_a_new_loan(self):
        first = self.issue()
        self.return_all(first)
        request = BorrowingRequest.objects.create(borrower=self.borrower, purpose="Another presentation", due_at=timezone.now() + timedelta(days=3))
        item = BorrowingRequestItem.objects.create(request=request, equipment=self.equipment, quantity=1)
        approve_request(request.pk, reason="Approved for the test borrowing activity.", actor=self.admin, allocations={item.pk: [self.units[0].pk]})
        second = release_request(request.pk, actor=self.admin)
        self.assertEqual(second.quantity, 1)
        self.assertEqual(LoanUnit.objects.filter(unit=self.units[0], returned_at__isnull=True).count(), 1)
        self.assertEqual(first.units.count(), 2)

    def test_overdue_is_dynamic_and_exact_due_boundary_is_not_overdue(self):
        loan = self.issue()
        with patch("apps.loans.models.timezone.now", return_value=loan.due_at):
            self.assertFalse(loan.is_overdue)
            self.assertFalse(Loan.objects.overdue().exists())
        with patch("apps.loans.models.timezone.now", return_value=loan.due_at + timedelta(days=1)):
            self.assertTrue(loan.is_overdue)
            self.assertEqual(loan.status, "Overdue")
            self.assertEqual(Loan.objects.overdue().count(), 1)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, "ISSUED")

    def test_partial_overdue_remains_overdue_and_completed_loan_does_not(self):
        loan = self.issue()
        with patch("apps.loans.models.timezone.now", return_value=loan.due_at + timedelta(days=1)):
            process_returns(loan.pk, actor=self.admin, returns=[(loan.units.first().pk, "GOOD", "")])
            self.assertTrue(loan.is_overdue)
            self.return_all(Loan.objects.get(pk=loan.pk))
            loan.refresh_from_db()
            self.assertFalse(loan.is_overdue)
            self.assertFalse(Loan.objects.overdue().exists())

    def test_history_records_cannot_be_deleted_through_related_inventory(self):
        self.issue()
        with self.assertRaises(ProtectedError):
            self.units[0].delete()
        with self.assertRaises(ProtectedError):
            self.request.delete()

    def test_database_enforces_single_active_issue(self):
        loan = self.issue()
        # A separate allocation can refer to the same physical unit historically;
        # it still cannot create a second outstanding LoanUnit.
        request = BorrowingRequest.objects.create(borrower=self.other, purpose="Duplicate attempt", due_at=timezone.now() + timedelta(days=3))
        item = BorrowingRequestItem.objects.create(request=request, equipment=self.equipment, quantity=1)
        allocation = Allocation.objects.create(request_item=item, unit=self.units[0], active=False)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LoanUnit.objects.create(loan=loan, allocation=allocation, unit=self.units[0], equipment_name="Projector", asset_tag="PROJECTOR-0")


class FoundationTests(LoanFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def test_approval_reserves_exact_units_and_records_actor(self):
        request = self.approve()
        self.assertEqual(request.status, "APPROVED")
        self.assertEqual(request.approved_by, self.admin)
        self.assertIsNotNone(request.approved_at)
        self.assertEqual(EquipmentUnit.objects.filter(status="RESERVED").count(), 2)

    def test_approval_rejects_wrong_role_duplicate_units_and_wrong_quantities(self):
        with self.assertRaises(PermissionDenied):
            approve_request(self.request.pk, reason="Approved for the test borrowing activity.", actor=self.borrower, allocations={self.item.pk: [u.pk for u in self.units]})
        for allocations in [{}, {self.item.pk: [self.units[0].pk]}, {self.item.pk: [self.units[0].pk] * 2}]:
            with self.subTest(allocations=allocations), self.assertRaises(ValidationError):
                approve_request(self.request.pk, reason="Approved for the test borrowing activity.", actor=self.admin, allocations=allocations)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, "PENDING")
        self.assertFalse(Allocation.objects.exists())

    def test_approval_rolls_back_all_reservations_if_a_unit_is_unavailable(self):
        EquipmentUnit.objects.filter(pk=self.units[1].pk).update(status="MAINTENANCE")
        with self.assertRaises(ValidationError):
            self.approve()
        self.units[0].refresh_from_db()
        self.assertEqual(self.units[0].status, "AVAILABLE")
        self.assertFalse(Allocation.objects.exists())

    def test_damaged_unit_cannot_be_reserved(self):
        loan = self.issue()
        item = loan.units.first()
        process_returns(loan.pk, actor=self.admin, returns=[(item.pk, "DAMAGED", "Broken lens")])
        request = BorrowingRequest.objects.create(borrower=self.borrower, purpose="New request", due_at=timezone.now() + timedelta(days=3))
        new_item = BorrowingRequestItem.objects.create(request=request, equipment=self.equipment, quantity=1)
        with self.assertRaises(ValidationError):
            approve_request(request.pk, reason="Approved for the test borrowing activity.", actor=self.admin, allocations={new_item.pk: [item.unit_id]})


class LoanPageTests(LoanFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def test_anonymous_and_wrong_role_access(self):
        self.approve()
        admin_pages = [reverse("loan_management"), reverse("returns_overdue"), reverse("release_equipment", args=[self.request.pk])]
        user_pages = [reverse("my_loans"), reverse("borrowing_history")]
        for url in admin_pages + user_pages:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.borrower)
        for url in admin_pages:
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, {"confirm": "on"}).status_code, 403)
        self.client.force_login(self.admin)
        for url in user_pages:
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_staff_flag_does_not_grant_admin_access(self):
        self.borrower.is_staff = True
        self.borrower.is_superuser = True
        self.borrower.save()
        self.client.force_login(self.borrower)
        self.assertEqual(self.client.get(reverse("loan_management")).status_code, 403)

    def test_all_admin_pages_render_and_get_does_not_change_data(self):
        self.approve()
        self.client.force_login(self.admin)
        for name in ["loan_management", "release_equipment"]:
            response = self.client.get(reverse(name, args=[self.request.pk] if name == "release_equipment" else []))
            self.assertEqual(response.status_code, 200)
        self.assertFalse(Loan.objects.exists())
        loan = release_request(self.request.pk, actor=self.admin)
        for name in ["returns_overdue", "admin_loan_detail", "return_equipment", "borrowing_slip"]:
            response = self.client.get(reverse(name, args=[] if name == "returns_overdue" else [loan.pk]))
            self.assertEqual(response.status_code, 200)
        self.assertEqual(loan.outstanding_count, 2)

    def test_incomplete_approved_request_is_marked_not_ready(self):
        self.approve()
        Allocation.objects.filter(unit=self.units[1]).update(active=False)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("loan_management")), "Needs review")
        response = self.client.get(reverse("release_equipment", args=[self.request.pk]))
        self.assertContains(response, "fully allocated before release")
        self.assertNotContains(response, 'id="release-form"')

    def test_release_requires_confirmation_and_post_redirects_to_loan(self):
        self.approve()
        self.client.force_login(self.admin)
        url = reverse("release_equipment", args=[self.request.pk])
        response = self.client.post(url, {})
        self.assertContains(response, "Confirm the handover")
        self.assertFalse(Loan.objects.exists())
        response = self.client.post(url, {"confirm": "on"}, follow=True)
        self.assertContains(response, "The reserved equipment has been released")
        self.assertEqual(Loan.objects.count(), 1)
        response = self.client.post(url, {"confirm": "on"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Loan.objects.count(), 1)

    def test_basic_user_cannot_release_or_return_or_print_admin_slip(self):
        loan = self.issue()
        self.client.force_login(self.borrower)
        for name in ["admin_loan_detail", "return_equipment", "borrowing_slip"]:
            self.assertEqual(self.client.get(reverse(name, args=[loan.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("return_equipment", args=[loan.pk]), self.return_post(loan)).status_code, 403)
        self.assertEqual(loan.outstanding_count, 2)

    def test_basic_user_data_isolation_for_loans_and_details(self):
        own = self.issue()
        other = self.make_other_loan()
        self.client.force_login(self.borrower)
        response = self.client.get(reverse("my_loans"))
        self.assertContains(response, "Projector")
        self.assertNotContains(response, "Private equipment")
        self.assertEqual(self.client.get(reverse("user_loan_detail", args=[own.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("user_loan_detail", args=[other.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("my_loans"), {"q": "Private"}), "Private equipment")

    def test_basic_user_history_contains_only_own_completed_loans(self):
        own = self.issue()
        other = self.make_other_loan()
        self.return_all(own)
        self.return_all(other)
        self.client.force_login(self.borrower)
        history = self.client.get(reverse("borrowing_history"))
        self.assertContains(history, "Projector")
        self.assertNotContains(history, "Private equipment")
        self.assertNotContains(self.client.get(reverse("my_loans")), "Projector")
        detail = self.client.get(reverse("user_loan_detail", args=[own.pk]))
        self.assertContains(detail, "Good / undamaged")
        self.assertContains(detail, "Completed")

    def test_empty_states_and_navigation_links(self):
        self.client.force_login(self.borrower)
        response = self.client.get(reverse("my_loans"))
        self.assertContains(response, "No active loans")
        self.assertContains(response, 'href="/portal/loans/"')
        self.assertContains(response, 'href="/portal/history/"')
        self.client.force_login(self.admin)
        response = self.client.get(reverse("loan_management"))
        self.assertContains(response, "No approved requests")
        self.assertContains(response, 'href="/manage/returns/"')

    def test_overdue_and_date_filters_and_invalid_range(self):
        loan = self.issue()
        self.client.force_login(self.borrower)
        self.assertNotContains(self.client.get(reverse("my_loans"), {"status": "overdue"}), "Projector")
        with patch("apps.loans.models.timezone.now", return_value=loan.due_at + timedelta(days=1)):
            response = self.client.get(reverse("my_loans"), {"status": "overdue"})
            self.assertContains(response, "Projector")
            self.assertContains(response, "Overdue")
        response = self.client.get(reverse("my_loans"), {"due_from": "2030-01-02", "due_to": "2030-01-01"})
        self.assertContains(response, "End date must be on or after")
        self.assertNotContains(response, "Projector")
        self.assertContains(self.client.get(reverse("my_loans"), {"q": "PROJECTOR-0", "due_from": timezone.localdate().isoformat()}), "Projector")

    def test_admin_search_partial_filter_and_ready_requests_disappear_after_release(self):
        self.approve()
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("loan_management"), {"q": self.borrower.username}), "Projector")
        loan = release_request(self.request.pk, actor=self.admin)
        self.assertNotContains(self.client.get(reverse("loan_management")), "Projector")
        self.assertContains(self.client.get(reverse("returns_overdue"), {"q": "PROJECTOR-0"}), "Projector")
        self.assertNotContains(self.client.get(reverse("returns_overdue"), {"status": "partial"}), "Projector")
        process_returns(loan.pk, actor=self.admin, returns=[(loan.units.first().pk, "GOOD", "")])
        self.assertContains(self.client.get(reverse("returns_overdue"), {"status": "partial"}), "Projector")

    def test_post_partial_then_full_return(self):
        loan = self.issue()
        self.client.force_login(self.admin)
        url = reverse("return_equipment", args=[loan.pk])
        response = self.client.post(url, self.return_post(loan, selected=[loan.units.first().pk]), follow=True)
        self.assertContains(response, "Selected units returned")
        self.assertEqual(loan.outstanding_count, 1)
        response = self.client.post(url, self.return_post(loan), follow=True)
        self.assertContains(response, "the loan is completed")
        loan.refresh_from_db()
        self.assertIsNotNone(loan.completed_at)

    def test_post_to_completed_loan_returns_conflict_without_changing_history(self):
        loan = self.issue()
        data = self.return_post(loan)
        self.return_all(loan)
        original = list(loan.units.values_list("pk", "returned_at", "return_condition"))
        self.client.force_login(self.admin)
        response = self.client.post(reverse("return_equipment", args=[loan.pk]), data)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Additional returns cannot be recorded", status_code=409)
        self.assertEqual(list(loan.units.values_list("pk", "returned_at", "return_condition")), original)

    def test_post_damaged_return_requires_notes_and_routes_to_maintenance(self):
        loan = self.issue()
        self.client.force_login(self.admin)
        url = reverse("return_equipment", args=[loan.pk])
        data = self.return_post(loan)
        data["units-0-condition"] = "DAMAGED"
        self.assertContains(self.client.post(url, data), "Describe the damage")
        self.assertEqual(loan.outstanding_count, 2)
        data["units-0-notes"] = "Cracked casing"
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.units[0].refresh_from_db()
        self.assertEqual(self.units[0].status, "MAINTENANCE")

    def test_return_confirmation_required(self):
        loan = self.issue()
        self.client.force_login(self.admin)
        data = self.return_post(loan)
        data.pop("confirm")
        self.assertContains(self.client.post(reverse("return_equipment", args=[loan.pk]), data), "Confirm the physical return")
        self.assertEqual(loan.outstanding_count, 2)

    def test_empty_selection_invalid_condition_and_missing_management_form(self):
        loan = self.issue()
        self.client.force_login(self.admin)
        url = reverse("return_equipment", args=[loan.pk])
        data = self.return_post(loan, selected=[])
        self.assertContains(self.client.post(url, data), "Select at least one physical unit")
        data = self.return_post(loan)
        data["units-0-condition"] = "INVALID"
        self.assertContains(self.client.post(url, data), "Select a valid choice")
        self.assertEqual(self.client.post(url, {"confirm": "on"}).status_code, 200)
        self.assertEqual(loan.outstanding_count, 2)

    def test_tampered_or_duplicate_form_ids_are_rejected(self):
        loan = self.issue()
        other = self.make_other_loan()
        self.client.force_login(self.admin)
        url = reverse("return_equipment", args=[loan.pk])
        for bad_id in [other.units.first().pk, loan.units.first().pk]:
            data = self.return_post(loan)
            data["units-1-loan_unit_id"] = str(bad_id)
            self.assertContains(self.client.post(url, data), "form contains invalid units")
        self.assertEqual(loan.outstanding_count, 2)
        self.assertEqual(other.outstanding_count, 1)

    def test_stale_return_form_cannot_overwrite_a_previous_return(self):
        loan = self.issue()
        self.client.force_login(self.admin)
        data = self.return_post(loan)
        process_returns(loan.pk, actor=self.admin, returns=[(loan.units.first().pk, "GOOD", "First return")])
        response = self.client.post(reverse("return_equipment", args=[loan.pk]), data)
        self.assertContains(response, "loan changed")
        self.assertEqual(loan.outstanding_count, 1)
        self.assertEqual(loan.units.first().return_notes, "First return")

    def test_csrf_is_required_on_release_and_returns(self):
        self.approve()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(reverse("release_equipment", args=[self.request.pk]), {"confirm": "on"}).status_code, 403)
        loan = release_request(self.request.pk, actor=self.admin)
        self.assertEqual(client.post(reverse("return_equipment", args=[loan.pk]), self.return_post(loan)).status_code, 403)

    def test_printable_slip_contains_units_and_handover_details(self):
        loan = self.issue()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("borrowing_slip", args=[loan.pk]))
        for text in ["Borrowing slip", "PROJECTOR-0", "PROJECTOR-1", "Borrower signature", "Releasing Admin signature", "Due date"]:
            self.assertContains(response, text)

    def test_pagination_retains_filters_and_handles_invalid_page(self):
        for index in range(21):
            request = BorrowingRequest.objects.create(borrower=self.borrower, purpose="Pagination test", due_at=timezone.now() + timedelta(days=2))
            item = BorrowingRequestItem.objects.create(request=request, equipment=self.equipment, quantity=1)
            unit = EquipmentUnit.objects.create(equipment=self.equipment, asset_tag=f"PAGE-{index}")
            approve_request(request.pk, reason="Approved for the test borrowing activity.", actor=self.admin, allocations={item.pk: [unit.pk]})
            release_request(request.pk, actor=self.admin)
        self.client.force_login(self.borrower)
        first = self.client.get(reverse("my_loans"), {"q": "Projector"})
        self.assertEqual(len(first.context["page_obj"]), 10)
        self.assertContains(first, "q=Projector&amp;page=2")
        second = self.client.get(reverse("my_loans"), {"q": "Projector", "page": "2"})
        self.assertEqual(len(second.context["page_obj"]), 10)
        third = self.client.get(second.wsgi_request.path, {**second.wsgi_request.GET.dict(), "page": "3"})
        self.assertEqual(len(third.context["page_obj"]), 1)
        self.assertContains(third, "Showing 21–21 of 21 records.")
        self.assertEqual(self.client.get(reverse("my_loans"), {"page": "invalid"}).status_code, 200)

    def test_formset_rejects_forged_excess_rows(self):
        loan = self.issue()
        self.client.force_login(self.admin)
        data = self.return_post(loan)
        data["units-TOTAL_FORMS"] = "100000"
        response = self.client.post(reverse("return_equipment", args=[loan.pk]), data)
        self.assertContains(response, "Maximum unit rows: 2")
        self.assertEqual(loan.outstanding_count, 2)


class LoanSummaryPresentationTests(LoanFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def assert_summary(self, loan, *, status, outstanding, completed=False):
        for actor, route in [(self.borrower, "user_loan_detail"), (self.admin, "admin_loan_detail")]:
            with self.subTest(role=actor.role, status=status):
                self.client.force_login(actor)
                response = self.client.get(reverse(route, args=[loan.pk]))
                self.assertEqual(response.status_code, 200)
                for heading in ["Loan information", "Timeline", "Status", "Purpose"]:
                    self.assertContains(response, heading)
                self.assertContains(response, f"<dt>Borrowing request</dt><dd>#{loan.request_id}</dd>", html=True)
                self.assertContains(response, f"<dt>Current loan status</dt><dd>{status}</dd>", html=True)
                self.assertContains(response, f"<dt>Outstanding units</dt><dd>{outstanding} of 2</dd>", html=True)
                self.assertContains(response, "<dt>Issued date</dt>", html=True)
                self.assertContains(response, "<dt>Due date</dt>", html=True)
                self.assertContains(response, 'aria-label="Issued physical units and return history"')
                self.assertContains(response, "Class presentation")
                if completed:
                    self.assertContains(response, "Completed / returned")
                else:
                    self.assertNotContains(response, "Completed / returned")
                return_url = reverse("return_equipment", args=[loan.pk])
                if actor == self.admin:
                    self.assertContains(response, reverse("borrowing_slip", args=[loan.pk]))
                    if completed:
                        self.assertNotContains(response, return_url)
                    else:
                        self.assertContains(response, return_url)
                else:
                    self.assertNotContains(response, "/manage/")
                    self.assertContains(response, reverse("borrowing_history" if completed else "my_loans"))

    def test_summary_and_return_history_follow_active_partial_and_completed_states(self):
        loan = self.issue()
        self.assert_summary(loan, status="Active", outstanding=2)
        units = list(loan.units.all())
        process_returns(loan.pk, actor=self.admin, returns=[(units[0].pk, "GOOD", "Case checked on receipt")])
        self.assert_summary(loan, status="Partially returned", outstanding=1)
        process_returns(loan.pk, actor=self.admin, returns=[(units[1].pk, "DAMAGED", "Cracked case; needs inspection")])
        self.assert_summary(loan, status="Completed", outstanding=0, completed=True)
        response = self.client.get(reverse("admin_loan_detail", args=[loan.pk]))
        for text in ["Good / undamaged", "Made Available", "Damaged", "Sent to Maintenance", "Case checked on receipt", "Cracked case; needs inspection"]:
            self.assertContains(response, text)

    def test_overdue_summary_keeps_warning_and_return_permissions(self):
        loan = self.issue()
        with patch("apps.loans.models.timezone.now", return_value=loan.due_at + timedelta(days=1)):
            self.assert_summary(loan, status="Overdue", outstanding=2)
            self.assertContains(self.client.get(reverse("admin_loan_detail", args=[loan.pk])), "This loan is overdue.")

    def test_purpose_and_return_notes_remain_escaped_with_line_breaks(self):
        BorrowingRequest.objects.filter(pk=self.request.pk).update(purpose="Class presentation\n<script>purpose</script>")
        loan = self.issue()
        process_returns(loan.pk, actor=self.admin, returns=[(loan.units.first().pk, "GOOD", "Received\n<script>notes</script>")])
        for actor, route in [(self.borrower, "user_loan_detail"), (self.admin, "admin_loan_detail")]:
            self.client.force_login(actor)
            response = self.client.get(reverse(route, args=[loan.pk]))
            self.assertContains(response, "Class presentation<br>&lt;script&gt;purpose&lt;/script&gt;")
            self.assertContains(response, "Received<br>&lt;script&gt;notes&lt;/script&gt;")
            self.assertNotContains(response, "<script>purpose</script>")
            self.assertNotContains(response, "<script>notes</script>")


class DemoFixtureTests(LoanFixtures, TestCase):
    def setUp(self):
        self.make_records()

    @override_settings(DEBUG=True)
    def test_demo_creates_ready_request_and_overdue_loan_without_modifying_accounts(self):
        output = StringIO()
        users_before = list(get_user_model().objects.values_list("pk", "role", "password"))
        call_command("seed_loans_demo", admin=self.admin.username, borrower=self.borrower.username, stdout=output)
        self.assertEqual(EquipmentUnit.objects.filter(asset_tag__startswith="LOANS-DEMO-").count(), 4)
        self.assertEqual(BorrowingRequest.objects.filter(status="APPROVED").count(), 1)
        self.assertEqual(Loan.objects.overdue().count(), 1)
        self.assertEqual(list(get_user_model().objects.values_list("pk", "role", "password")), users_before)
        self.assertIn("Ready request", output.getvalue())
        with self.assertRaises(CommandError):
            call_command("seed_loans_demo", admin=self.admin.username, borrower=self.borrower.username, stdout=output)
        self.assertEqual(EquipmentUnit.objects.filter(asset_tag__startswith="LOANS-DEMO-").count(), 4)

    @override_settings(DEBUG=False)
    def test_demo_is_disabled_outside_debug(self):
        with self.assertRaises(CommandError):
            call_command("seed_loans_demo", admin=self.admin.username, borrower=self.borrower.username)
        self.assertFalse(EquipmentUnit.objects.filter(asset_tag__startswith="LOANS-DEMO-").exists())

    @override_settings(DEBUG=True)
    def test_demo_requires_existing_accounts_with_correct_roles(self):
        with self.assertRaises(CommandError):
            call_command("seed_loans_demo", admin=self.borrower.username, borrower=self.other.username)
        self.assertFalse(EquipmentUnit.objects.filter(asset_tag__startswith="LOANS-DEMO-").exists())


class ConcurrentLoanTests(LoanFixtures, TransactionTestCase):
    def setUp(self):
        self.make_records()

    def race(self, operation):
        barrier = Barrier(2)

        def worker():
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
            results = list(executor.map(lambda _: worker(), range(2)))
        self.assertEqual(sorted(results), ["rejected", "saved"])

    def test_two_simultaneous_releases_issue_only_one_loan(self):
        self.approve()
        self.race(lambda: release_request(self.request.pk, actor=self.admin))
        self.assertEqual(Loan.objects.count(), 1)
        self.assertEqual(LoanUnit.objects.count(), 2)

    def test_two_simultaneous_returns_record_only_one_return(self):
        loan = self.issue()
        item = loan.units.first()
        self.race(lambda: process_returns(loan.pk, actor=self.admin, returns=[(item.pk, "GOOD", "")]))
        self.assertEqual(loan.units.filter(returned_at__isnull=False).count(), 1)
        self.assertEqual(Allocation.objects.filter(active=False).count(), 1)
