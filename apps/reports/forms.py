from django import forms


class ReportPeriodForm(forms.Form):
    start = forms.DateField(
        required=False,
        label="From",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "input input-bordered w-full"}
        ),
    )
    end = forms.DateField(
        required=False,
        label="Through",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "input input-bordered w-full"}
        ),
    )

    def clean(self):
        values = super().clean()
        if (
            values.get("start")
            and values.get("end")
            and values["start"] > values["end"]
        ):
            raise forms.ValidationError(
                "The start date must be on or before the end date."
            )
        return values
