"""Fictional, atomic project fixtures for a separate, empty demonstration DB."""
import os
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from apps.borrowing.models import BorrowingRequest
from apps.borrowing.services import approve_request, cancel_request, reject_request, submit_request
from apps.dashboard.models import AuditLog, SystemSetting
from apps.inventory.models import Category, Equipment, EquipmentUnit
from apps.inventory.services import add_unit, save_category, save_equipment
from apps.loans.models import Loan
from apps.loans.services import process_returns, release_request
from apps.maintenance.models import MaintenanceRecord
from apps.maintenance.services import create_record, resolve_record, start_repair


class Command(BaseCommand):
    help = "Create the complete fictional PDF demonstration in a separate empty database. Never resets data."

    def add_arguments(self, parser):
        parser.add_argument("--confirm-isolated", action="store_true", help="Confirm that this is a disposable demo database.")
        parser.add_argument("--password-env", default="CAMPUS_DEMO_PASSWORD", help="Environment variable containing a private demo password; never pass the password on the command line.")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG or not options["confirm_isolated"]:
            raise CommandError("Use DEBUG=True and --confirm-isolated with a separate demonstration database.")
        if connection.vendor == "sqlite" and Path(str(connection.settings_dict["NAME"])).resolve() == (settings.BASE_DIR / "db.sqlite3").resolve():
            raise CommandError("Refusing to seed the working db.sqlite3. Set DJANGO_DATABASE_PATH to a separate file.")
        User = get_user_model()
        populated = any(model.objects.exists() for model in [User, Category, Equipment, EquipmentUnit, BorrowingRequest, Loan, MaintenanceRecord, AuditLog, SystemSetting])
        if populated:
            # Atomic first creation means the full dataset exists or nothing does.
            # Never overwrite passwords, dates or transactions on a repeat run.
            if (User.objects.filter(username="demo_admin", role="ADMIN").exists()
                    and User.objects.filter(username__startswith="demo_user", role="BASIC_USER").count() >= 8
                    and EquipmentUnit.objects.filter(asset_tag__startswith="PDF-DEMO-").count() >= 18
                    and BorrowingRequest.objects.filter(purpose__startswith="Fictional PDF demo:").count() >= 20
                    and Loan.objects.filter(request__purpose__startswith="Fictional PDF demo:").count() >= 8):
                self.stdout.write("Demo dataset already exists; all records and passwords were left unchanged. Use a new database to refresh historical dates.")
                return
            raise CommandError("Database is not empty or contains an incomplete demo. Use a new database; no existing records were changed.")
        password = os.environ.get(options["password_env"], "")
        if len(password) < 12:
            raise CommandError("Set the named password environment variable privately to at least 12 characters.")
        admin = User(username="demo_admin", first_name="Demo", last_name="Administrator", email="admin@example.invalid", role="ADMIN")
        users = [admin] + [User(username=f"demo_user{i:02}", first_name="Fictional", last_name=f"Borrower {i:02}", email=f"borrower{i:02}@example.invalid", role="BASIC_USER") for i in range(1, 9)]
        for user in users:
            try:
                validate_password(password, user)
                user.set_password(password)
                user.full_clean()
                user.save()
            except ValidationError as error:
                # Validator text can vary; do not echo supplied credentials.
                raise CommandError("Demo credentials or account data failed validation. Choose a stronger private password.") from error

        now = timezone.now()
        today = timezone.localdate(now)
        categories = [save_category(actor=admin, name=name, description="Synthetic classroom demonstration category.") for name in ["Demo audiovisual", "Demo computing", "Demo field equipment"]]
        names = ["Projector", "Speaker", "Laptop", "Tablet", "Camera", "Tripod"]
        equipment = []
        for index, name in enumerate(names):
            item = save_equipment(actor=admin, name=f"Demo {name}", category_id=categories[index // 2].pk, description="Fictional demonstration equipment; no real asset or personal data.")
            equipment.append(item)
            for number in range(1, 4):
                add_unit(item.pk, actor=admin, asset_tag=f"PDF-DEMO-{index+1:02}-{number:02}", condition="GOOD", acquisition_date=today-timedelta(days=365))

        def request(number, item, quantity=1):
            return submit_request(borrower=users[1 + (number-1) % 8], purpose=f"Fictional PDF demo: scenario {number:02}", due_at=now+timedelta(days=5), items=[(item.pk, quantity)])

        def approve(record):
            return approve_request(record.pk, actor=admin, reason="Approved for the fictional classroom demonstration.")

        # Real service transitions create all allocations/returns/audits. Only
        # freshly created fixtures receive historical timestamps afterward.
        for index in range(8):
            record = request(index+1, equipment[index % 6], quantity=2 if index < 6 else 1)
            approve(record)
            loan = release_request(record.pk, actor=admin)
            if index < 5:
                rows = list(loan.units.all())
                process_returns(loan.pk, actor=admin, returns=[(row.pk, "DAMAGED" if index == 4 and offset == 0 else "GOOD", "Synthetic damaged casing for maintenance practice." if index == 4 and offset == 0 else "") for offset, row in enumerate(rows)])
            elif index == 5:
                process_returns(loan.pk, actor=admin, returns=[(loan.units.first().pk, "GOOD", "")])
            if index != 6:
                # Historical demo data is allowed by the PDF. Requested policy
                # duration stays seven calendar days; ordinary services retain
                # their current/future validation. Returns happened today.
                submitted = now - timedelta(days=70 if index < 2 else 40 if index < 4 else 10)
                approved, issued, due = submitted+timedelta(hours=1), submitted+timedelta(hours=2), submitted+timedelta(days=7)
                BorrowingRequest.objects.filter(pk=record.pk).update(requested_at=submitted, approved_at=approved, due_at=due)
                Loan.objects.filter(pk=loan.pk).update(issued_at=issued, due_at=due)
                AuditLog.objects.filter(entity_type="borrowing_request", entity_id=record.pk, action="REQUEST_APPROVED").update(occurred_at=approved)
                AuditLog.objects.filter(entity_type="loan", entity_id=loan.pk, action="LOAN_RELEASED").update(occurred_at=issued)

        approve(request(9, equipment[2]))  # Awaiting release, with reservations.
        for number in [10, 11]:
            reject_request(request(number, equipment[0]).pk, actor=admin, reason="Fictional demonstration: request not needed for the scheduled activity.")
        for number in [12, 13, 14]:
            record = request(number, equipment[0])
            if number != 12:
                approve(record)
            cancel_request(record.pk, actor=admin)
        for number in range(15, 21):
            request(number, equipment[(number-15) % 6])

        # A damaged return already created one Reported record. Add all other
        # supported outcomes using idle units and the existing maintenance rules.
        choices = [(equipment[3], "REPORTED"), (equipment[3], "IN_PROGRESS"), (equipment[2], "REPAIRED"), (equipment[4], "RETIRED")]
        for item, outcome in choices:
            unit = item.units.filter(status="AVAILABLE").first()
            record = create_record(unit.pk, actor=admin, reason="Synthetic demonstration inspection issue.")
            if outcome != "REPORTED":
                start_repair(record.pk, actor=admin)
            if outcome in ["REPAIRED", "RETIRED"]:
                resolve_record(record.pk, actor=admin, outcome=outcome, repair_notes="Synthetic repair assessment completed for the demonstration.")
        self.stdout.write(self.style.SUCCESS("Created fictional demo: 3 categories, 6 items, 18 units, 1 Admin, 8 Basic Users, 20 requests, 8 loans and 5 maintenance records. Accounts: demo_admin and demo_user01–demo_user08. Passwords were not printed."))
