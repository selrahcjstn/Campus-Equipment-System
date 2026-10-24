from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone
from threading import Barrier
from unittest.mock import patch
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command, CommandError
from django.db import IntegrityError, OperationalError, close_old_connections, connections, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.dashboard.models import SystemSetting
from apps.inventory.models import Equipment, EquipmentUnit
from apps.loans.models import Loan
from apps.loans.services import process_returns, release_request
from .forms import BorrowingRequestForm
from .models import Allocation, BorrowingRequest, BorrowingRequestItem
from .services import approve_request, cancel_request, catalog_queryset, reject_request, submit_request


class BorrowingFixtures:
    def make_records(self):
        User = get_user_model()
        self.admin = User.objects.create_user("request-admin", role="ADMIN")
        self.borrower = User.objects.create_user("request-borrower", role="BASIC_USER")
        self.other = User.objects.create_user("other-request-borrower", role="BASIC_USER")
        self.equipment = []
        for index in range(4):
            equipment = Equipment.objects.create(name=f"Equipment {index}", description="Classroom equipment")
            self.equipment.append(equipment)
            for number in range(3):
                EquipmentUnit.objects.create(equipment=equipment, asset_tag=f"EQ-{index}-{number}")
        self.due = timezone.now() + timedelta(days=3)

    def submit(self, *, borrower=None, items=None, due=None, purpose="Class presentation"):
        return submit_request(borrower=borrower or self.borrower, purpose=purpose,
                              due_at=due or self.due,
                              items=items if items is not None else [(self.equipment[0].pk, 2)])

    def post_data(self, items=None, due_date=None):
        items = items if items is not None else [(self.equipment[0].pk, 2)]
        data = {"purpose": "Class presentation", "due_date": due_date or (timezone.localdate() + timedelta(days=3)).isoformat(),
                "items-TOTAL_FORMS": str(max(3, len(items))), "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "3"}
        for index in range(max(3, len(items))):
            equipment_id, quantity = items[index] if index < len(items) else ("", 1)
            data[f"items-{index}-equipment"] = str(equipment_id)
            data[f"items-{index}-quantity"] = str(quantity)
        return data


class BorrowingServiceTests(BorrowingFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def test_submit_one_two_or_three_distinct_catalog_items(self):
        for count in [1, 2, 3]:
            request = self.submit(items=[(equipment.pk, 1) for equipment in self.equipment[:count]])
            self.assertEqual(request.status, "PENDING")
            self.assertEqual(request.borrower, self.borrower)
            self.assertEqual(request.items.count(), count)
            self.assertEqual(request.quantity, count)
        self.assertFalse(Allocation.objects.exists())
        self.assertEqual(EquipmentUnit.objects.filter(status="AVAILABLE").count(), 12)

    def test_item_limit_and_empty_request(self):
        for items in [[], [(item.pk, 1) for item in self.equipment]]:
            with self.subTest(items=items), self.assertRaises(ValidationError):
                self.submit(items=items)
        self.assertFalse(BorrowingRequest.objects.exists())

    def test_quantity_limit_and_invalid_quantities(self):
        for quantity in [-1, 0, 4, 1.5, True, "2"]:
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                self.submit(items=[(self.equipment[0].pk, quantity)])
        self.assertFalse(BorrowingRequest.objects.exists())

    def test_duplicate_and_nonexistent_catalog_items(self):
        for items in [[(self.equipment[0].pk, 1)] * 2, [(999999, 1)]]:
            with self.assertRaises(ValidationError):
                self.submit(items=items)
        self.assertFalse(BorrowingRequest.objects.exists())

    def test_duration_limit_past_and_naive_dates(self):
        for due in [timezone.now() + timedelta(days=8), timezone.now() - timedelta(seconds=1), datetime(2030, 1, 1)]:
            with self.subTest(due=due), self.assertRaises(ValidationError):
                self.submit(due=due)
        self.assertFalse(BorrowingRequest.objects.exists())

    def test_seven_calendar_day_boundary_in_local_timezone(self):
        frozen = datetime(2026, 10, 14, 15, 30, tzinfo=dt_timezone.utc)
        with timezone.override("Asia/Manila"), patch("django.utils.timezone.now", return_value=frozen):
            latest = timezone.localdate() + timedelta(days=7)
            form = BorrowingRequestForm({"purpose": "Calendar boundary", "due_date": latest.isoformat()})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(timezone.localdate(form.cleaned_data["due_at"]), latest)
            form = BorrowingRequestForm({"purpose": "Too long", "due_date": (latest + timedelta(days=1)).isoformat()})
            self.assertFalse(form.is_valid())

    @override_settings(BORROWING_MAX_ITEMS=1, BORROWING_MAX_QUANTITY=2, BORROWING_MAX_DAYS=2)
    def test_configurable_limits_enforced_by_service(self):
        with self.assertRaises(ValidationError):
            self.submit(items=[(item.pk, 1) for item in self.equipment[:2]], due=timezone.now() + timedelta(days=1))
        with self.assertRaises(ValidationError):
            self.submit(items=[(self.equipment[0].pk, 3)], due=timezone.now() + timedelta(days=1))
        with self.assertRaises(ValidationError):
            self.submit(due=timezone.now() + timedelta(days=3))
        self.assertEqual(self.submit(due=timezone.now() + timedelta(days=1)).status, "PENDING")

    def test_purpose_validation(self):
        for purpose in ["", "   ", "x" * 1001]:
            with self.assertRaises(ValidationError):
                self.submit(purpose=purpose)

    def test_only_active_basic_users_can_submit(self):
        with self.assertRaises(PermissionDenied):
            self.submit(borrower=self.admin)
        self.borrower.is_active = False
        with self.assertRaises(PermissionDenied):
            self.submit()

    def test_insufficient_availability_at_submission(self):
        EquipmentUnit.objects.filter(equipment=self.equipment[0]).update(status="MAINTENANCE")
        with self.assertRaises(ValidationError):
            self.submit()
        self.assertFalse(BorrowingRequest.objects.exists())

    def test_catalog_excludes_active_reservations_even_if_status_is_inconsistent(self):
        request = self.submit(items=[(self.equipment[0].pk, 1)])
        approve_request(request.pk, actor=self.admin)
        allocated = Allocation.objects.get(request_item__request=request)
        EquipmentUnit.objects.filter(pk=allocated.unit_id).update(status="AVAILABLE")
        self.assertEqual(catalog_queryset().get(pk=self.equipment[0].pk).available_count, 2)
        with self.assertRaises(ValidationError):
            self.submit(items=[(self.equipment[0].pk, 3)])

    def test_successful_automatic_allocation_reserves_exact_quantities(self):
        request = self.submit(items=[(self.equipment[0].pk, 2), (self.equipment[1].pk, 1)])
        approved = approve_request(request.pk, actor=self.admin)
        self.assertEqual(approved.status, "APPROVED")
        self.assertEqual(approved.approved_by, self.admin)
        self.assertIsNotNone(approved.approved_at)
        self.assertEqual(Allocation.objects.filter(request_item__request=request, active=True).count(), 3)
        self.assertEqual(EquipmentUnit.objects.filter(status="RESERVED").count(), 3)
        self.assertFalse(Loan.objects.exists())

    def test_approval_revalidates_availability_and_rolls_back_every_item(self):
        request = self.submit(items=[(self.equipment[0].pk, 2), (self.equipment[1].pk, 2)])
        EquipmentUnit.objects.filter(equipment=self.equipment[1]).update(status="MAINTENANCE")
        with self.assertRaises(ValidationError):
            approve_request(request.pk, actor=self.admin)
        request.refresh_from_db()
        self.assertEqual(request.status, "PENDING")
        self.assertIsNone(request.approved_at)
        self.assertFalse(Allocation.objects.exists())
        self.assertEqual(EquipmentUnit.objects.filter(equipment=self.equipment[0], status="AVAILABLE").count(), 3)

    def test_approval_skips_reserved_maintenance_retired_and_issued_units(self):
        units = list(self.equipment[0].units.all())
        EquipmentUnit.objects.filter(pk=units[0].pk).update(status="MAINTENANCE")
        EquipmentUnit.objects.filter(pk=units[1].pk).update(status="RETIRED")
        request = self.submit(items=[(self.equipment[0].pk, 1)])
        approve_request(request.pk, actor=self.admin)
        self.assertEqual(Allocation.objects.get(request_item__request=request).unit_id, units[2].pk)

    def test_duplicate_approval_does_not_allocate_again(self):
        request = self.submit()
        approve_request(request.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            approve_request(request.pk, actor=self.admin)
        self.assertEqual(Allocation.objects.count(), 2)

    def test_approval_revalidates_limits_for_legacy_or_tampered_rows(self):
        request = self.submit()
        request.items.update(quantity=4)
        with self.assertRaises(ValidationError):
            approve_request(request.pk, actor=self.admin)
        request.refresh_from_db()
        self.assertEqual(request.status, "PENDING")

    def test_expired_pending_request_cannot_be_approved(self):
        request = self.submit()
        with patch("django.utils.timezone.now", return_value=self.due + timedelta(days=1)):
            with self.assertRaises(ValidationError):
                approve_request(request.pk, actor=self.admin)

    def test_inactive_borrower_and_non_admin_cannot_approve(self):
        request = self.submit()
        with self.assertRaises(PermissionDenied):
            approve_request(request.pk, actor=self.borrower)
        get_user_model().objects.filter(pk=self.borrower.pk).update(is_active=False)
        with self.assertRaises(ValidationError):
            approve_request(request.pk, actor=self.admin)
        self.assertFalse(Allocation.objects.exists())

    def test_rejection_records_reason_date_and_admin(self):
        request = self.submit()
        rejected = reject_request(request.pk, actor=self.admin, reason="  Needed for an exam  ")
        self.assertEqual(rejected.status, "REJECTED")
        self.assertEqual(rejected.rejection_reason, "Needed for an exam")
        self.assertEqual(rejected.rejected_by, self.admin)
        self.assertIsNotNone(rejected.rejected_at)
        self.assertFalse(Allocation.objects.exists())

    def test_rejection_requires_reason_and_admin(self):
        request = self.submit()
        for reason in ["", " ", "x" * 1001]:
            with self.assertRaises(ValidationError):
                reject_request(request.pk, actor=self.admin, reason=reason)
        with self.assertRaises(PermissionDenied):
            reject_request(request.pk, actor=self.borrower, reason="No")
        request.refresh_from_db()
        self.assertEqual(request.status, "PENDING")

    def test_pending_cancellation_records_borrower_and_does_not_reserve(self):
        request = self.submit()
        cancelled = cancel_request(request.pk, actor=self.borrower)
        self.assertEqual(cancelled.status, "CANCELLED")
        self.assertEqual(cancelled.cancelled_by, self.borrower)
        self.assertIsNotNone(cancelled.cancelled_at)
        self.assertFalse(Allocation.objects.exists())

    def test_approved_cancellation_releases_reservations_and_preserves_history(self):
        request = self.submit()
        approve_request(request.pk, actor=self.admin)
        cancel_request(request.pk, actor=self.borrower)
        request.refresh_from_db()
        self.assertEqual(request.status, "CANCELLED")
        self.assertIsNotNone(request.approved_at)
        self.assertEqual(Allocation.objects.count(), 2)
        self.assertFalse(Allocation.objects.filter(active=True).exists())
        self.assertEqual(EquipmentUnit.objects.filter(equipment=self.equipment[0], status="AVAILABLE").count(), 3)

    def test_admin_can_cancel_approved_request(self):
        request = self.submit()
        approve_request(request.pk, actor=self.admin)
        cancelled = cancel_request(request.pk, actor=self.admin)
        self.assertEqual(cancelled.cancelled_by, self.admin)

    def test_basic_user_cannot_cancel_another_users_request(self):
        request = self.submit()
        with self.assertRaises(PermissionDenied):
            cancel_request(request.pk, actor=self.other)
        request.refresh_from_db()
        self.assertEqual(request.status, "PENDING")

    def test_cancellation_rolls_back_if_a_reserved_unit_has_changed(self):
        request = self.submit()
        approve_request(request.pk, actor=self.admin)
        allocations = list(Allocation.objects.filter(request_item__request=request).order_by("unit_id"))
        EquipmentUnit.objects.filter(pk=allocations[1].unit_id).update(status="ON_LOAN")
        with self.assertRaises(ValidationError):
            cancel_request(request.pk, actor=self.borrower)
        request.refresh_from_db()
        self.assertEqual(request.status, "APPROVED")
        self.assertIsNone(request.cancelled_at)
        self.assertEqual(Allocation.objects.filter(active=True).count(), 2)
        self.assertEqual(EquipmentUnit.objects.get(pk=allocations[0].unit_id).status, "RESERVED")

    def test_invalid_transitions_cannot_modify_terminal_or_issued_requests(self):
        for status in ["REJECTED", "CANCELLED", "ISSUED", "COMPLETED"]:
            request = self.submit()
            BorrowingRequest.objects.filter(pk=request.pk).update(status=status)
            for operation in [
                lambda: approve_request(request.pk, actor=self.admin),
                lambda: reject_request(request.pk, actor=self.admin, reason="Reason"),
                lambda: cancel_request(request.pk, actor=self.borrower),
            ]:
                with self.subTest(status=status), self.assertRaises(ValidationError):
                    operation()

    def test_approved_request_cannot_be_rejected(self):
        request = self.submit()
        approve_request(request.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            reject_request(request.pk, actor=self.admin, reason="No")
        self.assertEqual(Allocation.objects.filter(active=True).count(), 2)

    def test_cancelled_request_cannot_be_issued_and_units_can_be_reserved_again(self):
        request = self.submit()
        approve_request(request.pk, actor=self.admin)
        cancel_request(request.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            release_request(request.pk, actor=self.admin)
        new = self.submit(items=[(self.equipment[0].pk, 3)])
        approve_request(new.pk, actor=self.admin)
        self.assertEqual(Allocation.objects.filter(active=True).count(), 3)

    def test_approval_to_issue_partial_return_and_full_return_integration(self):
        request = self.submit()
        approve_request(request.pk, actor=self.admin)
        loan = release_request(request.pk, actor=self.admin)
        request.refresh_from_db()
        self.assertEqual(request.status, "ISSUED")
        self.assertEqual(request.workflow_label, "Issued")
        with self.assertRaises(ValidationError):
            cancel_request(request.pk, actor=self.borrower)
        items = list(loan.units.all())
        process_returns(loan.pk, actor=self.admin, returns=[(items[0].pk, "GOOD", "")])
        request.refresh_from_db()
        self.assertEqual(request.status, "ISSUED")
        self.assertEqual(request.workflow_label, "Partially Returned")
        process_returns(loan.pk, actor=self.admin, returns=[(items[1].pk, "DAMAGED", "Cracked case")])
        request.refresh_from_db()
        self.assertEqual(request.status, "COMPLETED")
        self.assertEqual(request.workflow_label, "Returned")
        self.assertEqual(Loan.objects.count(), 1)

    def test_overdue_does_not_create_a_request_status(self):
        request = self.submit()
        approve_request(request.pk, actor=self.admin)
        loan = release_request(request.pk, actor=self.admin)
        with patch("django.utils.timezone.now", return_value=loan.due_at + timedelta(seconds=1)):
            self.assertTrue(loan.is_overdue)
        request.refresh_from_db()
        self.assertEqual(request.status, "ISSUED")
        self.assertEqual(request.workflow_label, "Issued")


class BorrowingHardItemLimitTests(BorrowingFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.client.force_login(self.borrower)

    def assert_four_items_leave_records_unchanged(self, operation):
        before = (BorrowingRequest.objects.count(), BorrowingRequestItem.objects.count())
        operation()
        self.assertEqual((BorrowingRequest.objects.count(), BorrowingRequestItem.objects.count()), before)
        self.assertFalse(Allocation.objects.exists())
        self.assertEqual(EquipmentUnit.objects.filter(status="AVAILABLE").count(), 12)

    def assert_service_boundary(self):
        for count in [1, 2, 3]:
            with self.subTest(count=count):
                request = self.submit(items=[(item.pk, 1) for item in self.equipment[:count]])
                self.assertEqual(request.items.count(), count)
                self.assertEqual(request.status, "PENDING")

        def reject_four():
            with self.assertRaisesMessage(ValidationError, "Select 1–3 distinct equipment items."):
                self.submit(items=[(item.pk, 1) for item in self.equipment])
        self.assert_four_items_leave_records_unchanged(reject_four)

    def assert_http_boundary(self):
        url = reverse("new_borrowing_request")
        page = self.client.get(url)
        self.assertContains(page, "Select 1–3 equipment items")
        self.assertEqual(len(page.context["formset"].forms), 1)
        self.assertEqual(page.context["formset"].management_form["MAX_NUM_FORMS"].value(), 3)
        for count in [1, 2, 3]:
            with self.subTest(count=count):
                response = self.client.post(url, self.post_data([(item.pk, 1) for item in self.equipment[:count]]))
                self.assertEqual(response.status_code, 302)

        def reject_four():
            data = self.post_data([(item.pk, 1) for item in self.equipment])
            data["items-MAX_NUM_FORMS"] = "1000"
            response = self.client.post(url, data)
            self.assertContains(response, "Select no more than 3 distinct equipment items.")
            self.assertTrue(response.context["formset"].non_form_errors())
        self.assert_four_items_leave_records_unchanged(reject_four)

    @override_settings(BORROWING_MAX_ITEMS=4)
    def test_service_caps_manipulated_django_setting(self):
        self.assert_service_boundary()

    @override_settings(BORROWING_MAX_ITEMS=4)
    def test_frontend_and_forged_post_cap_manipulated_django_setting(self):
        self.assert_http_boundary()

    def test_service_caps_legacy_database_policy(self):
        for maximum in [4, 10]:
            with self.subTest(max_items=maximum), patch("apps.dashboard.policies.SystemSetting.objects.filter") as policies:
                policies.return_value.first.return_value = SystemSetting(max_items=maximum)
                self.assert_service_boundary()

    def test_frontend_and_forged_post_cap_legacy_database_policy(self):
        with patch("apps.dashboard.policies.SystemSetting.objects.filter") as policies:
            policies.return_value.first.return_value = SystemSetting(max_items=10)
            self.assert_http_boundary()

    def test_service_hard_limit_rejects_even_an_oversized_policy_snapshot(self):
        with patch("apps.borrowing.services.borrowing_limits", return_value={"max_items": 10, "max_quantity": 3, "max_days": 7}):
            self.assert_service_boundary()


class BorrowingPageTests(BorrowingFixtures, TestCase):
    def setUp(self):
        self.make_records()

    def test_user_submission_and_default_unused_slots(self):
        self.client.force_login(self.borrower)
        response = self.client.post(reverse("new_borrowing_request"), self.post_data(), follow=True)
        self.assertContains(response, "submitted for Admin review")
        self.assertEqual(BorrowingRequest.objects.count(), 1)
        self.assertEqual(BorrowingRequestItem.objects.count(), 1)

    def test_http_one_two_and_three_item_submissions(self):
        self.client.force_login(self.borrower)
        for count in [1, 2, 3]:
            response = self.client.post(reverse("new_borrowing_request"), self.post_data([(equipment.pk, 1) for equipment in self.equipment[:count]]))
            self.assertEqual(response.status_code, 302)
        self.assertEqual(BorrowingRequest.objects.count(), 3)

    def test_creation_page_renders_catalog_availability_and_limits(self):
        self.client.force_login(self.borrower)
        response = self.client.get(reverse("new_borrowing_request"))
        self.assertContains(response, "Browse equipment")
        self.assertContains(response, "3 available units")
        self.assertContains(response, "at most 7 calendar days")
        self.assertEqual(len(response.context["formset"]), 1)

    def test_http_quantity_item_duplicate_and_duration_limits(self):
        self.client.force_login(self.borrower)
        cases = [
            self.post_data([(self.equipment[0].pk, 4)]),
            self.post_data([(equipment.pk, 1) for equipment in self.equipment]),
            self.post_data([(self.equipment[0].pk, 1)] * 2),
            self.post_data(due_date=(timezone.localdate() + timedelta(days=8)).isoformat()),
            self.post_data(due_date=(timezone.localdate() - timedelta(days=1)).isoformat()),
        ]
        for data in cases:
            response = self.client.post(reverse("new_borrowing_request"), data)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors or response.context["formset"].errors or response.context["formset"].non_form_errors())
        self.assertFalse(BorrowingRequest.objects.exists())

    def test_http_oversized_or_missing_management_form_and_blank_request(self):
        self.client.force_login(self.borrower)
        for data in [self.post_data(items=[]), {"purpose": "No form data"}, dict(self.post_data(), **{"items-TOTAL_FORMS": "100000"})]:
            response = self.client.post(reverse("new_borrowing_request"), data)
            self.assertEqual(response.status_code, 200)
        self.assertFalse(BorrowingRequest.objects.exists())

    def test_forged_status_borrower_and_availability_are_ignored(self):
        self.client.force_login(self.borrower)
        data = self.post_data()
        data.update(status="APPROVED", borrower=str(self.other.pk), available_count="1000", approved_by=str(self.admin.pk))
        self.assertEqual(self.client.post(reverse("new_borrowing_request"), data).status_code, 302)
        request = BorrowingRequest.objects.get()
        self.assertEqual(request.borrower, self.borrower)
        self.assertEqual(request.status, "PENDING")
        self.assertIsNone(request.approved_by)

    def test_submission_handles_insufficient_quantity_without_creating_request(self):
        EquipmentUnit.objects.filter(equipment=self.equipment[0], asset_tag__endswith="-0").update(status="MAINTENANCE")
        self.client.force_login(self.borrower)
        response = self.client.post(reverse("new_borrowing_request"), self.post_data([(self.equipment[0].pk, 3)]))
        self.assertContains(response, "Not enough available units", status_code=409)
        self.assertFalse(BorrowingRequest.objects.exists())

    def test_anonymous_and_admin_cannot_use_basic_user_pages(self):
        for name in ["my_requests", "new_borrowing_request"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("my_requests")).status_code, 403)
        self.assertEqual(self.client.post(reverse("new_borrowing_request"), self.post_data()).status_code, 403)

    def test_basic_user_isolation_for_list_search_details_and_cancellation(self):
        own = self.submit(purpose="Owned request")
        other = self.submit(borrower=self.other, purpose="Private other purpose")
        self.client.force_login(self.borrower)
        response = self.client.get(reverse("my_requests"))
        self.assertEqual([request.pk for request in response.context["page_obj"]], [own.pk])
        self.assertEqual(self.client.get(reverse("request_detail", args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("cancel_borrowing_request", args=[other.pk]), {"confirm": "on"}).status_code, 404)
        self.assertEqual(len(self.client.get(reverse("my_requests"), {"q": "Private other"}).context["page_obj"]), 0)
        self.assertEqual(self.client.get(reverse("request_detail", args=[own.pk])).status_code, 200)

    def test_basic_users_staff_and_unknown_roles_cannot_review(self):
        request = self.submit()
        self.borrower.is_staff = True
        self.borrower.is_superuser = True
        self.borrower.save()
        for role in ["BASIC_USER", "OTHER"]:
            self.borrower.role = role
            self.borrower.save()
            self.client.force_login(self.borrower)
            for name in ["approve_borrowing_request", "reject_borrowing_request", "admin_cancel_borrowing_request"]:
                self.assertEqual(self.client.post(reverse(name, args=[request.pk]), {"confirm": "on", "rejection_reason": "No"}).status_code, 403)
            self.assertEqual(self.client.get(reverse("borrowing_requests")).status_code, 403)

    def test_admin_queue_defaults_pending_and_all_search_status_filters_work(self):
        pending = self.submit(purpose="Awaiting review")
        rejected = self.submit(purpose="Rejected purpose")
        reject_request(rejected.pk, actor=self.admin, reason="No")
        self.client.force_login(self.admin)
        queue = self.client.get(reverse("borrowing_requests"))
        self.assertEqual([request.pk for request in queue.context["page_obj"]], [pending.pk])
        all_requests = self.client.get(reverse("borrowing_requests"), {"status": ""})
        self.assertEqual(len(all_requests.context["page_obj"]), 2)
        found = self.client.get(reverse("borrowing_requests"), {"q": self.borrower.username, "status": "REJECTED"})
        self.assertEqual([request.pk for request in found.context["page_obj"]], [rejected.pk])
        invalid = self.client.get(reverse("borrowing_requests"), {"status": "OVERDUE"})
        self.assertEqual(len(invalid.context["page_obj"]), 0)
        self.assertTrue(invalid.context["filter_form"].errors)

    def test_get_review_pages_never_change_state_or_reserve(self):
        request = self.submit()
        self.client.force_login(self.admin)
        for name in ["admin_request_detail", "approve_borrowing_request", "reject_borrowing_request", "admin_cancel_borrowing_request"]:
            self.assertEqual(self.client.get(reverse(name, args=[request.pk])).status_code, 200)
        request.refresh_from_db()
        self.assertEqual(request.status, "PENDING")
        self.assertFalse(Allocation.objects.exists())
        self.client.force_login(self.borrower)
        self.assertEqual(self.client.get(reverse("cancel_borrowing_request", args=[request.pk])).status_code, 200)

    def test_admin_approval_allocations_and_loan_management_link(self):
        request = self.submit()
        self.client.force_login(self.admin)
        url = reverse("approve_borrowing_request", args=[request.pk])
        self.assertContains(self.client.post(url, {}), "Confirm this action")
        response = self.client.post(url, {"confirm": "on", "unit_ids": "999999"}, follow=True)
        self.assertContains(response, "approved and equipment reserved")
        self.assertContains(response, "EQ-0-0")
        self.assertContains(response, "Review equipment release")
        self.assertEqual(Allocation.objects.count(), 2)
        self.assertEqual(self.client.post(url, {"confirm": "on"}).status_code, 409)
        self.assertContains(self.client.get(reverse("loan_management")), "Equipment 0")

    def test_admin_approval_insufficient_units_reports_error_without_partial_changes(self):
        request = self.submit()
        EquipmentUnit.objects.filter(equipment=self.equipment[0]).update(status="MAINTENANCE")
        self.client.force_login(self.admin)
        response = self.client.post(reverse("approve_borrowing_request", args=[request.pk]), {"confirm": "on"})
        self.assertContains(response, "Nothing was reserved", status_code=409)
        request.refresh_from_db()
        self.assertEqual(request.status, "PENDING")

    def test_reject_requires_reason_and_displays_escaped_reason_to_borrower(self):
        request = self.submit()
        self.client.force_login(self.admin)
        url = reverse("reject_borrowing_request", args=[request.pk])
        self.assertEqual(self.client.post(url, {"confirm": "on"}).status_code, 200)
        self.assertEqual(self.client.post(url, {"confirm": "on", "rejection_reason": "<script>alert(1)</script>"}).status_code, 302)
        self.client.force_login(self.borrower)
        detail = self.client.get(reverse("request_detail", args=[request.pk]))
        self.assertContains(detail, "Rejection reason")
        self.assertNotContains(detail, "<script>alert(1)</script>")
        self.assertContains(detail, "&lt;script&gt;")

    def test_user_cancels_pending_and_approved_and_admin_cancels_approved(self):
        for actor, approved in [(self.borrower, False), (self.borrower, True), (self.admin, True)]:
            request = self.submit()
            if approved:
                approve_request(request.pk, actor=self.admin)
            self.client.force_login(actor)
            name = "admin_cancel_borrowing_request" if actor.role == "ADMIN" else "cancel_borrowing_request"
            response = self.client.post(reverse(name, args=[request.pk]), {"confirm": "on"}, follow=True)
            self.assertContains(response, "cancelled and any reservations released")
            request.refresh_from_db()
            self.assertEqual(request.status, "CANCELLED")
        self.assertFalse(Allocation.objects.filter(active=True).exists())

    def test_issued_request_cannot_be_cancelled_through_any_route(self):
        request = self.submit()
        approve_request(request.pk, actor=self.admin)
        release_request(request.pk, actor=self.admin)
        for actor, name in [(self.admin, "admin_cancel_borrowing_request"), (self.borrower, "cancel_borrowing_request")]:
            self.client.force_login(actor)
            self.assertEqual(self.client.post(reverse(name, args=[request.pk]), {"confirm": "on"}).status_code, 409)
        request.refresh_from_db()
        self.assertEqual(request.status, "ISSUED")
        self.assertEqual(EquipmentUnit.objects.filter(status="ON_LOAN").count(), 2)

    def test_partial_and_returned_filters_use_loans_records(self):
        request = self.submit()
        approve_request(request.pk, actor=self.admin)
        loan = release_request(request.pk, actor=self.admin)
        items = list(loan.units.all())
        process_returns(loan.pk, actor=self.admin, returns=[(items[0].pk, "GOOD", "")])
        self.client.force_login(self.borrower)
        self.assertContains(self.client.get(reverse("my_requests"), {"status": "partial"}), "Partially Returned")
        process_returns(loan.pk, actor=self.admin, returns=[(items[1].pk, "GOOD", "")])
        self.assertContains(self.client.get(reverse("my_requests"), {"status": "COMPLETED"}), "Returned")
        self.assertEqual(len(self.client.get(reverse("my_requests"), {"status": "partial"}).context["page_obj"]), 0)

    def test_csrf_required_on_submission_and_all_actions(self):
        request = self.submit()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.borrower)
        self.assertEqual(client.post(reverse("new_borrowing_request"), self.post_data()).status_code, 403)
        self.assertEqual(client.post(reverse("cancel_borrowing_request", args=[request.pk]), {"confirm": "on"}).status_code, 403)
        client.force_login(self.admin)
        for name in ["approve_borrowing_request", "reject_borrowing_request", "admin_cancel_borrowing_request"]:
            self.assertEqual(client.post(reverse(name, args=[request.pk]), {"confirm": "on", "rejection_reason": "No"}).status_code, 403)

    def test_empty_states_and_navigation(self):
        self.client.force_login(self.borrower)
        response = self.client.get(reverse("my_requests"))
        self.assertContains(response, "No requests in this view")
        self.assertContains(response, 'href="/portal/requests/"')
        self.client.force_login(self.admin)
        response = self.client.get(reverse("borrowing_requests"))
        self.assertContains(response, "No requests in this view")
        self.assertContains(response, 'href="/manage/requests/"')

    def test_request_pagination_keeps_filters_and_handles_invalid_pages(self):
        for _ in range(21):
            self.submit()
        self.client.force_login(self.borrower)
        first = self.client.get(reverse("my_requests"), {"status": "PENDING", "q": "Equipment 0"})
        self.assertEqual(len(first.context["page_obj"]), 10)
        self.assertContains(first, "status=PENDING&amp;q=Equipment+0&amp;page=2")
        second = self.client.get(reverse("my_requests"), {"status": "PENDING", "page": "2"})
        self.assertEqual(len(second.context["page_obj"]), 10)
        third = self.client.get(second.wsgi_request.path, {**second.wsgi_request.GET.dict(), "page": "3"})
        self.assertEqual(len(third.context["page_obj"]), 1)
        self.assertContains(third, "Showing 21–21 of 21 records.")
        self.assertEqual(self.client.get(reverse("my_requests"), {"page": "invalid"}).status_code, 200)


class DemoBorrowingTests(BorrowingFixtures, TestCase):
    def setUp(self):
        self.make_records()

    @override_settings(DEBUG=True)
    def test_demo_creates_available_inventory_and_pending_request_without_changing_users(self):
        original_users = list(get_user_model().objects.values_list("pk", "role", "password"))
        output = StringIO()
        call_command("seed_borrowing_demo", borrower=self.borrower.username, stdout=output)
        self.assertEqual(EquipmentUnit.objects.filter(asset_tag__startswith="BORROW-DEMO-", status="AVAILABLE").count(), 6)
        request = BorrowingRequest.objects.get()
        self.assertEqual(request.status, "PENDING")
        self.assertEqual(request.quantity, 3)
        self.assertFalse(Allocation.objects.exists())
        self.assertEqual(list(get_user_model().objects.values_list("pk", "role", "password")), original_users)
        self.assertIn("Pending request", output.getvalue())
        with self.assertRaises(CommandError):
            call_command("seed_borrowing_demo", borrower=self.borrower.username, stdout=output)
        self.assertEqual(BorrowingRequest.objects.count(), 1)

    @override_settings(DEBUG=False)
    def test_demo_disabled_outside_debug(self):
        with self.assertRaises(CommandError):
            call_command("seed_borrowing_demo", borrower=self.borrower.username)
        self.assertFalse(EquipmentUnit.objects.filter(asset_tag__startswith="BORROW-DEMO-").exists())

    @override_settings(DEBUG=True)
    def test_demo_requires_active_basic_user(self):
        with self.assertRaises(CommandError):
            call_command("seed_borrowing_demo", borrower=self.admin.username)
        self.assertFalse(BorrowingRequest.objects.exists())


class ConcurrentBorrowingTests(BorrowingFixtures, TransactionTestCase):
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

    def test_competing_requests_cannot_reserve_the_same_units(self):
        first = self.submit()
        second = self.submit()
        self.race([lambda: approve_request(first.pk, actor=self.admin), lambda: approve_request(second.pk, actor=self.admin)])
        self.assertEqual(BorrowingRequest.objects.filter(status="APPROVED").count(), 1)
        self.assertEqual(BorrowingRequest.objects.filter(status="PENDING").count(), 1)
        self.assertEqual(Allocation.objects.filter(active=True).count(), 2)
        self.assertEqual(len(set(Allocation.objects.values_list("unit_id", flat=True))), 2)

    def test_same_request_cannot_be_approved_twice(self):
        request = self.submit()
        self.race([lambda: approve_request(request.pk, actor=self.admin)] * 2)
        self.assertEqual(Allocation.objects.count(), 2)

    def test_cancellation_and_issuance_cannot_partially_release_the_same_reservation(self):
        request = self.submit()
        approve_request(request.pk, actor=self.admin)
        self.race([lambda: cancel_request(request.pk, actor=self.borrower), lambda: release_request(request.pk, actor=self.admin)])
        request.refresh_from_db()
        self.assertIn(request.status, ["CANCELLED", "ISSUED"])
        if request.status == "CANCELLED":
            self.assertFalse(Loan.objects.exists())
            self.assertFalse(Allocation.objects.filter(active=True).exists())
            self.assertEqual(EquipmentUnit.objects.filter(status="RESERVED").count(), 0)
            self.assertEqual(EquipmentUnit.objects.filter(status="ON_LOAN").count(), 0)
        else:
            self.assertEqual(Loan.objects.count(), 1)
            self.assertEqual(Allocation.objects.filter(active=True).count(), 2)
            self.assertEqual(EquipmentUnit.objects.filter(status="ON_LOAN").count(), 2)


class DynamicEquipmentFormTests(BorrowingFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.client.force_login(self.borrower)
        self.url = reverse("new_borrowing_request")

    def row_data(self, count):
        data = self.post_data([(item.pk, index + 1) for index, item in enumerate(self.equipment[:count])])
        data["items-TOTAL_FORMS"] = str(count)
        return data

    def test_initial_and_prefilled_form_show_one_row_with_three_item_capacity(self):
        for params in ({}, {"equipment": self.equipment[0].pk}):
            response = self.client.get(self.url, params)
            formset = response.context["formset"]
            self.assertEqual(formset.total_form_count(), 1)
            self.assertEqual(formset.max_num, 3)
            self.assertContains(response, "+ Add equipment")
            self.assertNotContains(response, "Leave unused equipment slots blank")
            if params:
                self.assertEqual(formset.forms[0]["equipment"].value(), self.equipment[0].pk)

    def test_no_javascript_add_preserves_values_and_does_not_submit(self):
        for count in (1, 2):
            data = self.row_data(count)
            data.update(row_action="add", purpose="")
            response = self.client.post(self.url, data)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.context["form"].is_bound)
            self.assertEqual(response.context["form"]["purpose"].value(), "")
            self.assertEqual(response.context["form"]["due_date"].value(), data["due_date"])
            formset = response.context["formset"]
            self.assertEqual(formset.total_form_count(), count + 1)
            for index in range(count):
                self.assertEqual(formset.forms[index]["equipment"].value(), data[f"items-{index}-equipment"])
                self.assertEqual(formset.forms[index]["quantity"].value(), data[f"items-{index}-quantity"])
            self.assertFalse(BorrowingRequest.objects.exists())
            self.assertFalse(Allocation.objects.exists())

    def test_no_javascript_remove_middle_row_preserves_remaining_values(self):
        data = self.row_data(3)
        data["row_action"] = "remove:items-1"
        response = self.client.post(self.url, data)
        formset = response.context["formset"]
        self.assertEqual(formset.total_form_count(), 2)
        self.assertEqual(formset.forms[1]["equipment"].value(), str(self.equipment[2].pk))
        self.assertEqual(formset.forms[1]["quantity"].value(), "3")
        self.assertEqual(response.context["form"]["purpose"].value(), data["purpose"])
        self.assertEqual(response.context["form"]["due_date"].value(), data["due_date"])
        self.assertFalse(BorrowingRequest.objects.exists())

    def test_invalid_row_actions_or_management_data_never_submit(self):
        for action, count in (("add", 3), ("remove:items-0", 1), ("remove:items-9", 2), ("remove:items-²", 2), ("invalid", 1), ("add", 4), ("add", "invalid")):
            data = self.row_data(3)
            data.update(row_action=action, **{"items-TOTAL_FORMS": str(count)})
            with self.subTest(action=action, count=count):
                response = self.client.post(self.url, data)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Unable to change equipment rows")
                self.assertFalse(BorrowingRequest.objects.exists())
                self.assertFalse(Allocation.objects.exists())

    def test_validation_errors_keep_dynamic_rows_and_all_entered_values(self):
        data = self.row_data(2)
        data.update(due_date="invalid-date", **{"items-1-equipment": str(self.equipment[0].pk), "items-1-quantity": "4"})
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["due_date"])
        formset = response.context["formset"]
        self.assertEqual(formset.total_form_count(), 2)
        self.assertTrue(formset.forms[1].errors["quantity"])
        self.assertEqual(formset.forms[1]["equipment"].value(), data["items-1-equipment"])
        self.assertEqual(formset.forms[1]["quantity"].value(), "4")
        self.assertEqual(response.context["form"]["purpose"].value(), data["purpose"])
        self.assertEqual(response.context["form"]["due_date"].value(), "invalid-date")
        self.assertFalse(BorrowingRequest.objects.exists())

    def test_duplicate_rows_remain_visible_with_validation_error(self):
        data = self.row_data(2)
        data["items-1-equipment"] = data["items-0-equipment"]
        response = self.client.post(self.url, data)
        self.assertContains(response, "Each equipment item can be selected only once.")
        self.assertEqual(response.context["formset"].total_form_count(), 2)
        self.assertEqual(response.context["formset"].forms[1]["equipment"].value(), data["items-0-equipment"])
        self.assertFalse(BorrowingRequest.objects.exists())

    def test_dynamic_one_two_three_row_submissions_stay_pending_without_reservations(self):
        for count in (1, 2, 3):
            response = self.client.post(self.url, self.row_data(count))
            self.assertEqual(response.status_code, 302)
            borrowing = BorrowingRequest.objects.latest("pk")
            self.assertEqual(borrowing.items.count(), count)
            self.assertEqual(borrowing.status, "PENDING")
        self.assertFalse(Allocation.objects.exists())
        self.assertEqual(EquipmentUnit.objects.filter(status="AVAILABLE").count(), 12)

    def test_forged_management_max_does_not_change_rendered_client_limit(self):
        data = self.post_data([(item.pk, 1) for item in self.equipment])
        data["items-MAX_NUM_FORMS"] = "1000"
        response = self.client.post(self.url, data)
        self.assertContains(response, 'data-max-equipment="3"')
        self.assertContains(response, "Select no more than 3 distinct equipment items.")
        self.assertFalse(BorrowingRequest.objects.exists())

    @override_settings(BORROWING_MAX_ITEMS=1)
    def test_smaller_configured_limit_disables_add_and_rejects_extra_rows(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'aria-describedby="equipment-help" disabled')
        self.assertEqual(response.context["formset"].max_num, 1)
        response = self.client.post(self.url, self.row_data(2))
        self.assertContains(response, "Select no more than 1 distinct equipment items.")
        self.assertFalse(BorrowingRequest.objects.exists())
