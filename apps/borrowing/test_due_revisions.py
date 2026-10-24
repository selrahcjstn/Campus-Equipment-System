from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError, connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.dashboard.models import AuditLog, SystemSetting
from apps.inventory.models import EquipmentUnit
from apps.loans.models import Loan
from apps.loans.services import process_returns, release_request
from .forms import DueDateRevisionForm
from .models import Allocation, BorrowingRequest
from .services import approve_request, cancel_request, revise_due_date
from .tests import BorrowingFixtures


class DueDateRevisionTests(BorrowingFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.request = self.submit(items=[(self.equipment[0].pk, 1)])
        approve_request(self.request.pk, actor=self.admin)
        self.request.refresh_from_db()
        self.previous = self.request.due_at
        self.url = reverse("revise_request_due_date", args=[self.request.pk])

    def revised_date(self, days=4):
        return timezone.make_aware(datetime.combine(timezone.localdate() + timedelta(days=days), time(23, 59, 59)))

    def revise(self, **kwargs):
        values = {"actor": self.admin, "due_at": self.revised_date(), "reason": "Room schedule changed",
                  "expected_due_at": self.previous, **kwargs}
        return revise_due_date(self.request.pk, **values)

    def post_data(self, **kwargs):
        return {"due_date": timezone.localdate(self.revised_date()).isoformat(), "reason": "Room schedule changed",
                "expected_due_at": self.previous.isoformat(), **kwargs}

    def test_revision_records_complete_audit_and_issue_copies_final_date(self):
        submitted, approved = self.request.requested_at, self.request.approved_at
        before = timezone.now()
        revised = self.revise(reason="  Room schedule changed  ")
        entry = AuditLog.objects.get(action="REQUEST_DUE_DATE_REVISED")
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.actor_username, self.admin.username)
        self.assertGreaterEqual(entry.occurred_at, before)
        self.assertEqual((entry.entity_type, entry.entity_id), ("borrowing_request", self.request.pk))
        self.assertEqual(entry.description, f"Due date: {self.previous.isoformat()} → {revised.due_at.isoformat()}. Reason: Room schedule changed")
        self.assertEqual((revised.requested_at, revised.approved_at), (submitted, approved))
        self.assertEqual(revised.status, "APPROVED")
        self.assertEqual(Allocation.objects.filter(active=True).count(), 1)
        self.assertEqual(EquipmentUnit.objects.filter(status="RESERVED").count(), 1)
        loan = release_request(self.request.pk, actor=self.admin)
        self.assertEqual(loan.due_at, revised.due_at)

    def test_expired_approval_can_be_revised_then_issued(self):
        now = timezone.now()
        expired = now - timedelta(hours=1)
        BorrowingRequest.objects.filter(pk=self.request.pk).update(
            requested_at=now-timedelta(days=2), approved_at=now-timedelta(days=1), due_at=expired)
        with self.assertRaises(ValidationError):
            release_request(self.request.pk, actor=self.admin)
        self.revise(due_at=self.revised_date(1), expected_due_at=expired)
        self.assertEqual(release_request(self.request.pk, actor=self.admin).due_at, self.revised_date(1))

    def test_service_requires_active_admin(self):
        for actor in [AnonymousUser(), self.borrower, self.other]:
            with self.subTest(actor=actor), self.assertRaises(PermissionDenied):
                self.revise(actor=actor)
        self.admin.is_active = False
        with self.assertRaises(PermissionDenied):
            self.revise()
        self.assertFalse(AuditLog.objects.filter(action="REQUEST_DUE_DATE_REVISED").exists())

    def test_reason_and_due_date_validation_leave_agreement_unchanged(self):
        for reason in ["", "  ", "x"*301, None]:
            with self.subTest(reason=reason), self.assertRaises(ValidationError):
                self.revise(reason=reason)
        for due in [timezone.now(), timezone.now()-timedelta(seconds=1), self.revised_date(8), datetime(2030, 1, 1), self.previous]:
            with self.subTest(due=due), self.assertRaises(ValidationError):
                self.revise(due_at=due)
        self.request.refresh_from_db()
        self.assertEqual(self.request.due_at, self.previous)
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_revision_uses_current_policy_and_original_submission_calendar(self):
        SystemSetting.objects.create(max_days=2)
        with self.assertRaises(ValidationError):
            self.revise(due_at=self.revised_date(3))
        self.revise(due_at=self.revised_date(2))
        old_submission = timezone.now()-timedelta(days=8)
        BorrowingRequest.objects.filter(pk=self.request.pk).update(requested_at=old_submission)
        with self.assertRaises(ValidationError):
            self.revise(due_at=self.revised_date(1), expected_due_at=self.revised_date(2))
        # Original submission is retained: revision does not silently restart the duration.
        self.assertEqual(BorrowingRequest.objects.get(pk=self.request.pk).requested_at, old_submission)

    def test_stale_revision_and_duplicate_post_cannot_overwrite_or_duplicate_audit(self):
        self.revise()
        for due in [self.revised_date(), self.revised_date(5)]:
            with self.assertRaises(ValidationError):
                self.revise(due_at=due)
        self.assertEqual(AuditLog.objects.filter(action="REQUEST_DUE_DATE_REVISED").count(), 1)
        self.assertEqual(BorrowingRequest.objects.get(pk=self.request.pk).due_at, self.revised_date())

    def test_audit_failure_rolls_back_date_and_keeps_reservations(self):
        with patch("apps.borrowing.services.record_event", side_effect=IntegrityError("Audit unavailable")):
            with self.assertRaises(IntegrityError):
                self.revise()
        self.request.refresh_from_db()
        self.assertEqual((self.request.due_at, self.request.status), (self.previous, "APPROVED"))
        self.assertEqual(Allocation.objects.filter(active=True).count(), 1)
        self.assertEqual(EquipmentUnit.objects.filter(status="RESERVED").count(), 1)
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_only_approved_unissued_requests_with_recorded_approval_are_revisable(self):
        for status in ["PENDING", "REJECTED", "CANCELLED", "ISSUED", "COMPLETED"]:
            BorrowingRequest.objects.filter(pk=self.request.pk).update(status=status)
            with self.subTest(status=status), self.assertRaises(ValidationError):
                self.revise()
        BorrowingRequest.objects.filter(pk=self.request.pk).update(status="APPROVED", approved_at=None)
        with self.assertRaises(ValidationError):
            self.revise()

    def test_issued_and_completed_loans_cannot_be_revised_even_with_forged_status(self):
        loan = release_request(self.request.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            self.revise()
        BorrowingRequest.objects.filter(pk=self.request.pk).update(status="APPROVED")
        with self.assertRaises(ValidationError):
            self.revise()
        BorrowingRequest.objects.filter(pk=self.request.pk).update(status="ISSUED")
        process_returns(loan.pk, actor=self.admin, returns=[(loan.units.get().pk, "GOOD", "")])
        with self.assertRaises(ValidationError):
            self.revise()
        loan.refresh_from_db()
        self.assertEqual(loan.due_at, self.previous)

    def test_modal_and_fallback_preserve_values_display_errors_and_succeed(self):
        self.client.force_login(self.admin)
        page = self.client.get(self.url)
        self.assertContains(page, "Reason for revision")
        response = self.client.get(self.url, HTTP_X_ADMIN_MODAL="1")
        self.assertContains(response, "data-admin-modal-form")
        self.assertIn("X-Admin-Modal", response["Vary"])
        response = self.client.post(self.url, self.post_data(reason=""), HTTP_X_ADMIN_MODAL="1")
        self.assertEqual(response.status_code, 422)
        self.assertIn("reason", response.context["form"].errors)
        response = self.client.post(self.url, self.post_data(due_date=(timezone.localdate()+timedelta(days=8)).isoformat(),
                                                          reason="Keep this explanation"), HTTP_X_ADMIN_MODAL="1")
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Keep this explanation", status_code=422)
        self.assertEqual(response.context["form"]["expected_due_at"].value(), self.previous.isoformat())
        response = self.client.post(self.url, self.post_data(), HTTP_X_ADMIN_MODAL="1")
        self.assertJSONEqual(response.content, {"saved": True})
        response = self.client.post(self.url, self.post_data(), HTTP_X_ADMIN_MODAL="1")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(AuditLog.objects.filter(action="REQUEST_DUE_DATE_REVISED").count(), 1)
        self.assertContains(self.client.get(reverse("admin_request_detail", args=[self.request.pk])), "Approved due date revised")
        self.assertContains(self.client.get(reverse("audit_logs"), {"action": "REQUEST_DUE_DATE_REVISED"}), "Room schedule changed")

    def test_full_page_post_redirects_and_revision_links_only_show_before_issue(self):
        self.client.force_login(self.admin)
        for name in ["admin_request_detail", "release_equipment"]:
            self.assertContains(self.client.get(reverse(name, args=[self.request.pk])), 'data-admin-form="Revise due date"')
        response = self.client.post(self.url, self.post_data())
        self.assertRedirects(response, reverse("admin_request_detail", args=[self.request.pk]))
        release_request(self.request.pk, actor=self.admin)
        self.assertNotContains(self.client.get(reverse("admin_request_detail", args=[self.request.pk])), 'data-admin-form="Revise due date"')
        response = self.client.post(self.url, self.post_data(), HTTP_X_ADMIN_MODAL="1")
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "data-admin-modal-unavailable", status_code=409)

    def test_http_authorization_csrf_and_forged_actor(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.borrower)
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(self.url).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.put(self.url).status_code, 405)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(self.url, self.post_data(), HTTP_X_ADMIN_MODAL="1").status_code, 403)
        self.client.post(self.url, self.post_data(actor=self.other.pk, approved_by=self.other.pk))
        self.assertEqual(AuditLog.objects.get(action="REQUEST_DUE_DATE_REVISED").actor, self.admin)

    def test_form_current_policy_date_bounds_and_nonexistent_request(self):
        form = DueDateRevisionForm(borrowing=self.request)
        self.assertEqual(form.fields["due_date"].widget.attrs["max"],
                         (timezone.localdate(self.request.requested_at)+timedelta(days=7)).isoformat())
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("revise_request_due_date", args=[999999])).status_code, 404)


