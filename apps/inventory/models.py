from django.db import models
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower, Trim


class Category(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [models.UniqueConstraint(Lower(Trim("name")), name="inventory_category_name_ci")]

    def clean(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValidationError({"name": "Enter a category name."})
        duplicates = Category.objects.annotate(name_key=Lower(Trim("name"))).filter(name_key=self.name.lower()).exclude(pk=self.pk)
        if duplicates.exists():
            raise ValidationError({"name": "A category with this name already exists."})

    def __str__(self):
        return self.name


class Equipment(models.Model):
    """An equipment type; each lendable physical copy has an EquipmentUnit."""

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="equipment", null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return self.name

    def clean(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValidationError({"name": "Enter an equipment name."})


class EquipmentUnit(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        RESERVED = "RESERVED", "Reserved"
        ON_LOAN = "ON_LOAN", "On loan"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        RETIRED = "RETIRED", "Retired"

    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="units")
    asset_tag = models.CharField(max_length=80, unique=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.AVAILABLE)

    class Meta:
        ordering = ["asset_tag"]
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=["AVAILABLE", "RESERVED", "ON_LOAN", "MAINTENANCE", "RETIRED"]), name="inventory_valid_unit_status"),
            models.UniqueConstraint(Lower(Trim("asset_tag")), name="inventory_unit_asset_tag_ci"),
        ]

    def clean(self):
        self.asset_tag = self.asset_tag.strip().upper()
        if not self.asset_tag or len(self.asset_tag) > 80:
            raise ValidationError({"asset_tag": "Enter a physical unit identifier of 1–80 characters."})
        duplicate = EquipmentUnit.objects.annotate(tag_key=Lower(Trim("asset_tag"))).filter(tag_key=self.asset_tag.lower()).exclude(pk=self.pk)
        if duplicate.exists():
            raise ValidationError({"asset_tag": "This physical unit identifier is already in use."})

    @property
    def inventory_status_label(self):
        return "Issued" if self.status == self.Status.ON_LOAN else self.get_status_display()

    @property
    def status_variant(self):
        return {self.Status.AVAILABLE: "success", self.Status.RESERVED: "warning", self.Status.ON_LOAN: "info", self.Status.MAINTENANCE: "error", self.Status.RETIRED: "inactive"}.get(self.status, "inactive")

    @property
    def can_edit(self):
        if self.status not in [self.Status.AVAILABLE, self.Status.RETIRED]:
            return False
        allocated = getattr(self, "has_active_allocation", None)
        issued = getattr(self, "has_outstanding_loan", None)
        if allocated is None:
            allocated = self.allocations.filter(active=True).exists()
        if issued is None:
            issued = self.loan_units.filter(returned_at__isnull=True).exists()
        maintenance = getattr(self, "has_active_maintenance", None)
        if maintenance is None:
            maintenance = self.maintenance_records.filter(status__in=["REPORTED", "IN_PROGRESS"]).exists()
        return not allocated and not issued and not maintenance

    @property
    def can_retire(self):
        return self.status == self.Status.AVAILABLE and self.can_edit

    def __str__(self):
        return f"{self.equipment.name} ({self.asset_tag})"
