from django.http import HttpResponse
from django.test import SimpleTestCase

from apps.reports.views import _export_csv, _safe_csv_cell


class CsvSafetyTests(SimpleTestCase):
    def test_formula_prefixes_are_neutralized(self):
        for unsafe in ("=1+1", "+1+1", "-1+1", "@SUM(A1:A2)", "\tvalue"):
            with self.subTest(value=unsafe):
                self.assertEqual(_safe_csv_cell(unsafe), f"'{unsafe}")

    def test_regular_text_is_preserved(self):
        self.assertEqual(_safe_csv_cell("Northwind Ltd"), "Northwind Ltd")

    def test_large_exports_are_rejected_before_streaming(self):
        class TooManyRows:
            def __getitem__(self, key):
                return self

            def count(self):
                return 10_001

        response = _export_csv(
            filename="test.csv",
            queryset=TooManyRows(),
            headers=("name",),
            row_values=lambda item: (item.name,),
        )

        self.assertIsInstance(response, HttpResponse)
        self.assertEqual(response.status_code, 413)