class DueDateRevisionConcurrencyTests(BorrowingFixtures, TransactionTestCase):
    def setUp(self):
        self.make_records()
        self.request = self.submit(items=[(self.equipment[0].pk, 1)])
        approve_request(self.request.pk, actor=self.admin)
        self.request.refresh_from_db()
        self.previous = self.request.due_at
        self.revised = timezone.now()+timedelta(days=4)

    def revise(self, due_at=None):
        return revise_due_date(self.request.pk, actor=self.admin, due_at=due_at or self.revised,
                               reason="Concurrent schedule change", expected_due_at=self.previous)

    def race(self, operations):
        barrier = Barrier(2)

        def worker(operation):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                operation()
                return "saved"
            except (ValidationError, IntegrityError, OperationalError):
                return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, operations))

    def test_two_revisions_from_same_original_date_have_exactly_one_winner(self):
        results = self.race([self.revise, lambda: self.revise(self.revised+timedelta(days=1))])
        self.assertEqual(sorted(results), ["rejected", "saved"])
        self.assertEqual(AuditLog.objects.filter(action="REQUEST_DUE_DATE_REVISED").count(), 1)
        self.assertEqual(Allocation.objects.filter(active=True).count(), 1)

    def test_revision_racing_issue_never_changes_date_after_issuance(self):
        results = self.race([self.revise, lambda: release_request(self.request.pk, actor=self.admin)])
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, "ISSUED")
        loan = Loan.objects.get(request=self.request)
        self.assertEqual(loan.due_at, self.request.due_at)
        self.assertEqual(EquipmentUnit.objects.filter(status="ON_LOAN").count(), 1)
        revised = AuditLog.objects.filter(action="REQUEST_DUE_DATE_REVISED").first()
        if revised:
            self.assertEqual(results, ["saved", "saved"])
            self.assertEqual(loan.due_at, self.revised)
            self.assertLessEqual(revised.occurred_at, loan.issued_at)
        else:
            self.assertEqual(results, ["rejected", "saved"])
            self.assertEqual(loan.due_at, self.previous)

    def test_revision_racing_cancellation_never_changes_cancelled_agreement(self):
        results = self.race([self.revise, lambda: cancel_request(self.request.pk, actor=self.admin)])
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, "CANCELLED")
        self.assertFalse(Loan.objects.exists())
        self.assertFalse(Allocation.objects.filter(active=True).exists())
        self.assertEqual(EquipmentUnit.objects.filter(status="RESERVED").count(), 0)
        revised = AuditLog.objects.filter(action="REQUEST_DUE_DATE_REVISED").first()
        if revised:
            self.assertEqual(results, ["saved", "saved"])
            self.assertLessEqual(revised.occurred_at, self.request.cancelled_at)
        else:
            self.assertEqual(results, ["rejected", "saved"])
            self.assertEqual(self.request.due_at, self.previous)
