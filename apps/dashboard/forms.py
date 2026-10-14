from django import forms
from .models import AuditLog, LIMIT_RANGES


class DateRangeForm(forms.Form):
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        values = super().clean()
        for name in ["start_date", "end_date"]:
            date = values.get(name)
            if date and not 1900 <= date.year <= 2100:
                self.add_error(name, "Choose a date from 1900 through 2100.")
        start, end = values.get("start_date"), values.get("end_date")
        if start and end and start > end:
            raise forms.ValidationError("The start date must be on or before the end date.")
        return values


class ChartPeriodForm(DateRangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = True

    def clean(self):
        values = super().clean()
        if values.get("start_date") and values.get("end_date") and (values["end_date"] - values["start_date"]).days > 365:
            raise forms.ValidationError("Choose a chart period of at most 366 calendar dates.")
        return values


class ReportFilterForm(DateRangeForm):
    report = forms.ChoiceField(choices=[("loans", "Loan report (issue dates)"), ("overdue", "Currently overdue (due dates)")])


class AuditFilterForm(DateRangeForm):
    q = forms.CharField(label="Search actor, action or affected entity", required=False, max_length=150)
    action = forms.ChoiceField(required=False, choices=[("", "All actions"), *AuditLog.Action.choices])


class SystemSettingsForm(forms.Form):
    max_items = forms.IntegerField(min_value=LIMIT_RANGES["max_items"][0], max_value=LIMIT_RANGES["max_items"][1], label="Maximum distinct catalog items", help_text="1–10 distinct catalog items per request. Default: 3.")
    max_quantity = forms.IntegerField(min_value=LIMIT_RANGES["max_quantity"][0], max_value=LIMIT_RANGES["max_quantity"][1], label="Maximum units per catalog item", help_text="1–20 units per catalog item. Default: 3.")
    max_days = forms.IntegerField(min_value=LIMIT_RANGES["max_days"][0], max_value=LIMIT_RANGES["max_days"][1], label="Maximum borrowing duration", help_text="1–30 calendar days in the application timezone. Default: 7.")
    confirm = forms.BooleanField(label="I confirm these borrowing rules for new requests.")
