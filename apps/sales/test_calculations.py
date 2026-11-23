from decimal import Decimal
from unittest import TestCase

from apps.sales.calculations import GSTSupplyType, calculate_line_gst


class GSTLineCalculationTests(TestCase):
    def test_intra_state_rate_splits_into_cgst_and_sgst(self):
        result = calculate_line_gst(
            taxable_value=Decimal("100.0000"),
            rate_percent=Decimal("18"),
            supply_type=GSTSupplyType.INTRA_STATE,
        )

        self.assertEqual(result.cgst, Decimal("9.00"))
        self.assertEqual(result.sgst, Decimal("9.00"))
        self.assertEqual(result.igst, Decimal("0.00"))
        self.assertEqual(result.total, Decimal("18.00"))

    def test_inter_state_rate_uses_igst(self):
        result = calculate_line_gst(
            taxable_value="100.0000",
            rate_percent="18",
            supply_type=GSTSupplyType.INTER_STATE,
        )

        self.assertEqual(result.cgst, Decimal("0.00"))
        self.assertEqual(result.sgst, Decimal("0.00"))
        self.assertEqual(result.igst, Decimal("18.00"))

    def test_rate_is_input_and_tax_rounds_half_up_to_paise_per_component(self):
        result = calculate_line_gst(
            taxable_value="0.0500",
            rate_percent="18",
            supply_type=GSTSupplyType.INTER_STATE,
        )

        self.assertEqual(result.igst, Decimal("0.01"))

    def test_taxable_value_is_quantized_to_four_intermediate_places(self):
        result = calculate_line_gst(
            taxable_value="1.23456",
            rate_percent="100",
            supply_type=GSTSupplyType.INTER_STATE,
        )

        self.assertEqual(result.taxable_value, Decimal("1.2346"))
        self.assertEqual(result.igst, Decimal("1.23"))

    def test_zero_rate_returns_zero_components(self):
        result = calculate_line_gst(
            taxable_value="250.0000",
            rate_percent="0",
            supply_type=GSTSupplyType.INTRA_STATE,
        )

        self.assertEqual(result.total, Decimal("0.00"))

    def test_negative_amount_or_rate_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_line_gst(
                taxable_value="-1", rate_percent="18", supply_type="inter_state"
            )
        with self.assertRaises(ValueError):
            calculate_line_gst(
                taxable_value="1", rate_percent="-1", supply_type="inter_state"
            )

    def test_float_and_unknown_supply_type_are_rejected(self):
        with self.assertRaises(TypeError):
            calculate_line_gst(
                taxable_value=1.2, rate_percent="18", supply_type="inter_state"
            )
        with self.assertRaises(ValueError):
            calculate_line_gst(
                taxable_value="1", rate_percent="18", supply_type="export"
            )
