from django import forms

from apps.inventory.models import Equipment
from .models import ACTIVE_STATUSES, MaintenanceRecord
from .services import eligible_units


class MaintenanceForm(forms.Form):
    unit = forms.ModelChoiceField(queryset=eligible_units(), label="Physical equipment unit", help_text="Select an Available unit or a Maintenance unit without an active record. Reserved, Issued and Retired units are excluded.")
    reason = forms.CharField(max_length=1000, label="Reported issue", widget=forms.Textarea(attrs={"rows": 4}))


class ProgressForm(forms.Form):
    status = forms.ChoiceField(choices=[(value, label) for value, label in MaintenanceRecord.Status.choices if value in ACTIVE_STATUSES])
    repair_notes = forms.CharField(max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 5}), help_text="Internal assessment and repair progress. These notes are visible only to Admins.")

    def __init__(self, *args, record, **kwargs):
        super().__init__(*args, **kwargs)
        if record.status == "IN_PROGRESS":
            self.fields["status"].choices = [("IN_PROGRESS", "In progress")]


class ResolutionForm(forms.Form):
    repair_notes = forms.CharField(max_length=2000, label="Repair or retirement notes", widget=forms.Textarea(attrs={"rows": 5}), help_text="Record the completed repair and checks, or explain why the unit cannot be repaired.")
    confirm = forms.BooleanField(label="I confirm this maintenance outcome.", error_messages={"required": "Confirm the outcome before continuing."})


class StartRepairForm(forms.Form):
    confirm = forms.BooleanField(widget=forms.HiddenInput, initial=True,
                                 error_messages={"required": "Confirm that repair work is starting."})


class CompletionForm(ResolutionForm):
    outcome = forms.ChoiceField(choices=[("REPAIRED", "Repaired / serviceable"), ("RETIRED", "Retired / unserviceable")])
    repair_notes = forms.CharField(max_length=2000, label="Repair action taken", widget=forms.Textarea(attrs={"rows": 3}),
                                  help_text="Describe the work and checks completed, or why the unit must be retired.")
    field_order = ["outcome", "repair_notes", "confirm"]


class MaintenanceFilterForm(forms.Form):
    q = forms.CharField(label="Search unit, equipment or issue", max_length=150, required=False)
    status = forms.ChoiceField(required=False, choices=[("", "All statuses"), ("active", "Active maintenance"), *MaintenanceRecord.Status.choices])
    equipment = forms.ModelChoiceField(queryset=Equipment.objects.all(), required=False, empty_label="All equipment")
