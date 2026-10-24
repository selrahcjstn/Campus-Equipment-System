from django.db import models
from django.conf import settings
from django.utils import timezone
from collections import Counter


class LoanQuerySet(models.QuerySet):
    def active(self):
        return self.filter(completed_at__isnull=True)

    def completed(self):
        return self.filter(completed_at__isnull=False)

    def overdue(self, at=None):
        outstanding = LoanUnit.objects.filter(loan_id=models.OuterRef("pk"), returned_at__isnull=True)
        return self.active().filter(models.Exists(outstanding), due_at__lt=at or timezone.now())


class Loan(models.Model):
    request = models.OneToOneField("borrowing.BorrowingRequest", on_delete=models.PROTECT, related_name="loan")
    borrower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="loans")
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="issued_loans")
    issued_at = models.DateTimeField(default=timezone.now)
    due_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = LoanQuerySet.as_manager()

    class Meta:
        ordering = ["-issued_at", "-pk"]
        indexes = [models.Index(fields=["borrower", "completed_at"], name="loan_borrower_completion"), models.Index(fields=["completed_at", "due_at"], name="loan_completion_due")]
        constraints = [
            models.CheckConstraint(condition=models.Q(due_at__gt=models.F("issued_at")), name="loan_due_after_issue"),
            models.CheckConstraint(condition=models.Q(completed_at__isnull=True) | models.Q(completed_at__gte=models.F("issued_at")), name="loan_completion_after_issue"),
        ]

    @property
    def is_overdue(self):
        return self.is_overdue_at(timezone.now())

    def is_overdue_at(self, at):
        return self.completed_at is None and self.due_at < at and self.outstanding_count > 0

    def overdue_days(self, at=None):
        at = at or timezone.now()
        if not self.is_overdue_at(at):
            return 0
        zone = timezone.get_default_timezone()  # Application calendar: Asia/Manila.
        return max((timezone.localdate(at, zone) - timezone.localdate(self.due_at, zone)).days, 0)

    @property
    def outstanding_count(self):
        return sum(unit.returned_at is None for unit in self.units.all())

    @property
    def quantity(self):
        return len(self.units.all())

    @property
    def equipment_summary(self):
        counts = Counter(unit.equipment_name for unit in self.units.all())
        return [{"name": name, "quantity": count} for name, count in sorted(counts.items())]

    @property
    def status(self):
        if self.completed_at or (self.quantity and not self.outstanding_count):
            return "Completed"
        if self.is_overdue:
            return "Overdue"
        if any(unit.returned_at for unit in self.units.all()):
            return "Partially returned"
        return "Active"

    @property
    def status_variant(self):
        if self.status == "Completed":
            return "success"
        return "error" if self.is_overdue else "info"

    def __str__(self):
        return f"Loan #{self.pk}"


class LoanUnit(models.Model):
    class Condition(models.TextChoices):
        GOOD = "GOOD", "Good / undamaged"
        DAMAGED = "DAMAGED", "Damaged"

    loan = models.ForeignKey(Loan, on_delete=models.PROTECT, related_name="units")
    allocation = models.OneToOneField("borrowing.Allocation", on_delete=models.PROTECT, related_name="loan_unit")
    unit = models.ForeignKey("inventory.EquipmentUnit", on_delete=models.PROTECT, related_name="loan_units")
    # Snapshots keep slips/history accurate if inventory labels change later.
    equipment_name = models.CharField(max_length=150)
    equipment_description = models.TextField(blank=True)
    asset_tag = models.CharField(max_length=80)
    returned_at = models.DateTimeField(null=True, blank=True)
    return_condition = models.CharField(max_length=7, choices=Condition.choices, blank=True)
    return_notes = models.TextField(max_length=1000, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="received_loan_units", null=True, blank=True)

    class Meta:
        ordering = ["asset_tag", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["unit"], condition=models.Q(returned_at__isnull=True), name="loan_one_active_issue_per_unit"),
            models.CheckConstraint(condition=(models.Q(returned_at__isnull=True, return_condition="", received_by__isnull=True, return_notes="") | models.Q(returned_at__isnull=False, return_condition__in=["GOOD", "DAMAGED"], received_by__isnull=False)), name="loan_complete_return_record"),
        ]

    def __str__(self):
        return f"{self.equipment_name} ({self.asset_tag})"
