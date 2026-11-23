"""Pure Decimal arithmetic for the approved India GST V1 calculation scope."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

INTERMEDIATE_QUANTUM = Decimal("0.0001")
PAISE_QUANTUM = Decimal("0.01")
ZERO_PAISE = Decimal("0.00")


class GSTSupplyType(StrEnum):
    INTRA_STATE = "intra_state"
    INTER_STATE = "inter_state"


@dataclass(frozen=True)
class GSTBreakdown:
    taxable_value: Decimal
    rate_percent: Decimal
    cgst: Decimal = ZERO_PAISE
    sgst: Decimal = ZERO_PAISE
    igst: Decimal = ZERO_PAISE

    @property
    def total(self) -> Decimal:
        return self.cgst + self.sgst + self.igst


def calculate_line_gst(
    *,
    taxable_value: Decimal | int | str,
    rate_percent: Decimal | int | str,
    supply_type: GSTSupplyType | str,
) -> GSTBreakdown:
    """Calculate GST for one pre-tax line value using the selected tax rate.

    The caller is responsible for selecting the legally applicable rate and
    supply type from reviewed HSN/SAC and place-of-supply data. Each component
    is rounded independently to paise, half-up. Invoice aggregation and
    statutory nearest-rupee rounding are deliberately outside this function.
    """
    taxable_value = _as_decimal(taxable_value, "taxable_value")
    rate_percent = _as_decimal(rate_percent, "rate_percent")
    try:
        supply_type = GSTSupplyType(supply_type)
    except ValueError as error:
        raise ValueError("Unsupported GST supply type.") from error

    if taxable_value < 0:
        raise ValueError("Taxable value cannot be negative.")
    if rate_percent < 0:
        raise ValueError("GST rate cannot be negative.")

    taxable_value = _quantize(taxable_value, INTERMEDIATE_QUANTUM)
    rate_percent = _quantize(rate_percent, INTERMEDIATE_QUANTUM)

    if supply_type == GSTSupplyType.INTER_STATE:
        return GSTBreakdown(
            taxable_value=taxable_value,
            rate_percent=rate_percent,
            igst=_tax_component(taxable_value, rate_percent),
        )

    component_rate = _quantize(rate_percent / 2, INTERMEDIATE_QUANTUM)
    component_tax = _tax_component(taxable_value, component_rate)
    return GSTBreakdown(
        taxable_value=taxable_value,
        rate_percent=rate_percent,
        cgst=component_tax,
        sgst=component_tax,
    )


def _tax_component(taxable_value: Decimal, rate_percent: Decimal) -> Decimal:
    intermediate_tax = _quantize(
        taxable_value * rate_percent / Decimal("100"), INTERMEDIATE_QUANTUM
    )
    return _quantize(intermediate_tax, PAISE_QUANTUM)


def _as_decimal(value: Decimal | int | str, field_name: str) -> Decimal:
    if isinstance(value, (float, bool)):
        raise TypeError(f"{field_name} must not be a float.")
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a finite decimal value.") from error
    if not result.is_finite():
        raise ValueError(f"{field_name} must be a finite decimal value.")
    return result


def _quantize(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)
