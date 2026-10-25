from django import forms
from django.db.models import Q
from django.utils import timezone

from .models import Category, Equipment, EquipmentUnit


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class EquipmentForm(forms.ModelForm):
    class Meta:
        model = Equipment
        fields = ["name", "category", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}
        labels = {"description": "Public catalog description"}
        help_texts = {"description": "Shown in the Basic User catalog. Use the owning workflow for internal unit or maintenance records."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].required = True
        choices = Q(is_active=True)
        if self.instance.pk and self.instance.category_id:
            choices |= Q(pk=self.instance.category_id)
        self.fields["category"].queryset = Category.objects.filter(choices)
        self.fields["category"].help_text = "Select an active category. Existing equipment may keep its current archived category."


class UnitForm(forms.ModelForm):
    class Meta:
        model = EquipmentUnit
        fields = ["asset_tag", "condition", "acquisition_date"]
        labels = {"asset_tag": "Physical unit identifier"}
        widgets = {"acquisition_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}
        help_texts = {
            "asset_tag": "A unique tag, barcode or serial identifier. Surrounding spaces are removed and letters are normalized to uppercase.",
            "condition": "Physical condition is separate from inventory status. Leave blank if not recorded.",
            "acquisition_date": "Enter the actual acquisition date. Leave blank if unknown; do not estimate.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["condition"].choices = [("", "Not recorded"), *EquipmentUnit.Condition.choices]
        self.fields["acquisition_date"].widget.attrs["max"] = timezone.localdate().isoformat()


class ConfirmationForm(forms.Form):
    confirm = forms.BooleanField(label="I confirm this action.", error_messages={"required": "Confirm this action before continuing."})


class CatalogFilterForm(forms.Form):
    q = forms.CharField(label="Search equipment name", max_length=150, required=False)
    category = forms.ModelChoiceField(queryset=Category.objects.all(), required=False, empty_label="All categories")
    availability = forms.ChoiceField(required=False, choices=[("", "Any availability"), ("available", "Available"), ("unavailable", "Unavailable")])


class EquipmentFilterForm(CatalogFilterForm):
    q = forms.CharField(label="Search equipment name or physical unit identifier", max_length=150, required=False)
    state = forms.ChoiceField(required=False, choices=[("", "All catalog items"), ("active", "Active"), ("archived", "Archived")])


class UnitFilterForm(forms.Form):
    q = forms.CharField(label="Search identifier or equipment", max_length=150, required=False)
    category = forms.ModelChoiceField(queryset=Category.objects.all(), required=False, empty_label="All categories")
    equipment = forms.ModelChoiceField(queryset=Equipment.objects.all(), required=False, empty_label="All equipment")
    status = forms.ChoiceField(required=False, choices=[("", "All unit statuses"), ("AVAILABLE", "Available"), ("RESERVED", "Reserved"), ("ON_LOAN", "Issued"), ("MAINTENANCE", "Maintenance"), ("RETIRED", "Retired")])


class CategoryFilterForm(forms.Form):
    q = forms.CharField(label="Search category name", max_length=100, required=False)
