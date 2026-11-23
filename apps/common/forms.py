class AccessibleFormMixin:
    """Connect field help and validation feedback to its input for assistive tech."""

    def full_clean(self):
        super().full_clean()
        for name in self.fields:
            bound_field = self[name]
            described_by = []
            if bound_field.help_text:
                described_by.append(f"{bound_field.id_for_label}_helptext")
            if bound_field.errors:
                described_by.append(f"{bound_field.id_for_label}_errors")
                bound_field.field.widget.attrs["aria-invalid"] = "true"
            else:
                bound_field.field.widget.attrs.pop("aria-invalid", None)
            if described_by:
                bound_field.field.widget.attrs["aria-describedby"] = " ".join(
                    described_by
                )
            else:
                bound_field.field.widget.attrs.pop("aria-describedby", None)
