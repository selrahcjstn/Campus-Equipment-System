"""The minimal approval/allocation foundation consumed by Loans.

The Borrowing module can call approve_request from its own approval UI later.
"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.inventory.models import EquipmentUnit
from .models import Allocation, BorrowingRequest


@transaction.atomic
def approve_request(request_id, *, actor, allocations):
    """Reserve exact quantities: allocations maps request-item IDs to unit IDs."""
    if not actor.is_authenticated or not actor.is_active or actor.role != "ADMIN":
        raise PermissionDenied("Only an active Admin may approve requests.")

    # Claim the transition before reading units. This also acquires SQLite's
    # write lock, where select_for_update alone cannot serialize writers.
    changed = BorrowingRequest.objects.filter(
        pk=request_id, status=BorrowingRequest.Status.PENDING
    ).update(status=BorrowingRequest.Status.APPROVED)
    if changed != 1:
        raise ValidationError("Only pending requests can be approved.")
    request = BorrowingRequest.objects.select_for_update().get(pk=request_id)
    items = list(request.items.select_for_update().order_by("pk"))
    now = timezone.now()
    if request.due_at <= now:
        raise ValidationError("The due date must be in the future.")
    if request.borrower.role != "BASIC_USER" or not request.borrower.is_active:
        raise ValidationError("The borrower must be an active Basic User.")
    if not items or set(allocations) != {item.pk for item in items}:
        raise ValidationError("Allocate every requested equipment item.")
    ids = [unit_id for values in allocations.values() for unit_id in values]
    if len(ids) != len(set(ids)):
        raise ValidationError("Each physical unit can be allocated only once.")
    units = {
        unit.pk: unit for unit in EquipmentUnit.objects.select_for_update()
        .filter(pk__in=ids).order_by("pk")
    }
    if len(units) != len(ids):
        raise ValidationError("One or more equipment units do not exist.")
    for item in items:
        if len(allocations[item.pk]) != item.quantity:
            raise ValidationError("Allocated quantities must match the requested quantities.")
        for unit_id in sorted(allocations[item.pk]):
            unit = units[unit_id]
            if unit.equipment_id != item.equipment_id:
                raise ValidationError("An allocated unit does not match the requested equipment.")
            if Allocation.objects.filter(unit=unit, active=True).exists():
                raise ValidationError("An equipment unit already has an active reservation.")
            reserved = EquipmentUnit.objects.filter(
                pk=unit.pk, status=EquipmentUnit.Status.AVAILABLE
            ).update(status=EquipmentUnit.Status.RESERVED)
            if reserved != 1:
                raise ValidationError("Only available equipment units can be reserved.")
            Allocation.objects.create(request_item=item, unit=unit)
    request.approved_at = now
    request.approved_by = actor
    request.save(update_fields=["approved_at", "approved_by"])
    return request
