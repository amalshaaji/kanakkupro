from django import forms

from apps.common.forms import AccessibleFormMixin
from apps.tenants.models import PilotCheck, PilotFeedback


class PilotCheckForm(forms.Form):
    code = forms.ChoiceField(choices=PilotCheck.Code.choices)
    confirmed = forms.BooleanField(required=False)


class PilotFeedbackForm(AccessibleFormMixin, forms.ModelForm):
    request_id = forms.RegexField(
        regex=r"^[a-f0-9]{32}$",
        max_length=32,
        widget=forms.TextInput(attrs={"class": "input input-bordered w-full"}),
        required=False,
        label="Support reference (optional)",
        error_messages={
            "invalid": "Use the 32-character reference shown on an error page."
        },
    )

    class Meta:
        model = PilotFeedback
        fields = ["kind", "severity", "description", "request_id"]
        widgets = {
            "kind": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "severity": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "description": forms.Textarea(
                attrs={"class": "textarea textarea-bordered w-full", "rows": 4}
            ),
            "request_id": forms.TextInput(
                attrs={"class": "input input-bordered w-full"}
            ),
        }


class PilotStatusForm(forms.Form):
    status = forms.ChoiceField(choices=PilotFeedback.Status.choices)
