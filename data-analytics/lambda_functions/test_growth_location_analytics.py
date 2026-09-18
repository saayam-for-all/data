
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import growth_location_analytics as api


class GrowthLocationAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)

        countries = pd.DataFrame(
            [
                ["1", "USA"],
                ["2", "IND"],
                ["3", "CAN"],
                ["4", "GBR"],
                ["5", "AUS"],
            ],
            columns=["country_id", "country_code"],
        )

        states = pd.DataFrame(
            [
                ["TX", "Texas", "1"],
                ["FL", "Florida", "1"],
                ["CA", "California", "1"],
                ["MH", "Maharashtra", "2"],
                ["ON", "Ontario", "3"],
                ["ENG", "England", "4"],
                ["NSW", "New South Wales", "5"],
            ],
            columns=["state_id", "state_name", "country_id"],
        )

        organizations = pd.DataFrame(
            [
                ["ORG001", "TX", "Austin", "TRUE", "2024-01-15 10:00:00"],
                ["ORG002", "CA", "Los Angeles", "FALSE", "2025-09-20 09:00:00"],
                ["ORG003", "FL", "Miami", "TRUE", "2025-10-12 09:00:00"],
                ["ORG004", "MH", "Pune", "TRUE", "2026-01-10 08:00:00"],
                ["ORG005", "ON", "Toronto", "FALSE", "2026-01-11 08:00:00"],
                ["ORG006", "ENG", "London", "TRUE", "2026-02-10 08:00:00"],
                ["ORG007", "NSW", "Sydney", "FALSE", "2026-03-10 08:00:00"],
                ["ORG008", "MH", "Mumbai", "TRUE", "2026-06-05 08:00:00"],
                ["ORG009", "TX", "Dallas", "FALSE", "2026-08-25 08:00:00"],
                ["ORG010", "CA", "San Diego", "TRUE", "2026-09-12 08:00:00"],
                ["ORG011", "MH", "Nagpur", "TRUE", "2026-09-13 08:00:00"],
                ["ORG012", "ON", "Ottawa", "FALSE", "2026-09-14 08:00:00"],
                ["ORG013", "ENG", "Manchester", "TRUE", "2026-09-16 08:00:00"],
                ["ORG014", "TX", "Houston", "FALSE", "2026-09-17 08:00:00"],
                ["ORG015", "NSW", "Newcastle", "TRUE", "2026-09-18 08:00:00"],
            ],
            columns=[
                "org_id",
                "state_id",
                "city_name",
                "is_collaborator",
                "created_at",
            ],
        )

        countries.to_csv(self.data_dir / "countries.csv", index=False)
        states.to_csv(self.data_dir / "states.csv", index=False)
        organizations.to_csv(self.data_dir / "organizations.csv", index=False)

        self.env_patch = patch.dict(
            os.environ,
            {"MOCK_DATA_DIR": str(self.data_dir)},
        )
        self.env_patch.start()

        self.today_patch = patch(
            "growth_location_analytics.get_today",
            return_value=pd.Timestamp("2026-09-18"),
        )
        self.today_patch.start()

    def tearDown(self):
        self.today_patch.stop()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_no_body_has_exact_five_top_level_keys(self):
        response = api.lambda_handler({}, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            list(response["body"].keys()),
            ["7D", "30D", "1Y", "All", "Custom"],
        )

    def test_each_bucket_has_exact_required_keys(self):
        body = api.lambda_handler({}, None)["body"]

        for bucket in ["7D", "30D", "1Y", "All", "Custom"]:
            self.assertEqual(
                set(body[bucket].keys()),
                {"growth_trend", "organizations_by_location"},
            )
            self.assertEqual(
                set(body[bucket]["growth_trend"].keys()),
                {"total_organizations", "collaborators"},
            )

    def test_custom_is_empty_when_no_dates_are_supplied(self):
        custom = api.lambda_handler({}, None)["body"]["Custom"]

        self.assertEqual(
            custom["growth_trend"],
            {"total_organizations": [], "collaborators": []},
        )
        self.assertEqual(custom["organizations_by_location"], [])

    def test_growth_custom_range_populates_only_growth(self):
        event = {
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
        }

        custom = api.lambda_handler(event, None)["body"]["Custom"]

        self.assertTrue(custom["growth_trend"]["total_organizations"])
        self.assertEqual(custom["organizations_by_location"], [])

    def test_location_custom_range_populates_only_location(self):
        event = {
            "location_start_date": "2026-01-01",
            "location_end_date": "2026-06-30",
        }

        custom = api.lambda_handler(event, None)["body"]["Custom"]

        self.assertEqual(
            custom["growth_trend"],
            {"total_organizations": [], "collaborators": []},
        )
        self.assertTrue(custom["organizations_by_location"])

    def test_both_custom_ranges_work_independently(self):
        event = {
            "start_date": "2026-01-01",
            "end_date": "2026-02-28",
            "location_start_date": "2026-06-01",
            "location_end_date": "2026-06-30",
        }

        custom = api.lambda_handler(event, None)["body"]["Custom"]

        growth_periods = [
            row["period"]
            for row in custom["growth_trend"]["total_organizations"]
        ]
        location_countries = {
            row["country"]
            for row in custom["organizations_by_location"]
        }

        self.assertIn("2026-01-10", growth_periods)
        self.assertEqual(location_countries, {"IND"})

    def test_partial_growth_date_pair_returns_400(self):
        response = api.lambda_handler(
            {"start_date": "2026-01-01"},
            None,
        )

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(set(response["body"].keys()), {"error"})

    def test_partial_location_date_pair_returns_400(self):
        response = api.lambda_handler(
            {"location_end_date": "2026-01-31"},
            None,
        )

        self.assertEqual(response["statusCode"], 400)

    def test_invalid_date_format_returns_400(self):
        response = api.lambda_handler(
            {
                "start_date": "2026/01/01",
                "end_date": "2026-01-31",
            },
            None,
        )

        self.assertEqual(response["statusCode"], 400)

    def test_start_after_end_returns_400(self):
        response = api.lambda_handler(
            {
                "start_date": "2026-06-30",
                "end_date": "2026-01-01",
            },
            None,
        )

        self.assertEqual(response["statusCode"], 400)

    def test_total_organizations_is_all_time_cumulative(self):
        event = {
            "start_date": "2026-01-01",
            "end_date": "2026-02-28",
        }

        totals = api.lambda_handler(event, None)["body"]["Custom"][
            "growth_trend"
        ]["total_organizations"]

        self.assertEqual(
            totals,
            [
                {"period": "2026-01-10", "count": 4},
                {"period": "2026-01-11", "count": 5},
                {"period": "2026-02-10", "count": 6},
            ],
        )

    def test_collaborators_are_per_period_not_cumulative(self):
        event = {
            "start_date": "2026-01-01",
            "end_date": "2026-02-28",
        }

        collaborators = api.lambda_handler(event, None)["body"]["Custom"][
            "growth_trend"
        ]["collaborators"]

        self.assertEqual(
            collaborators,
            [
                {"period": "2026-01-10", "count": 1},
                {"period": "2026-01-11", "count": 0},
                {"period": "2026-02-10", "count": 1},
            ],
        )

    def test_growth_series_share_same_periods(self):
        trend = api.lambda_handler({}, None)["body"]["1Y"]["growth_trend"]

        total_periods = [
            row["period"] for row in trend["total_organizations"]
        ]
        collaborator_periods = [
            row["period"] for row in trend["collaborators"]
        ]

        self.assertEqual(total_periods, collaborator_periods)

    def test_7d_and_30d_use_daily_periods(self):
        body = api.lambda_handler({}, None)["body"]

        for bucket in ["7D", "30D"]:
            for row in body[bucket]["growth_trend"]["total_organizations"]:
                self.assertRegex(row["period"], r"^\d{4}-\d{2}-\d{2}$")

    def test_1y_and_all_use_monthly_periods(self):
        body = api.lambda_handler({}, None)["body"]

        for bucket in ["1Y", "All"]:
            for row in body[bucket]["growth_trend"]["total_organizations"]:
                self.assertRegex(row["period"], r"^\d{4}-\d{2}$")

    def test_sparse_periods_are_not_zero_filled(self):
        periods = [
            row["period"]
            for row in api.lambda_handler({}, None)["body"]["7D"][
                "growth_trend"
            ]["total_organizations"]
        ]

        self.assertNotIn("2026-09-15", periods)

    def test_location_is_aggregated_by_country_and_limited_to_four(self):
        locations = api.lambda_handler({}, None)["body"]["All"][
            "organizations_by_location"
        ]

        countries = {row["country"] for row in locations}

        self.assertLessEqual(len(locations), 4)
        self.assertIn("USA", countries)
        self.assertNotIn("TX", countries)
        self.assertNotIn("CA", countries)

        for row in locations:
            self.assertNotIn("percentage", row)
            self.assertNotEqual(row["country"], "Other")

    def test_all_last_total_equals_dataset_row_count(self):
        body = api.lambda_handler({}, None)["body"]

        last_total = body["All"]["growth_trend"]["total_organizations"][-1][
            "count"
        ]

        self.assertEqual(last_total, 15)

    def test_empty_organizations_file_does_not_crash(self):
        pd.DataFrame(
            columns=[
                "org_id",
                "state_id",
                "city_name",
                "is_collaborator",
                "created_at",
            ]
        ).to_csv(self.data_dir / "organizations.csv", index=False)

        response = api.lambda_handler({}, None)

        self.assertEqual(response["statusCode"], 200)

        for bucket in ["7D", "30D", "1Y", "All", "Custom"]:
            self.assertEqual(
                response["body"][bucket]["growth_trend"],
                {"total_organizations": [], "collaborators": []},
            )
            self.assertEqual(
                response["body"][bucket]["organizations_by_location"],
                [],
            )

    def test_one_row_organizations_file_does_not_crash(self):
        pd.DataFrame(
            [
                [
                    "ONLY1",
                    "TX",
                    "Austin",
                    "TRUE",
                    "2026-09-18 08:00:00",
                ]
            ],
            columns=[
                "org_id",
                "state_id",
                "city_name",
                "is_collaborator",
                "created_at",
            ],
        ).to_csv(self.data_dir / "organizations.csv", index=False)

        response = api.lambda_handler({}, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            response["body"]["All"]["growth_trend"]["total_organizations"],
            [{"period": "2026-09", "count": 1}],
        )

    def test_api_gateway_string_body_is_supported(self):
        event = {
            "body": (
                '{"start_date":"2026-01-01",'
                '"end_date":"2026-01-31"}'
            )
        }

        response = api.lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(
            response["body"]["Custom"]["growth_trend"][
                "total_organizations"
            ]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
