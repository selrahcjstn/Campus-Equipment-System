import csv
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.borrowing.models import BorrowingRequest
from apps.dashboard.services import dashboard_statistics, loan_report, personal_summary, report_row
from .models import Loan
from .services import process_returns
from .tests import LoanFixtures


MANILA = ZoneInfo("Asia/Manila")


class CalendarOverdueTests(LoanFixtures, TestCase):
    def setUp(self):
        self.make_records()
        self.loan = self.issue()

    def test_calendar_boundaries_ignore_elapsed_days_and_viewer_timezone(self):
        cases = [
            ("2026-10-24T12:00:00", "2026-10-24T11:00:00", 0, False),
            ("2026-10-24T12:00:00", "2026-10-24T12:00:00", 0, False),
            ("2026-10-24T12:00:00", "2026-10-24T23:59:59", 0, False),
            ("2026-10-24T23:59:59", "2026-10-25T00:00:00", 1, True),
            ("2026-10-24T12:00:00", "2026-10-25T11:59:59", 1, True),
            ("2026-10-24T12:00:00", "2026-10-26T11:59:59", 2, True),
            ("2026-10-24T12:00:00", "2026-10-25T12:00:00", 1, True),
        ]
        for viewer_zone in ["Asia/Manila", "UTC", "America/New_York"]:
            with timezone.override(viewer_zone):
                for due, at, days, overdue in cases:
                    with self.subTest(zone=viewer_zone, due=due, at=at):
                        self.loan.due_at = datetime.fromisoformat(due).replace(tzinfo=MANILA).astimezone(dt_timezone.utc)
                        at = datetime.fromisoformat(at).replace(tzinfo=MANILA).astimezone(dt_timezone.utc)
                        self.assertEqual(self.loan.overdue_days(at), days)
                        self.assertEqual(self.loan.is_overdue_at(at), overdue)
                        row = report_row(self.loan, at=at)
                        self.assertEqual(row["overdue_days"], days)
                        self.assertEqual(row["overdue_label"], f"{days} calendar day(s) overdue" if overdue else "—")

    def set_midnight_fixture(self):
        due = datetime(2026, 10, 24, 23, 59, 59, tzinfo=MANILA)
        BorrowingRequest.objects.filter(pk=self.request.pk).update(
            requested_at=due-timedelta(days=3), approved_at=due-timedelta(days=2), due_at=due)
        Loan.objects.filter(pk=self.loan.pk).update(issued_at=due-timedelta(days=2), due_at=due)
        self.loan.refresh_from_db()
        return due+timedelta(seconds=1)

    def test_all_surfaces_and_csv_agree_one_second_after_manila_midnight(self):
        at = self.set_midnight_fixture()
        with patch("django.utils.timezone.now", return_value=at):
            self.assertTrue(self.loan.is_overdue)
            self.assertEqual(self.loan.overdue_days(), 1)
            # Exists does not duplicate a loan with two outstanding unit rows.
            self.assertEqual(Loan.objects.overdue().count(), 1)
            self.client.force_login(self.borrower)
            self.assertContains(self.client.get(reverse("my_loans"), {"status": "overdue"}), "1 calendar day(s) overdue")
            dashboard = self.client.get(reverse("user_dashboard"))
            self.assertEqual(dashboard.context["overdue_count"], 1)
            self.assertContains(dashboard, "1 calendar day(s) overdue")
            self.client.force_login(self.admin)
            returns = self.client.get(reverse("returns_overdue"), {"status": "overdue"})
            self.assertEqual(returns.context["overdue_count"], 1)
            self.assertContains(returns, "1 calendar day(s) overdue")
            self.assertEqual(dashboard_statistics(at=at)["overdue_loans"], 1)
            report = self.client.get(reverse("reports"), {"report": "overdue"})
            self.assertEqual(report.context["rows"][0]["overdue_days"], 1)
            self.assertContains(report, "1 calendar day(s) overdue")
            exported = self.client.get(reverse("export_reports"), {"report": "overdue"})
            rows = list(csv.DictReader(StringIO(exported.content.decode("utf-8-sig"))))
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["Overdue days"] for row in rows}, {"1"})
            self.assertEqual({row["Loan status"] for row in rows}, {"Overdue"})

    def test_partial_and_final_returns_update_overdue_classification_and_days(self):
        at = self.set_midnight_fixture()
        with patch("django.utils.timezone.now", return_value=at):
            process_returns(self.loan.pk, actor=self.admin, returns=[(self.loan.units.first().pk, "GOOD", "")])
            self.loan.refresh_from_db()
            self.assertEqual(self.loan.outstanding_count, 1)
            self.assertEqual(self.loan.overdue_days(), 1)
            self.assertEqual(Loan.objects.overdue().count(), 1)
            self.assertEqual(report_row(self.loan, at=at)["overdue_days"], 1)
            self.return_all(self.loan)
            self.loan.refresh_from_db()
            self.assertFalse(self.loan.is_overdue)
            self.assertEqual(self.loan.overdue_days(), 0)
            self.assertEqual(self.loan.status, "Completed")
            self.assertFalse(Loan.objects.overdue().exists())
            self.assertFalse(loan_report({"report": "overdue"}, at=at).exists())

    def test_stale_completion_never_makes_zero_outstanding_loan_overdue_anywhere(self):
        at = self.set_midnight_fixture()
        with patch("django.utils.timezone.now", return_value=at):
            self.return_all(self.loan)
            Loan.objects.filter(pk=self.loan.pk).update(completed_at=None)
            self.loan.refresh_from_db()
            self.assertFalse(self.loan.is_overdue)
            self.assertEqual(self.loan.overdue_days(), 0)
            self.assertEqual(self.loan.status, "Completed")
            self.assertEqual(self.loan.status_variant, "success")
            self.assertFalse(Loan.objects.overdue().exists())
            self.assertEqual(report_row(self.loan, at=at)["status"], "Completed")
            self.assertEqual(personal_summary(self.borrower, at=at)["overdue_count"], 0)
            self.assertEqual(dashboard_statistics(at=at)["overdue_loans"], 0)
            self.client.force_login(self.borrower)
            response = self.client.get(reverse("my_loans"), {"status": "overdue"})
            self.assertEqual(response.context["overdue_count"], 0)
            self.assertEqual(len(response.context["page_obj"]), 0)
            self.client.force_login(self.admin)
            response = self.client.get(reverse("returns_overdue"), {"status": "overdue"})
            self.assertEqual(response.context["overdue_count"], 0)
            self.assertEqual(len(response.context["page_obj"]), 0)
            self.assertFalse(self.client.get(reverse("reports"), {"report": "overdue"}).context["rows"])
            rows = list(csv.DictReader(StringIO(self.client.get(reverse("export_reports"), {"report": "overdue"}).content.decode("utf-8-sig"))))
            self.assertEqual(rows, [])

    def test_loan_with_no_unit_records_is_not_overdue(self):
        at = self.set_midnight_fixture()
        request = BorrowingRequest.objects.create(borrower=self.other, purpose="Incomplete historical record", due_at=at+timedelta(days=1))
        empty = Loan.objects.create(request=request, borrower=self.other, issued_by=self.admin,
                                    issued_at=at-timedelta(days=2), due_at=at-timedelta(days=1))
        with patch("django.utils.timezone.now", return_value=at):
            self.assertFalse(empty.is_overdue)
            self.assertEqual(empty.overdue_days(), 0)
            self.assertFalse(Loan.objects.overdue().filter(pk=empty.pk).exists())
            self.assertEqual(report_row(empty, at=at)["status"], "Needs review")
