"""Borrowing rules and atomic transitions; Loans owns equipment issuance."""
from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.inventory.models import Equipment, EquipmentUnit
from apps.inventory.services import eligible_units, inventory_queryset
from apps.dashboard.audit import record_event
from apps.dashboard.models import LIMIT_RANGES
from apps.dashboard.policies import borrowing_limits
from .models import Allocation, BorrowingRequest, BorrowingRequestItem


def _require_role(actor, role):
    if not actor.is_authenticated or not actor.is_active or actor.role != role:
        raise PermissionDenied(f"This operation requires an active {role} account.")


def available_units():
    return eligible_units()


def catalog_queryset():
    return inventory_queryset().filter(is_active=True)


def validate_due_date(due_at, *, requested_at=None, limits=None):
    now = timezone.now()
    requested_at = requested_at or now
    if not isinstance(due_at, datetime) or not timezone.is_aware(due_at):
        raise ValidationError("Provide a valid due date in the application's timezone.")
    if due_at <= now:
        raise ValidationError("The due date must be in the future.")
    days = (timezone.localdate(due_at) - timezone.localdate(requested_at)).days
    maximum = (limits if limits is not None else borrowing_limits())["max_days"]
    if days < 0 or days > maximum:
        raise ValidationError(f"Borrowing duration cannot exceed {maximum} calendar days.")


def _validate_items(items, *, limits=None):
    limits = limits if limits is not None else borrowing_limits()
    maximum = min(limits["max_items"], LIMIT_RANGES["max_items"][1])
    if not 1 <= len(items) <= maximum:
        raise ValidationError(f"Select 1–{maximum} distinct equipment items.")
    ids = [item[0] for item in items]
    if len(set(ids)) != len(ids):
        raise ValidationError("Each equipment item can be selected only once.")
    for equipment_id, quantity in items:
        if type(equipment_id) is not int or equipment_id < 1:
            raise ValidationError("Select valid equipment from the catalog.")
        if type(quantity) is not int or not 1 <= quantity <= limits["max_quantity"]:
            raise ValidationError(f"Each quantity must be between 1 and {limits['max_quantity']}.")


