import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import rating_type_analytics as api


class RatingTypeAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.env = patch.dict(
            os.environ,
            {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": str(self.root)},
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

        pd.DataFrame(
            [
                ["ORG001", 5, "Non-Profit", "CA", "2026-09-20"],
                ["ORG002", 4, "For-profit", "NY", "2026-09-18"],
                ["ORG003", 3, "non_profit", "TX", "2026-09-10"],
                ["ORG004", 4, "for_profit", "CA", "2026-08-28"],
                ["ORG005", 2, "non_profit", "NY", "2026-08-15"],
                ["ORG006", 5, "for_profit", "TX", "2026-02-05"],
                ["ORG007", 3, "non_profit", "CA", "2026-06-30"],
                ["ORG008", 1, "for_profit", "NY", "2025-11-02"],
                ["ORG009", 5, "non_profit", "ON", "2026-09-19"],
                ["ORG010", 2, "for_profit", "NY", "2025-03-19"],
                ["ORG011", 4, "non_profit", "TX", "2024-06-30"],
                ["ORG012", 4, "non_profit", "CA", "2025-07-15"],
            ],
            columns=["org_id", "org_rating", "org_type", "state_id", "created_at"],
        ).to_csv(self.root / "organizations.csv", index=False)
        pd.DataFrame(
            [["CA", 1], ["NY", 1], ["TX", 1], ["ON", 2]],
            columns=["state_id", "country_id"],
        ).to_csv(self.root / "states.csv", index=False)
        pd.DataFrame(
            [[1, "USA", "United States"], [2, "CAN", "Canada"]],
            columns=["country_id", "country_code", "country_name"],
        ).to_csv(self.root / "countries.csv", index=False)

    def call(self, event):
        response = api.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200, response)
        return json.loads(response["body"])

    def test_no_custom_returns_exact_shape(self):
        result = api.build_analytics(api.load_data(), today="2026-09-25")
        self.assertEqual(set(result), {"7D", "30D", "1Y", "All", "Custom"})
        for bucket in result.values():
            self.assertEqual(set(bucket), {"rating_distribution", "organization_mix_trend"})
            self.assertEqual(set(bucket["organization_mix_trend"]), {"non_profit", "for_profit"})
        self.assertEqual(result["Custom"], {
            "rating_distribution": [],
            "organization_mix_trend": {"non_profit": [], "for_profit": []},
        })

    def test_rating_custom_only_returns_custom(self):
        result = self.call({
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-06-30",
        })
        self.assertEqual(set(result), {"Custom"})
        self.assertEqual(result["Custom"]["rating_distribution"], [
            {"rating": 3, "count": 1},
            {"rating": 5, "count": 1},
        ])
        self.assertEqual(result["Custom"]["organization_mix_trend"], {
            "non_profit": [], "for_profit": [],
        })

    def test_type_custom_only_returns_cumulative_sparse_series(self):
        result = self.call({
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-12-31",
        })
        self.assertEqual(set(result), {"Custom"})
        mix = result["Custom"]["organization_mix_trend"]
        self.assertEqual(result["Custom"]["rating_distribution"], [])
        self.assertEqual(mix["non_profit"], [{"period": "2025-07-15", "count": 2}])

    def test_both_custom_ranges_are_independent(self):
        result = self.call({
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-06-30",
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-12-31",
        })
        custom = result["Custom"]
        self.assertEqual(custom["rating_distribution"], [
            {"rating": 3, "count": 1},
            {"rating": 5, "count": 1},
        ])
        self.assertEqual(custom["organization_mix_trend"]["for_profit"], [
            {"period": "2025-03-19", "count": 1},
            {"period": "2025-11-02", "count": 2},
        ])

    def test_country_filter_accepts_code_and_name(self):
        usa_by_code = self.call({"country": "USA"})
        usa_by_name = self.call({"country": "United States"})
        canada = self.call({"country": "CAN"})
        self.assertEqual(
            usa_by_code["All"]["rating_distribution"],
            usa_by_name["All"]["rating_distribution"],
        )
        self.assertEqual(canada["All"]["rating_distribution"], [{"rating": 5, "count": 1}])

    def test_country_name_only_lookup_is_supported(self):
        pd.DataFrame(
            [[1, "United States"], [2, "Canada"]],
            columns=["country_id", "country_name"],
        ).to_csv(self.root / "countries.csv", index=False)
        result = self.call({"country": "Canada"})
        self.assertEqual(result["All"]["rating_distribution"], [{"rating": 5, "count": 1}])

    def test_daily_and_monthly_period_granularity(self):
        result = api.build_analytics(api.load_data(), today="2026-09-25")
        daily = result["30D"]["organization_mix_trend"]
        monthly = result["1Y"]["organization_mix_trend"]
        self.assertTrue(all(len(item["period"]) == 10 for series in daily.values() for item in series))
        self.assertTrue(all(len(item["period"]) == 7 for series in monthly.values() for item in series))

    def test_cumulative_type_counts_are_non_decreasing(self):
        result = api.build_analytics(api.load_data(), today="2026-09-25")
        for series in result["All"]["organization_mix_trend"].values():
            counts = [item["count"] for item in series]
            self.assertEqual(counts, sorted(counts))

    def test_api_gateway_string_body_is_supported(self):
        result = self.call({"body": json.dumps({"country": "USA"})})
        self.assertIn("All", result)

    def test_invalid_or_incomplete_ranges_return_400(self):
        invalid_events = [
            {"rating_start_date": "2026-01-01"},
            {"type_end_date": "2026-01-01"},
            {"rating_start_date": "bad", "rating_end_date": "2026-01-01"},
            {"type_start_date": "2026-02-30", "type_end_date": "2026-03-01"},
            {"rating_start_date": "2026-03-01", "rating_end_date": "2026-02-01"},
            {"type_start_date": "2026-1-01", "type_end_date": "2026-02-01"},
        ]
        for event in invalid_events:
            with self.subTest(event=event):
                response = api.lambda_handler(event, None)
                self.assertEqual(response["statusCode"], 400)
                self.assertEqual(set(json.loads(response["body"])), {"error"})

    def test_empty_and_single_row_data_do_not_crash(self):
        organizations = pd.read_csv(self.root / "organizations.csv")
        organizations.head(0).to_csv(self.root / "organizations.csv", index=False)
        empty = self.call({})
        self.assertEqual(empty["All"]["rating_distribution"], [])
        self.assertEqual(empty["All"]["organization_mix_trend"], {
            "non_profit": [], "for_profit": [],
        })

        organizations.head(1).to_csv(self.root / "organizations.csv", index=False)
        single = self.call({})
        self.assertEqual(single["All"]["rating_distribution"], [{"rating": 5, "count": 1}])

    def test_invalid_org_type_is_reported_as_data_error(self):
        organizations = pd.read_csv(self.root / "organizations.csv")
        organizations.loc[0, "org_type"] = "unknown_type"
        organizations.to_csv(self.root / "organizations.csv", index=False)
        with self.assertLogs(api.LOGGER, level="ERROR"):
            response = api.lambda_handler({}, None)
        self.assertEqual(response["statusCode"], 500)


if __name__ == "__main__":
    unittest.main()
