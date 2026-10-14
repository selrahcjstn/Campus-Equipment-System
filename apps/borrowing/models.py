from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone


class BorrowingRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"
        ISSUED = "ISSUED", "Issued"
        COMPLETED = "COMPLETED", "Completed"

    borrower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="borrowing_requests")
    purpose = models.TextField(max_length=1000)
    requested_at = models.DateTimeField(default=timezone.now)
    due_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approved_borrowing_requests", null=True, blank=True)

    class Meta:
        ordering = ["-requested_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=["PENDING", "APPROVED", "REJECTED", "CANCELLED", "ISSUED", "COMPLETED"]), name="borrowing_valid_request_status"),
            models.CheckConstraint(condition=models.Q(due_at__gt=models.F("requested_at")), name="borrowing_due_after_request"),
        ]

    @property
    def quantity(self):
        return sum(item.quantity for item in self.items.all())

    def __str__(self):
        return f"Request #{self.pk}"


class BorrowingRequestItem(models.Model):
    request = models.ForeignKey(BorrowingRequest, on_delete=models.CASCADE, related_name="items")
    equipment = models.ForeignKey("inventory.Equipment", on_delete=models.PROTECT, related_name="request_items")
    quantity = models.PositiveIntegerField()

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["request", "equipment"], name="borrowing_one_equipment_per_request"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="borrowing_positive_quantity"),
        ]

    def __str__(self):
        return f"{self.equipment.name} × {self.quantity}"


class Allocation(models.Model):
    request_item = models.ForeignKey(BorrowingRequestItem, on_delete=models.PROTECT, related_name="allocations")
    unit = models.ForeignKey("inventory.EquipmentUnit", on_delete=models.PROTECT, related_name="allocations")
    # Reservations stay active through issuance, then end per returned unit.
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["request_item", "unit"], name="borrowing_unique_item_unit"),
            models.UniqueConstraint(fields=["unit"], condition=models.Q(active=True), name="borrowing_one_active_allocation"),
        ]

    def clean(self):
        if self.request_item_id and self.unit_id and self.request_item.equipment_id != self.unit.equipment_id:
            raise ValidationError({"unit": "The unit must match the requested equipment."})
