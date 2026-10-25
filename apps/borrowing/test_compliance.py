from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.dashboard.models import AuditLog
from apps.inventory.models import EquipmentUnit
from .models import Allocation, BorrowingRequest
from .services import approve_request, cancel_request
from .tests import BorrowingFixtures


class RequestComplianceTests(BorrowingFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.client.force_login(self.admin)

    def test_date_boundaries_combined_filters_and_pagination_use_manila(self):
        start = datetime(2026, 10, 20, tzinfo=ZoneInfo("Asia/Manila"))
        inside = []
        for index in range(13):
            record = self.submit(purpose="Filter target")
            at = start-timedelta(microseconds=1) if index == 0 else start+timedelta(days=1) if index == 12 else start+timedelta(minutes=index)
            BorrowingRequest.objects.filter(pk=record.pk).update(requested_at=at, due_at=at+timedelta(days=2))
            if 0 < index < 12:
                inside.append(record.pk)
        excluded = self.submit(purpose="Another purpose")
        BorrowingRequest.objects.filter(pk=excluded.pk).update(requested_at=start, due_at=start+timedelta(days=2))
        data = {"q": "Filter target", "status": "PENDING", "start_date": "2026-10-20", "end_date": "2026-10-20"}
        with timezone.override("UTC"):
            response = self.client.get(reverse("borrowing_requests"), data)
            self.assertEqual(response.context["page_obj"].paginator.count, 11)
            self.assertContains(response, "start_date=2026-10-20")
            second = self.client.get(reverse("borrowing_requests"), {**data, "page": 2})
        found = {r.pk for r in response.context["page_obj"]} | {r.pk for r in second.context["page_obj"]}
        self.assertEqual(found, set(inside))
        cancel_request(inside[0], actor=self.admin)
        self.assertEqual(self.client.get(reverse("borrowing_requests"), data).context["page_obj"].paginator.count, 10)

    def test_invalid_date_or_reversed_range_displays_errors(self):
        self.submit()
        for data in [{"start_date": "wrong"}, {"start_date": "2026-10-22", "end_date": "2026-10-21"}, {"end_date": "9999-01-01"}]:
            response = self.client.get(reverse("borrowing_requests"), data)
            self.assertTrue(response.context["filter_form"].errors)
            self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_review_counts_exclude_each_unavailable_status_and_refresh(self):
        record = self.submit()
        equipment = self.equipment[0]
        unit = equipment.units.first()
        url = reverse("approve_borrowing_request", args=[record.pk])
        for status, expected in [("AVAILABLE", 3), ("RESERVED", 2), ("ON_LOAN", 2), ("MAINTENANCE", 2), ("RETIRED", 2)]:
            EquipmentUnit.objects.filter(pk=unit.pk).update(status=status)
            page = self.client.get(url)
            self.assertContains(page, "Currently available")
            self.assertEqual(page.context["borrowing"].items.all()[0].current_available, expected)
        EquipmentUnit.objects.filter(equipment=equipment).update(status="MAINTENANCE")
        self.assertContains(self.client.get(url), "Insufficient stock")
        response = self.client.post(url, {"confirm": "on", "approval_reason": "Reviewed before stock changed."})
        self.assertEqual(response.status_code, 409)
        record.refresh_from_db()
        self.assertEqual((record.status, record.approval_reason), ("PENDING", ""))
        self.assertFalse(Allocation.objects.exists())

    def test_approval_requires_reason_in_form_and_service(self):
        record = self.submit()
        url = reverse("approve_borrowing_request", args=[record.pk])
        response = self.client.post(url, {"confirm": "on"})
        self.assertIn("approval_reason", response.context["form"].errors)
        for reason in [None, "", "  ", "a" * 301, 123]:
            with self.subTest(reason_type=type(reason).__name__), self.assertRaises(ValidationError):
                approve_request(record.pk, actor=self.admin, reason=reason)
        self.assertFalse(Allocation.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action="REQUEST_APPROVED").exists())
        record.refresh_from_db()
        self.assertEqual(record.status, "PENDING")


    def test_approval_reason_persisted_escaped_and_audited_with_actor_time(self):
        record = self.submit()
        reason = "<script>example</script> " + "x" * 270
        response = self.client.post(reverse("approve_borrowing_request", args=[record.pk]), {"confirm": "on", "approval_reason": reason})
        self.assertEqual(response.status_code, 302)
        record.refresh_from_db()
        self.assertEqual(record.approval_reason, reason)
        event = AuditLog.objects.get(action="REQUEST_APPROVED", entity_id=record.pk)
        self.assertEqual(event.actor, self.admin)
        self.assertIn(reason, event.description)
        self.assertIsNotNone(event.occurred_at)
        page = self.client.get(reverse("admin_request_detail", args=[record.pk]))
        self.assertContains(page, "&lt;script&gt;")
        self.assertNotContains(page, "<script>example</script>")
        with self.assertRaises(ValidationError):
            approve_request(record.pk, actor=self.admin, reason="Overwrite")
        record.refresh_from_db()
        self.assertEqual(record.approval_reason, reason)

    def test_audit_failure_rolls_back_reason_and_reservations(self):
        record = self.submit()
        with patch("apps.borrowing.services.record_event", side_effect=IntegrityError("Unavailable audit")):
            with self.assertRaises(IntegrityError):
                approve_request(record.pk, actor=self.admin, reason="Approved class activity.")
        record.refresh_from_db()
        self.assertEqual((record.status, record.approval_reason, record.approved_at), ("PENDING", "", None))
        self.assertFalse(Allocation.objects.exists())
        self.assertEqual(self.equipment[0].units.filter(status="AVAILABLE").count(), 3)

    def test_basic_user_cannot_post_reason_or_access_admin_filters(self):
        record = self.submit()
        self.client.force_login(self.borrower)
        response = self.client.post(reverse("approve_borrowing_request", args=[record.pk]), {"confirm": "on", "approval_reason": "Forged"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get(reverse("borrowing_requests"), {"start_date": "2026-10-20"}).status_code, 403)
        record.refresh_from_db()
        self.assertEqual(record.status, "PENDING")


class ApprovalMigrationSafetyTests(TransactionTestCase):
    def test_existing_decisions_keep_original_metadata_without_invented_reason(self):
        previous = ("borrowing", "0002_borrowingrequest_cancelled_at_and_more")
        latest = ("borrowing", "0003_borrowingrequest_approval_reason")
        try:
            executor = MigrationExecutor(connection)
            executor.migrate([previous])
            old = executor.loader.project_state([previous]).apps
            User = old.get_model("accounts", "User")
            admin = User.objects.create(username="legacy-approver", role="ADMIN")
            borrower = User.objects.create(username="legacy-borrower", role="BASIC_USER")
            now = timezone.now()
            record = old.get_model("borrowing", "BorrowingRequest").objects.create(
                borrower=borrower, purpose="Historical approval", requested_at=now,
                due_at=now+timedelta(days=3), approved_by=admin, approved_at=now, status="APPROVED",
            )
            MigrationExecutor(connection).migrate([latest])
            current = BorrowingRequest.objects.get(pk=record.pk)
            self.assertEqual((current.approval_reason, current.approved_by_id, current.approved_at, current.status), ("", admin.pk, now, "APPROVED"))
        finally:
            MigrationExecutor(connection).migrate([latest])

