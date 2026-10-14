from django import forms
from django.forms import BaseFormSet, formset_factory

from .models import LoanUnit


class LoanFilterForm(forms.Form):
    q = forms.CharField(label="Search equipment or asset tag", max_length=150, required=False)
    status = forms.ChoiceField(required=False, choices=[("", "All active loans"), ("active", "On time"), ("overdue", "Overdue"), ("partial", "Partially returned")])
    due_from = forms.DateField(label="Due from", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    due_to = forms.DateField(label="Due through", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, history=False, admin=False, **kwargs):
        super().__init__(*args, **kwargs)
        if history:
            self.fields.pop("status")
        if admin:
            self.fields["q"].label = "Search borrower, equipment or asset tag"

    def clean(self):
        data = super().clean()
        if data.get("due_from") and data.get("due_to") and data["due_from"] > data["due_to"]:
            self.add_error("due_to", "End date must be on or after the start date.")
        return data


class RequestFilterForm(forms.Form):
    q = forms.CharField(label="Search borrower or equipment", max_length=150, required=False)


class ReleaseForm(forms.Form):
    confirm = forms.BooleanField(label="I checked the reserved units and confirm they are being handed to the borrower.", error_messages={"required": "Confirm the handover before releasing the equipment."})


class ReturnConfirmationForm(forms.Form):
    confirm = forms.BooleanField(label="I checked the selected units and confirm they have been physically returned.", error_messages={"required": "Confirm the physical return before saving."})


class ReturnUnitForm(forms.Form):
    loan_unit_id = forms.IntegerField(widget=forms.HiddenInput)
    return_now = forms.BooleanField(label="Return this unit", required=False)
    condition = forms.ChoiceField(label="Return condition", required=False, choices=[("", "Choose condition"), *LoanUnit.Condition.choices])
    notes = forms.CharField(label="Return notes", max_length=1000, required=False, help_text="Describe any damage. These notes are visible to the borrower.", widget=forms.Textarea(attrs={"rows": 2}))

    def clean(self):
        data = super().clean()
        if data.get("return_now"):
            if not data.get("condition"):
                self.add_error("condition", "Choose a condition for this returned unit.")
            if data.get("condition") == LoanUnit.Condition.DAMAGED and not data.get("notes"):
                self.add_error("notes", "Describe the damage for Maintenance.")
        return data


class BaseReturnUnitFormSet(BaseFormSet):
    default_error_messages = {
        "too_many_forms": "The loan changed or the form contains invalid units. Reload this page before returning equipment. Maximum unit rows: %(num)d."
    }

    def __init__(self, *args, expected_ids, **kwargs):
        self.expected_ids = set(expected_ids)
        super().__init__(*args, **kwargs)
        # Bound submissions cannot manufacture extra rows. The limit follows
        # the actual loan size rather than imposing a borrowing quantity cap.
        self.max_num = len(self.expected_ids)
        self.absolute_max = max(self.max_num, 100)

    def clean(self):
        if any(self.errors):
            return
        ids = [form.cleaned_data.get("loan_unit_id") for form in self.forms]
        if len(ids) != len(set(ids)) or set(ids) != self.expected_ids:
            raise forms.ValidationError("The loan changed or the form contains invalid units. Reload this page before returning equipment.")
        if not any(form.cleaned_data.get("return_now") for form in self.forms):
            raise forms.ValidationError("Select at least one physical unit to return.")

    def selected_returns(self):
        return [(form.cleaned_data["loan_unit_id"], form.cleaned_data["condition"], form.cleaned_data.get("notes", "")) for form in self.forms if form.cleaned_data.get("return_now")]


ReturnUnitFormSet = formset_factory(ReturnUnitForm, formset=BaseReturnUnitFormSet, extra=0, validate_max=True)
