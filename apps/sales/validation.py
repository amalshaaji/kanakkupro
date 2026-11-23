import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

# V1 supports domestic States with CGST/SGST, and inter-State IGST.
# Intra-UT supplies needing UTGST are explicitly rejected rather than mislabelled.
STATES = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
}
UTGST_STATES = {"04", "26", "31", "35", "38"}
STATE_CHOICES = [("", "Select a state"), *sorted(STATES.items(), key=lambda x: x[1])]


def validate_gstin(value):
    if not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", value):
        raise ValidationError("Enter a 15-character GSTIN in uppercase.")
    if value[:2] not in STATES:
        raise ValidationError("Select a supported domestic GST registration state.")
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    total = 0
    factor = 2
    for character in reversed(value[:-1]):
        product = alphabet.index(character) * factor
        total += product // 36 + product % 36
        factor = 1 if factor == 2 else 2
    if alphabet[(36 - total % 36) % 36] != value[-1]:
        raise ValidationError("The GSTIN checksum is invalid.")


def exact_decimal(
    value, *, places=4, maximum=Decimal("9999999999.9999"), positive=False
):
    if isinstance(value, (float, bool)):
        raise ValidationError("Use an exact decimal value.")
    try:
        value = Decimal(value)
        if not value.is_finite() or value < 0 or value > maximum:
            raise ValidationError(
                "Enter a finite nonnegative amount within the field limit."
            )
        if positive and value == 0:
            raise ValidationError("Enter an amount greater than zero.")
        if value != value.quantize(Decimal(1).scaleb(-places)):
            raise ValidationError(f"Use at most {places} decimal places.")
    except (TypeError, ValueError, InvalidOperation) as error:
        raise ValidationError("Enter a valid decimal amount.") from error
    return value
