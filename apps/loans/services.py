"""All issuance and returns must pass through these atomic operations."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.borrowing.models import Allocation, BorrowingRequest
from apps.dashboard.audit import record_event
from apps.inventory.models import EquipmentUnit
from .models import Loan, LoanUnit


def _require_admin(actor):
    if not actor.is_authenticated or not actor.is_active or actor.role != "ADMIN":
        raise PermissionDenied("Only an active Admin may release equipment or process returns.")


def validate_handover(request, items, allocations, units, *, at=None):
    """Shared read-only review checks; issuance repeats them under locks."""
    now = at or timezone.now()
    if not request.approved_at or not request.approved_by_id:
        raise ValidationError("This request does not have a recorded approval.")
    if request.due_at <= now:
        raise ValidationError("The approved due date has passed. The request must be reviewed before release.")
    if request.borrower.role != "BASIC_USER" or not request.borrower.is_active:
        raise ValidationError("Equipment can only be released to an active Basic User.")
    unit_ids = [allocation.unit_id for allocation in allocations]
    if not items or not allocations or len(unit_ids) != len(set(unit_ids)):
        raise ValidationError("Allocate the required physical units before releasing this request.")
    for item in items:
        allocated = [
            allocation for allocation in allocations
            if allocation.request_item_id == item.pk
        ]
        if len(allocated) != item.quantity:
            raise ValidationError("Every requested quantity must be fully allocated before release.")
        for allocation in allocated:
            unit = units[allocation.unit_id]
            if unit.equipment_id != item.equipment_id:
                raise ValidationError("An allocated unit does not match the requested equipment.")
            if unit.status != EquipmentUnit.Status.RESERVED:
                raise ValidationError("All allocated units must still be reserved for this request.")
            if unit.maintenance_records.filter(status__in=["REPORTED", "IN_PROGRESS"]).exists():
                raise ValidationError("An allocated unit has active maintenance and cannot be released.")


@transaction.atomic
def release_request(request_id, *, actor):
    _require_admin(actor)
    # A conditional write claims the request even on SQLite. Any validation
    # failure rolls this transition and every unit update back together.
    claimed = BorrowingRequest.objects.filter(
        pk=request_id, status=BorrowingRequest.Status.APPROVED
    ).update(status=BorrowingRequest.Status.ISSUED)
    if claimed != 1:
        raise ValidationError("This request is not approved for release or has already been issued.")
    request = BorrowingRequest.objects.select_for_update().get(pk=request_id)
    if Loan.objects.filter(request=request).exists():
        raise ValidationError("This request already has a loan.")

    items = list(request.items.select_for_update().order_by("pk"))
    allocations = list(
        Allocation.objects.select_for_update()
        .filter(request_item__request=request, active=True).order_by("pk")
    )
    unit_ids = [allocation.unit_id for allocation in allocations]
    units = {
        unit.pk: unit for unit in EquipmentUnit.objects.select_for_update()
        .filter(pk__in=unit_ids).order_by("pk")
    }
    now = timezone.now()
    validate_handover(request, items, allocations, units, at=now)
    for unit in units.values():
        if LoanUnit.objects.filter(unit=unit, returned_at__isnull=True).exists():
            raise ValidationError("An allocated unit is already on loan.")
        issued = EquipmentUnit.objects.filter(
            pk=unit.pk, status=EquipmentUnit.Status.RESERVED
        ).update(status=EquipmentUnit.Status.ON_LOAN)
        if issued != 1:
            raise ValidationError("All allocated units must still be reserved for this request.")

    loan = Loan.objects.create(
        request=request, borrower=request.borrower, issued_by=actor,
        issued_at=now, due_at=request.due_at,
    )
    for allocation in allocations:
        unit = units[allocation.unit_id]
        LoanUnit.objects.create(
            loan=loan, allocation=allocation, unit=unit,
            equipment_name=unit.equipment.name,
            equipment_description=unit.equipment.description,
            asset_tag=unit.asset_tag,
        )
    record_event(actor=actor, action="LOAN_RELEASED", entity_type="loan", entity_id=loan.pk, description=f"Released {len(allocations)} physical unit(s) for request #{request.pk}.")
    return loan


@transaction.atomic
def process_returns(loan_id, *, actor, returns):
    """returns contains (loan_unit_id, condition, notes) for selected units."""
    _require_admin(actor)
    if not returns:
        raise ValidationError("Select at least one physical unit to return.")
    ids = [entry[0] for entry in returns]
    if len(ids) != len(set(ids)):
        raise ValidationError("A physical unit cannot be returned twice in the same submission.")
    for _, condition, notes in returns:
        if condition not in LoanUnit.Condition.values:
            raise ValidationError("Select a valid condition for every returned unit.")
        if not isinstance(notes, str) or len(notes) > 1000:
            raise ValidationError("Return notes must be text of at most 1,000 characters.")
        if condition == LoanUnit.Condition.DAMAGED and not notes.strip():
            raise ValidationError("Describe the damage so the Maintenance team can assess it.")

    # Serialize returns to this loan, including partial returns on SQLite.
    claimed = Loan.objects.filter(
        pk=loan_id, completed_at__isnull=True
    ).update(due_at=F("due_at"))
    if claimed != 1:
        raise ValidationError("This loan is already completed or does not exist.")
    loan = Loan.objects.select_for_update().get(pk=loan_id)
    request = BorrowingRequest.objects.select_for_update().get(pk=loan.request_id)
    if request.status != BorrowingRequest.Status.ISSUED:
        raise ValidationError("Returns require an issued borrowing request.")
    loan_units = {
        item.pk: item for item in LoanUnit.objects.select_for_update()
        .filter(loan=loan, pk__in=ids).order_by("pk")
    }
    if len(loan_units) != len(ids):
        raise ValidationError("One or more selected units do not belong to this loan.")
    allocations = {
        item.pk: item for item in Allocation.objects.select_for_update()
        .filter(pk__in=[item.allocation_id for item in loan_units.values()])
        .order_by("pk")
    }
    units = {
        unit.pk: unit for unit in EquipmentUnit.objects.select_for_update()
        .filter(pk__in=[item.unit_id for item in loan_units.values()])
        .order_by("pk")
    }
    now = timezone.now()
    if now < loan.issued_at:
        raise ValidationError("A return cannot occur before the loan's issue date.")
    for item_id, condition, notes in sorted(returns):
        item = loan_units[item_id]
        allocation = allocations[item.allocation_id]
        unit = units[item.unit_id]
        if item.returned_at is not None:
            raise ValidationError("A selected physical unit has already been returned.")
        if (
            not allocation.active or allocation.unit_id != unit.pk
            or allocation.request_item.request_id != request.pk
        ):
            raise ValidationError("The issued unit's allocation is inconsistent. No returns were saved.")
        if unit.status != EquipmentUnit.Status.ON_LOAN:
            raise ValidationError("A selected unit is no longer marked as on loan.")
        if unit.maintenance_records.filter(status__in=["REPORTED", "IN_PROGRESS"]).exists():
            raise ValidationError("This issued unit has conflicting active maintenance. Review its history before returning it.")
        returned = LoanUnit.objects.filter(
            pk=item.pk, returned_at__isnull=True
        ).update(
            returned_at=now, return_condition=condition,
            return_notes=notes.strip(), received_by=actor,
        )
        if returned != 1:
            raise ValidationError("A selected unit has already been returned.")
        status = (
            EquipmentUnit.Status.MAINTENANCE
            if condition == LoanUnit.Condition.DAMAGED
            else EquipmentUnit.Status.AVAILABLE
        )
        updated = EquipmentUnit.objects.filter(
            pk=unit.pk, status=EquipmentUnit.Status.ON_LOAN
        ).update(status=status)
        if updated != 1:
            raise ValidationError("The unit's status changed. Reload the loan and try again.")
        if Allocation.objects.filter(pk=allocation.pk, active=True).update(active=False) != 1:
            raise ValidationError("The unit's reservation changed. Reload the loan and try again.")
        if condition == LoanUnit.Condition.DAMAGED:
            from apps.maintenance.services import record_damaged_return
            record_damaged_return(item.pk, actor=actor)

    if not loan.units.filter(returned_at__isnull=True).exists():
        loan.completed_at = now
        loan.save(update_fields=["completed_at"])
        request.status = BorrowingRequest.Status.COMPLETED
        request.save(update_fields=["status"])
    damaged = sum(condition == LoanUnit.Condition.DAMAGED for _, condition, _ in returns)
    record_event(actor=actor, action="UNITS_RETURNED", entity_type="loan", entity_id=loan.pk, description=f"Returned {len(returns)} physical unit(s); {damaged} sent to Maintenance.")
    return loan
