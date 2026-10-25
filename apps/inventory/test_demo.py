import os
import secrets
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.db import IntegrityError, connection
from django.db.models import Count, Sum
from django.test import TestCase, override_settings

from apps.borrowing.models import Allocation, BorrowingRequest
from apps.dashboard.services import category_usage, monthly_issued_loans
from apps.loans.models import Loan, LoanUnit
from apps.maintenance.models import MaintenanceRecord
from .models import Category, Equipment, EquipmentUnit


@override_settings(DEBUG=True)
class ProjectDemoTests(TestCase):
    def seed(self):
        output = StringIO()
        call_command("seed_project_demo", confirm_isolated=True, stdout=output)
        return output.getvalue()

    def setUp(self):
        self.password = secrets.token_urlsafe(24)
        patcher = patch.dict(os.environ, {"CAMPUS_DEMO_PASSWORD": self.password})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_complete_dataset_reconciles_and_is_repeatable(self):
        output = self.seed()
        User = get_user_model()
        models = [Category, Equipment, EquipmentUnit, User, BorrowingRequest, Loan, MaintenanceRecord]
        counts = [model.objects.count() for model in models]
        self.assertEqual(counts, [3, 6, 18, 9, 20, 8, 5])
        self.assertNotIn(self.password, output)
        self.assertTrue(User.objects.get(username="demo_admin").check_password(self.password))
        self.assertEqual(User.objects.filter(role="BASIC_USER").count(), 8)
        self.assertEqual(set(EquipmentUnit.objects.values_list("status", flat=True)), set(EquipmentUnit.Status.values))
        self.assertFalse(Equipment.objects.filter(category=None).exists())
        self.assertFalse(EquipmentUnit.objects.filter(condition=None).exists())
        self.assertFalse(EquipmentUnit.objects.filter(acquisition_date=None).exists())
        for status in ["PENDING", "APPROVED", "REJECTED", "CANCELLED", "ISSUED", "COMPLETED"]:
            self.assertTrue(BorrowingRequest.objects.filter(status=status).exists())
        self.assertTrue(Loan.objects.overdue().exists())
        self.assertTrue(any(loan.outstanding_count and loan.outstanding_count < loan.quantity for loan in Loan.objects.all()))
        self.assertTrue(LoanUnit.objects.filter(return_condition="DAMAGED", returned_at__isnull=False).exists())
        self.assertFalse(Allocation.objects.filter(active=True).values("unit_id").annotate(n=Count("pk")).filter(n__gt=1).exists())
        for allocation in Allocation.objects.filter(active=True).select_related("unit", "request_item__request"):
            expected = "RESERVED" if allocation.request_item.request.status == "APPROVED" else "ON_LOAN"
            self.assertEqual(allocation.unit.status, expected)
        with connection.cursor() as cursor:
            self.assertEqual(cursor.execute("PRAGMA foreign_key_check").fetchall(), [])
        passwords = list(User.objects.order_by("pk").values_list("password", flat=True))
        self.assertIn("already exists", self.seed())
        self.assertEqual([model.objects.count() for model in models], counts)
        self.assertEqual(list(User.objects.order_by("pk").values_list("password", flat=True)), passwords)

    def test_refuses_nonempty_or_working_database_and_missing_confirmation(self):
        with self.assertRaises(CommandError):
            call_command("seed_project_demo", stdout=StringIO())
        from django.conf import settings
        with patch.dict(connection.settings_dict, {"NAME": str(settings.BASE_DIR/"db.sqlite3")}):
            with self.assertRaisesRegex(CommandError, "working"):
                self.seed()
        Category.objects.create(name="Existing category")
        with self.assertRaisesRegex(CommandError, "not empty"):
            self.seed()
        self.assertEqual(Category.objects.count(), 1)
        self.assertFalse(get_user_model().objects.exists())

    def test_failure_rolls_back_entire_seed(self):
        with patch("apps.inventory.management.commands.seed_project_demo.release_request", side_effect=IntegrityError("Test failure")):
            with self.assertRaises(IntegrityError):
                self.seed()
        for model in [get_user_model(), Category, Equipment, EquipmentUnit, BorrowingRequest, Loan, MaintenanceRecord]:
            self.assertFalse(model.objects.exists())

    def test_missing_private_password_creates_nothing(self):
        with patch.dict(os.environ, {"CAMPUS_DEMO_PASSWORD": ""}):
            with self.assertRaises(CommandError):
                self.seed()
        self.assertFalse(get_user_model().objects.exists())
