from datetime import datetime, time, timedelta

from django import forms
from django.forms import BaseFormSet, formset_factory
from django.utils import timezone

from .models import BorrowingRequest
from .services import borrowing_limits, catalog_queryset, validate_due_date


class BorrowingRequestForm(forms.Form):
    purpose = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))
    due_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        latest = today + timedelta(days=borrowing_limits()["max_days"])
        self.fields["due_date"].initial = latest
        self.fields["due_date"].widget.attrs.update(min=today.isoformat(), max=latest.isoformat())
        self.fields["due_date"].help_text = f"Return by the end of this date ({timezone.get_current_timezone_name()}). Maximum {borrowing_limits()['max_days']} calendar days from today."

    def clean(self):
        data = super().clean()
        if data.get("due_date"):
            due_at = timezone.make_aware(datetime.combine(data["due_date"], time(23, 59, 59)))
            try:
                validate_due_date(due_at)
            except forms.ValidationError as error:
                self.add_error("due_date", error)
            else:
                data["due_at"] = due_at
        return data


class CatalogChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.name} ({obj.available_count} available)"


class RequestItemForm(forms.Form):
    equipment = CatalogChoiceField(queryset=catalog_queryset().none(), required=False, empty_label="Choose equipment")
    quantity = forms.IntegerField(min_value=1, required=False, initial=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["equipment"].queryset = catalog_queryset().filter(available_count__gt=0)
        self.fields["quantity"].max_value = borrowing_limits()["max_quantity"]
        self.fields["quantity"].widget.attrs.update(min=1, max=borrowing_limits()["max_quantity"])

    def clean(self):
        data = super().clean()
        if data.get("equipment") and data.get("quantity") is None:
            self.add_error("quantity", "Enter the quantity for this equipment.")
        if not data.get("equipment") and data.get("quantity") not in [None, 1]:
            self.add_error("equipment", "Select equipment for this quantity.")
        maximum = borrowing_limits()["max_quantity"]
        if data.get("quantity") and data["quantity"] > maximum:
            self.add_error("quantity", f"Request at most {maximum} units per item.")
        return data


class BaseRequestItemFormSet(BaseFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_num = borrowing_limits()["max_items"]
        self.extra = self.max_num
        self.absolute_max = max(self.max_num, 100)

    def clean(self):
        if any(self.errors):
            return
        selected = [form.cleaned_data["equipment"].pk for form in self.forms if form.cleaned_data.get("equipment")]
        if not 1 <= len(selected) <= self.max_num:
            raise forms.ValidationError(f"Select 1–{self.max_num} distinct equipment items.")
        if len(set(selected)) != len(selected):
            raise forms.ValidationError("Each equipment item can be selected only once.")

    def requested_items(self):
        return [(form.cleaned_data["equipment"].pk, form.cleaned_data["quantity"]) for form in self.forms if form.cleaned_data.get("equipment")]


RequestItemFormSet = formset_factory(RequestItemForm, formset=BaseRequestItemFormSet, extra=0, validate_max=True)


class ReviewForm(forms.Form):
    rejection_reason = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))
    confirm = forms.BooleanField(label="I confirm this action.", error_messages={"required": "Confirm this action before continuing."})

    def __init__(self, *args, action, **kwargs):
        super().__init__(*args, **kwargs)
        if action != "reject":
            self.fields.pop("rejection_reason")


class RequestFilterForm(forms.Form):
    q = forms.CharField(label="Search equipment or purpose", max_length=150, required=False)
    status = forms.ChoiceField(required=False, choices=[
        ("", "All requests"), ("PENDING", "Pending"), ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"), ("CANCELLED", "Cancelled"), ("ISSUED", "Issued"),
        ("partial", "Partially Returned"), ("COMPLETED", "Returned"),
    ])

    def __init__(self, *args, admin=False, **kwargs):
        super().__init__(*args, **kwargs)
        if admin:
            self.fields["q"].label = "Search borrower, equipment or purpose"
