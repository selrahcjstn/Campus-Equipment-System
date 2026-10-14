"""Optional local test inventory and a Pending request for an existing borrower."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.inventory.models import Equipment, EquipmentUnit
from apps.borrowing.services import submit_request


class Command(BaseCommand):
    help = "Create available demo inventory and a Pending request using an existing Basic User."

    def add_arguments(self, parser):
        parser.add_argument("--borrower", required=True, help="Existing active BASIC_USER username")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo fixtures require DEBUG=True.")
        User = get_user_model()
        try:
            borrower = User.objects.get(username=options["borrower"], role="BASIC_USER", is_active=True)
        except User.DoesNotExist as error:
            raise CommandError("Provide an existing active Basic User account.") from error
        if EquipmentUnit.objects.filter(asset_tag__startswith="BORROW-DEMO-").exists():
            raise CommandError("Borrowing demo records already exist; existing records were left untouched.")
        equipment = []
        for kind in ["Projector", "Speaker"]:
            item = Equipment.objects.create(name=f"Borrowing demo {kind.lower()}", description="Local test equipment for borrowing and approval")
            equipment.append(item)
            for number in range(1, 4):
                EquipmentUnit.objects.create(equipment=item, asset_tag=f"BORROW-DEMO-{kind.upper()}-{number}")
        request = submit_request(borrower=borrower, purpose="Borrowing demo: class presentation", due_at=timezone.now() + timedelta(days=3), items=[(equipment[0].pk, 2), (equipment[1].pk, 1)])
        self.stdout.write(self.style.SUCCESS(f"Created six available demo units and Pending request #{request.pk}. Review it in the Admin Borrowing Requests queue."))
