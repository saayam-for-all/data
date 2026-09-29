"""Unit tests for rating_type_analytics.py (issue #380)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

import rating_type_analytics as rta


REFERENCE = date(2026, 9, 26)


class RatingTypeAnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.mock_dir = Path(self.tmp.name)
        self._write_tables()
        self.env = mock.patch.dict(
            "os.environ",
            {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": str(self.mock_dir)},
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def _write_tables(self, rows=None) -> None:
        if rows is None:
            rows = [
                ["ORG1", 4, "non_profit", "CA", "2026-08-25"],
                ["ORG2", 5, "for_profit", "TX", "2026-08-26"],
                ["ORG3", 3, "non_profit", "MH", "2025-09-10"],
                ["ORG4", 3, "Non-Profit", "CA", "2025-10-01"],
                ["ORG5", 1, "for_profit", "CA", "2024-08-01"],
            ]
        pd.DataFrame(
            rows,
            columns=["org_id", "org_rating", "org_type", "state_id", "created_at"],
        ).to_csv(self.mock_dir / "organizations.csv", index=False)
        pd.DataFrame(
            [
                {"state_id": "CA", "country_id": 1},
                {"state_id": "TX", "country_id": 1},
                {"state_id": "MH", "country_id": 2},
            ]
        ).to_csv(self.mock_dir / "states.csv", index=False)
        pd.DataFrame(
            [
                {
                    "country_id": 1,
                    "country_code": "USA",
                    "country_name": "United States",
                },
                {"country_id": 2, "country_code": "IND", "country_name": "India"},
            ]
        ).to_csv(self.mock_dir / "countries.csv", index=False)

    @staticmethod
    def _body(response):
        return json.loads(response["body"])

    def test_no_custom_params_returns_exact_five_keys(self):
        result = rta.build_rating_type_response({}, today=REFERENCE)
        self.assertEqual(list(result), ["7D", "30D", "1Y", "All", "Custom"])

    def test_every_bucket_contains_exactly_two_charts(self):
        result = rta.build_rating_type_response({}, today=REFERENCE)
        for bucket in result.values():
            self.assertEqual(
                set(bucket), {"rating_distribution", "organization_mix_trend"}
            )

    def test_mix_trend_always_has_both_series(self):
        result = rta.build_rating_type_response({}, today=REFERENCE)
        for bucket in result.values():
            self.assertEqual(
                set(bucket["organization_mix_trend"]),
                {"non_profit", "for_profit"},
            )

    def test_custom_is_empty_without_custom_params(self):
        result = rta.build_rating_type_response({}, today=REFERENCE)
        self.assertEqual(result["Custom"], rta.empty_charts())

    def test_rating_custom_returns_only_rating_chart(self):
        result = rta.build_rating_type_response(
            {"rating_start_date": "2025-01-01", "rating_end_date": "2026-12-31"}
        )
        self.assertEqual(list(result), ["Custom"])
        self.assertTrue(result["Custom"]["rating_distribution"])
        self.assertEqual(
            result["Custom"]["organization_mix_trend"],
            {"non_profit": [], "for_profit": []},
        )

    def test_type_custom_returns_only_type_chart(self):
        result = rta.build_rating_type_response(
            {"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"}
        )
        self.assertEqual(list(result), ["Custom"])
        self.assertEqual(result["Custom"]["rating_distribution"], [])
        self.assertTrue(result["Custom"]["organization_mix_trend"]["non_profit"])
        # Custom type trend uses daily periods.
        period = result["Custom"]["organization_mix_trend"]["non_profit"][0]["period"]
        self.assertEqual(len(period), 10)

    def test_both_custom_ranges_populate_both_charts(self):
        result = rta.build_rating_type_response(
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
        result = rta.build_rating_type_response({"country": "IND"}, today=REFERENCE)
        total = sum(row["count"] for row in result["All"]["rating_distribution"])
        self.assertEqual(total, 1)

    def test_country_name_filter(self):
        result = rta.build_rating_type_response(
            {"country": "United States"}, today=REFERENCE
        )
        total = sum(row["count"] for row in result["All"]["rating_distribution"])
        self.assertEqual(total, 4)

    def test_rating_distribution_not_zero_filled(self):
        result = rta.build_rating_type_response({}, today=REFERENCE)
        ratings_present = {row["rating"] for row in result["All"]["rating_distribution"]}
        self.assertEqual(ratings_present, {1, 3, 4, 5})

    def test_org_type_normalizes_hyphen_and_case(self):
        result = rta.build_rating_type_response({}, today=REFERENCE)
        non_profit_last = result["All"]["organization_mix_trend"]["non_profit"][-1]
        self.assertEqual(non_profit_last["count"], 3)

    def test_mix_trend_counts_are_cumulative_and_non_decreasing(self):
        result = rta.build_rating_type_response({}, today=REFERENCE)
        for series_name in ("non_profit", "for_profit"):
            counts = [
                row["count"]
                for row in result["All"]["organization_mix_trend"][series_name]
            ]
            self.assertEqual(counts, sorted(counts))

    def test_1y_uses_monthly_periods(self):
        result = rta.build_rating_type_response({}, today=REFERENCE)
        periods = [
            row["period"]
            for row in result["1Y"]["organization_mix_trend"]["non_profit"]
        ]
        self.assertTrue(periods)
        self.assertTrue(all(len(p) == 7 for p in periods))

    def test_incomplete_date_pair_returns_400(self):
        response = rta.lambda_handler({"rating_start_date": "2026-01-01"})
        self.assertEqual(response["statusCode"], 400)

    def test_bad_date_format_returns_400(self):
        response = rta.lambda_handler(
            {"type_start_date": "01-01-2026", "type_end_date": "12-31-2026"}
        )
        self.assertEqual(response["statusCode"], 400)

    def test_start_after_end_returns_400(self):
        response = rta.lambda_handler(
            {"rating_start_date": "2026-12-31", "rating_end_date": "2026-01-01"}
        )
        self.assertEqual(response["statusCode"], 400)

    def test_empty_organizations_file_does_not_crash(self):
        self._write_tables(rows=[])
        result = rta.build_rating_type_response({}, today=REFERENCE)
        for bucket in result.values():
            self.assertEqual(bucket, rta.empty_charts())

    def test_single_row_file_does_not_crash(self):
        self._write_tables(rows=[["ORG1", 5, "non_profit", "CA", "2026-08-25"]])
        result = rta.build_rating_type_response({}, today=REFERENCE)
        self.assertEqual(
            result["All"]["rating_distribution"], [{"rating": 5, "count": 1}]
        )

    def test_api_gateway_json_body_is_supported(self):
        response = rta.lambda_handler({"body": json.dumps({"country": "USA"})})
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            set(self._body(response)), {"7D", "30D", "1Y", "All", "Custom"}
        )

    def test_7d_bucket_populated_near_reference(self):
        # ORG1/ORG2 fall inside 7D of 2026-09-26? Aug 25/26 are ~30 days prior.
        # Use a reference close to those dates.
        result = rta.build_rating_type_response({}, today=date(2026, 8, 28))
        ratings = {row["rating"] for row in result["7D"]["rating_distribution"]}
        self.assertEqual(ratings, {4, 5})


if __name__ == "__main__":
    unittest.main(verbosity=2)
