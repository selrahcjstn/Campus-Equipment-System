"""Opt-in local fixtures, using existing test accounts and new demo units only."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.borrowing.models import BorrowingRequest, BorrowingRequestItem
from apps.borrowing.services import approve_request
from apps.inventory.models import Category, Equipment, EquipmentUnit
from apps.loans.models import Loan
from apps.loans.services import release_request


class Command(BaseCommand):
    help = "Add a ready request and an overdue loan for local testing; does not create or modify accounts."

    def add_arguments(self, parser):
        parser.add_argument("--admin", required=True, help="Existing active ADMIN username")
        parser.add_argument("--borrower", required=True, help="Existing active BASIC_USER username")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo fixtures are only available with DEBUG=True.")
        User = get_user_model()
        try:
            admin = User.objects.get(username=options["admin"], role="ADMIN", is_active=True)
            borrower = User.objects.get(username=options["borrower"], role="BASIC_USER", is_active=True)
        except User.DoesNotExist as error:
            raise CommandError("Provide existing active accounts with the specified roles.") from error
        if EquipmentUnit.objects.filter(asset_tag__startswith="LOANS-DEMO-").exists():
            raise CommandError("Loans demo records already exist. Existing demo data was left untouched.")

        now = timezone.now()
        category = Category(name="Loans demo equipment", description="Synthetic test inventory")
        category.full_clean()
        category.save()
        equipment = Equipment(name="Loans demo projector", category=category, description="Demo equipment for testing releases and returns")
        equipment.full_clean()
        equipment.save()
        ready = None
        for scenario in ["ready", "overdue"]:
            request = BorrowingRequest.objects.create(borrower=borrower, purpose=f"Loans demo: {scenario}", due_at=now + timedelta(days=7))
            item = BorrowingRequestItem.objects.create(request=request, equipment=equipment, quantity=2)
            units = []
            for index in [1, 2]:
                unit = EquipmentUnit(equipment=equipment, asset_tag=f"LOANS-DEMO-{scenario.upper()}-{index}", condition="GOOD", acquisition_date=timezone.localdate()-timedelta(days=30))
                unit.full_clean()
                unit.save()
                units.append(unit)
            approve_request(request.pk, actor=admin, reason="Approved for the synthetic loan fixture.", allocations={item.pk: [unit.pk for unit in units]})
            if scenario == "ready":
                ready = request
                continue
            loan = release_request(request.pk, actor=admin)
            # Move only this newly-created fixture's dates into the past. The
            # normal application never edits issue/due dates after release.
            BorrowingRequest.objects.filter(pk=request.pk).update(requested_at=now - timedelta(days=4), approved_at=now - timedelta(days=3), due_at=now - timedelta(days=1))
            Loan.objects.filter(pk=loan.pk).update(issued_at=now - timedelta(days=3), due_at=now - timedelta(days=1))
        self.stdout.write(self.style.SUCCESS(f"Ready request #{ready.pk}; overdue demo loan #{loan.pk}. Log in with the existing accounts to test the pages."))