@transaction.atomic
def submit_request(*, borrower, purpose, due_at, items):
    """items contains (equipment_id, quantity), never client availability."""
    _require_role(borrower, "BASIC_USER")
    # Repeat authorization against the current row and lock it before creating
    # requests. Account deactivation/promotion can happen after authentication.
    User = get_user_model()
    if User.objects.filter(pk=borrower.pk, role="BASIC_USER", is_active=True).update(first_name=F("first_name")) != 1:
        raise PermissionDenied("Only a currently active Basic User may submit requests.")
    borrower = User.objects.select_for_update().get(pk=borrower.pk)
    limits = borrowing_limits()
    _validate_items(items, limits=limits)
    validate_due_date(due_at, limits=limits)
    if not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 1000:
        raise ValidationError("Provide a borrowing purpose of at most 1,000 characters.")
    ids = [entry[0] for entry in items]
    # Coordinate submission with archiving, including SQLite's writer lock.
    Equipment.objects.filter(pk=min(ids)).update(is_active=F("is_active"))
    list(Equipment.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    catalog = {
        item.pk: item for item in catalog_queryset()
        .filter(pk__in=[entry[0] for entry in items])
    }
    for equipment_id, quantity in items:
        if equipment_id not in catalog:
            raise ValidationError("One or more selected equipment items do not exist.")
        if catalog[equipment_id].available_count < quantity:
            raise ValidationError(f"Not enough available units of {catalog[equipment_id].name}.")
    request = BorrowingRequest.objects.create(
        borrower=borrower, purpose=purpose.strip(), due_at=due_at,
    )
    BorrowingRequestItem.objects.bulk_create([
        BorrowingRequestItem(request=request, equipment_id=equipment_id, quantity=quantity)
        for equipment_id, quantity in items
    ])
    return request


@transaction.atomic
def approve_request(request_id, *, actor, allocations=None):
    """Auto-allocate units; explicit mappings remain compatible with Loans."""
    _require_role(actor, "ADMIN")
    # Claim first, including on SQLite where SELECT FOR UPDATE has no effect.
    claimed = BorrowingRequest.objects.filter(
        pk=request_id, status=BorrowingRequest.Status.PENDING,
    ).update(status=BorrowingRequest.Status.APPROVED)
    if claimed != 1:
        raise ValidationError("Only pending requests can be approved.")
    request = BorrowingRequest.objects.select_for_update().get(pk=request_id)
    items = list(request.items.select_for_update().order_by("equipment_id", "pk"))
    catalog = list(Equipment.objects.select_for_update().filter(pk__in=[item.equipment_id for item in items]).order_by("pk"))
    if any(not equipment.is_active for equipment in catalog):
        raise ValidationError("Archived equipment cannot be approved for borrowing.")
    limits = borrowing_limits()
    validate_due_date(request.due_at, requested_at=request.requested_at, limits=limits)
    _validate_items([(item.equipment_id, item.quantity) for item in items], limits=limits)
    if request.borrower.role != "BASIC_USER" or not request.borrower.is_active:
        raise ValidationError("The borrower must be an active Basic User.")
    if hasattr(request, "loan") or request.items.filter(allocations__active=True).exists():
        raise ValidationError("This request already has active allocations or a loan.")

    if allocations is None:
        allocations = {}
        for item in items:
            selected = list(
                available_units().select_for_update()
                .filter(equipment_id=item.equipment_id).order_by("pk")[:item.quantity]
            )
            if len(selected) != item.quantity:
                raise ValidationError(f"Not enough available units of {item.equipment.name}. Nothing was reserved.")
            allocations[item.pk] = [unit.pk for unit in selected]
    if set(allocations) != {item.pk for item in items}:
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
            if not available_units().filter(pk=unit.pk).exists():
                raise ValidationError("An equipment unit is unavailable or has active maintenance or a loan.")
            changed = EquipmentUnit.objects.filter(
                pk=unit.pk, status=EquipmentUnit.Status.AVAILABLE,
            ).update(status=EquipmentUnit.Status.RESERVED)
            if changed != 1:
                raise ValidationError("Only available equipment units can be reserved.")
            Allocation.objects.create(request_item=item, unit=unit)
    request.approved_at = timezone.now()
    request.approved_by = actor
    request.save(update_fields=["approved_at", "approved_by"])
    record_event(actor=actor, action="REQUEST_APPROVED", entity_type="borrowing_request", entity_id=request.pk, description=f"Approved request and reserved {len(ids)} physical unit(s).")
    return request


@transaction.atomic
def reject_request(request_id, *, actor, reason):
    _require_role(actor, "ADMIN")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise ValidationError("Provide a rejection reason of at most 1,000 characters.")
    changed = BorrowingRequest.objects.filter(
        pk=request_id, status=BorrowingRequest.Status.PENDING,
    ).update(status=BorrowingRequest.Status.REJECTED)
    if changed != 1:
        raise ValidationError("Only pending requests can be rejected.")
    request = BorrowingRequest.objects.select_for_update().get(pk=request_id)
    if hasattr(request, "loan") or request.items.filter(allocations__active=True).exists():
        raise ValidationError("This request has reservations or a loan and cannot be rejected.")
    request.rejection_reason = reason.strip()
    request.rejected_at = timezone.now()
    request.rejected_by = actor
    request.save(update_fields=["rejection_reason", "rejected_at", "rejected_by"])
    record_event(actor=actor, action="REQUEST_REJECTED", entity_type="borrowing_request", entity_id=request.pk, description="Rejected pending borrowing request.")
    return request


@transaction.atomic
def cancel_request(request_id, *, actor):
    if not actor.is_authenticated or not actor.is_active or actor.role not in ["ADMIN", "BASIC_USER"]:
        raise PermissionDenied("Only an active Admin or the borrower may cancel a request.")
    eligible = BorrowingRequest.objects.filter(
        pk=request_id, status__in=[BorrowingRequest.Status.PENDING, BorrowingRequest.Status.APPROVED],
    )
    if actor.role == "BASIC_USER":
        eligible = eligible.filter(borrower=actor)
    if eligible.update(status=BorrowingRequest.Status.CANCELLED) != 1:
        request = BorrowingRequest.objects.filter(pk=request_id).first()
        if request and actor.role == "BASIC_USER" and request.borrower_id != actor.pk:
            raise PermissionDenied("You can only cancel your own borrowing requests.")
        raise ValidationError("Only Pending or Approved requests can be cancelled before issuance.")
    request = BorrowingRequest.objects.select_for_update().get(pk=request_id)
    if hasattr(request, "loan"):
        raise ValidationError("Equipment has already been issued for this request.")
    allocations = list(
        Allocation.objects.select_for_update()
        .filter(request_item__request=request, active=True).order_by("unit_id")
    )
    units = {
        unit.pk: unit for unit in EquipmentUnit.objects.select_for_update()
        .filter(pk__in=[allocation.unit_id for allocation in allocations]).order_by("pk")
    }
    for allocation in allocations:
        unit = units[allocation.unit_id]
        changed = EquipmentUnit.objects.filter(
            pk=unit.pk, status=EquipmentUnit.Status.RESERVED,
        ).update(status=EquipmentUnit.Status.AVAILABLE)
        if changed != 1:
            raise ValidationError("A reservation changed or was issued. No cancellation was saved.")
        Allocation.objects.filter(pk=allocation.pk, active=True).update(active=False)
    request.cancelled_at = timezone.now()
    request.cancelled_by = actor
    request.save(update_fields=["cancelled_at", "cancelled_by"])
    record_event(actor=actor, action="REQUEST_CANCELLED", entity_type="borrowing_request", entity_id=request.pk, description=f"Cancelled request and released {len(allocations)} reservation(s).")
    return request
