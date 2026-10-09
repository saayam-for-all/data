"""Tests for the Rating & Type Analytics Lambda (issue #380)."""

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd


MODULE_PATH = (
    Path(__file__).parents[1] / "org_rating_type_analytics.py"
)
SPEC = importlib.util.spec_from_file_location("org_rating_type_analytics", MODULE_PATH)
ANALYTICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYTICS)


class RatingTypeAnalyticsTests(unittest.TestCase):
    """Exercise response shapes, filters, calculations, and edge cases."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mock_dir = Path(self.temp_dir.name)
        self.previous_mock_dir = os.environ.get("MOCK_DATA_DIR")
        self.previous_use_mock = os.environ.get("USE_MOCK_DATA")
        os.environ["MOCK_DATA_DIR"] = str(self.mock_dir)
        os.environ["USE_MOCK_DATA"] = "true"
        self._write_standard_tables()

    def tearDown(self):
        if self.previous_mock_dir is None:
            os.environ.pop("MOCK_DATA_DIR", None)
        else:
            os.environ["MOCK_DATA_DIR"] = self.previous_mock_dir
        if self.previous_use_mock is None:
            os.environ.pop("USE_MOCK_DATA", None)
        else:
            os.environ["USE_MOCK_DATA"] = self.previous_use_mock
        self.temp_dir.cleanup()

    def _write_standard_tables(self, rows=None):
        columns = ["org_id", "org_rating", "org_type", "state_id", "created_at"]

        if rows is None:
            rows = [
                ["ORG1", 4, "non_profit", "CA", "2026-08-25"],
                ["ORG2", 5, "for_profit", "TX", "2026-08-26"],
                ["ORG3", 3, "non_profit", "MH", "2025-09-10"],
                ["ORG4", 3, "Non-Profit", "CA", "2025-10-01"],
                ["ORG5", 1, "for_profit", "CA", "2024-08-01"],
            ]

        pd.DataFrame(rows, columns=columns).to_csv(
            self.mock_dir / "organizations.csv", index=False
        )
        pd.DataFrame(
            [
                {"state_id": "CA", "country_id": 1},
                {"state_id": "TX", "country_id": 1},
                {"state_id": "MH", "country_id": 2},
            ]
        ).to_csv(self.mock_dir / "states.csv", index=False)
        pd.DataFrame(
            [
                {"country_id": 1, "country_code": "USA", "country_name": "UNITED_STATES"},
                {"country_id": 2, "country_code": "IND", "country_name": "INDIA"},
            ]
        ).to_csv(self.mock_dir / "countries.csv", index=False)

    @staticmethod
    def _body(response):
        return json.loads(response["body"])

    def test_no_custom_params_returns_exact_five_keys(self):
        result = ANALYTICS.build_response({}, today=date(2026, 9, 26))
        self.assertEqual(list(result), ["7D", "30D", "1Y", "All", "Custom"])

    def test_every_bucket_contains_exactly_two_charts(self):
        result = ANALYTICS.build_response({}, today=date(2026, 9, 26))
        for bucket in result.values():
            self.assertEqual(
                set(bucket), {"rating_distribution", "organization_mix_trend"}
            )

    def test_mix_trend_always_has_both_series(self):
        result = ANALYTICS.build_response({}, today=date(2026, 9, 26))
        for bucket in result.values():
            self.assertEqual(
                set(bucket["organization_mix_trend"]), {"non_profit", "for_profit"}
            )

    def test_custom_is_empty_without_custom_params(self):
        result = ANALYTICS.build_response({}, today=date(2026, 9, 26))
        self.assertEqual(result["Custom"], ANALYTICS._empty_charts())

    def test_rating_custom_returns_only_rating_chart(self):
        result = ANALYTICS.build_response(
            {"rating_start_date": "2025-01-01", "rating_end_date": "2026-12-31"}
        )
        self.assertEqual(list(result), ["Custom"])
        self.assertTrue(result["Custom"]["rating_distribution"])
        self.assertEqual(
            result["Custom"]["organization_mix_trend"], {"non_profit": [], "for_profit": []}
        )

    def test_type_custom_returns_only_type_chart(self):
        result = ANALYTICS.build_response(
            {"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"}
        )
        self.assertEqual(list(result), ["Custom"])
        self.assertEqual(result["Custom"]["rating_distribution"], [])
        self.assertTrue(result["Custom"]["organization_mix_trend"]["non_profit"])

    def test_both_custom_ranges_populate_both_charts(self):
        result = ANALYTICS.build_response(
            {
                "rating_start_date": "2024-01-01",
                "rating_end_date": "2026-12-31",
                "type_start_date": "2024-01-01",
                "type_end_date": "2026-12-31",
            }
        )
        self.assertEqual(list(result), ["Custom"])
        self.assertTrue(result["Custom"]["rating_distribution"])
        self.assertTrue(result["Custom"]["organization_mix_trend"]["non_profit"])
        self.assertTrue(result["Custom"]["organization_mix_trend"]["for_profit"])

    def test_country_code_filter(self):
        result = ANALYTICS.build_response({"country": "IND"})
        total = sum(row["count"] for row in result["All"]["rating_distribution"])
        self.assertEqual(total, 1)

    def test_country_name_filter_accepts_spaces(self):
        result = ANALYTICS.build_response({"country": "United States"})
        total = sum(row["count"] for row in result["All"]["rating_distribution"])
        self.assertEqual(total, 4)

    def test_rating_distribution_not_zero_filled(self):
        result = ANALYTICS.build_response({}, today=date(2026, 9, 26))
        ratings_present = {row["rating"] for row in result["All"]["rating_distribution"]}
        self.assertEqual(ratings_present, {1, 3, 4, 5})

    def test_org_type_normalizes_hyphen_and_case(self):
        result = ANALYTICS.build_response({}, today=date(2026, 9, 26))
        non_profit_last = result["All"]["organization_mix_trend"]["non_profit"][-1]
        self.assertEqual(non_profit_last["count"], 3)

    def test_mix_trend_counts_are_cumulative_and_non_decreasing(self):
        result = ANALYTICS.build_response({}, today=date(2026, 9, 26))
        series = result["All"]["organization_mix_trend"]["for_profit"]
        counts = [row["count"] for row in series]
        self.assertEqual(counts, sorted(counts))

    def test_incomplete_date_pair_returns_400(self):
        response = ANALYTICS.lambda_handler({"rating_start_date": "2026-01-01"})
        self.assertEqual(response["statusCode"], 400)

    def test_bad_date_format_returns_400(self):
        response = ANALYTICS.lambda_handler(
            {"type_start_date": "01-01-2026", "type_end_date": "12-31-2026"}
        )
        self.assertEqual(response["statusCode"], 400)

    def test_start_after_end_returns_400(self):
        response = ANALYTICS.lambda_handler(
            {"rating_start_date": "2026-12-31", "rating_end_date": "2026-01-01"}
        )
        self.assertEqual(response["statusCode"], 400)

    def test_empty_organizations_file_does_not_crash(self):
        self._write_standard_tables(rows=[])
        result = ANALYTICS.build_response({}, today=date(2026, 9, 26))
        for bucket in result.values():
            self.assertEqual(bucket, ANALYTICS._empty_charts())

    def test_single_row_file_does_not_crash(self):
        row = [["ORG1", 5, "non_profit", "CA", "2026-08-25"]]
        self._write_standard_tables(rows=row)
        result = ANALYTICS.build_response({}, today=date(2026, 9, 26))
        self.assertEqual(result["All"]["rating_distribution"], [{"rating": 5, "count": 1}])

    def test_api_gateway_json_body_is_supported(self):
        response = ANALYTICS.lambda_handler(
            {"body": json.dumps({"country": "USA"})}
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(set(self._body(response)), {"7D", "30D", "1Y", "All", "Custom"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
