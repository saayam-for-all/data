import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import growth_location_analytics as api


class GrowthLocationTests(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        env = patch.dict(os.environ, MOCK_DATA_DIR=str(self.root))
        env.start()
        self.addCleanup(env.stop)
        self.organizations = pd.DataFrame([
            [1, 1, "Austin", True, "2024-01-01"],
            [2, 2, "Miami", False, "2025-12-01"],
            [3, 1, "Austin", True, "2026-06-23"],
            [4, 2, "Miami", False, "2026-06-24"],
            [5, 3, "Delhi", True, "2026-06-30"],
            [6, 4, "Toronto", True, "2026-07-01"],
        ], columns=["org_id", "state_id", "city_name", "is_collaborator", "created_at"])
        self.organizations.to_csv(self.root / "organizations.csv", index=False)
        pd.DataFrame([
            [1, "Texas", 1], [2, "Florida", 1], [3, "Delhi", 2], [4, "Ontario", 3],
        ], columns=["state_id", "state_name", "country_id"]).to_csv(self.root / "states.csv", index=False)
        pd.DataFrame([[1, "USA"], [2, "IND"], [3, "CAN"]], columns=["country_id", "country_code"]).to_csv(self.root / "countries.csv", index=False)

    def call(self, payload):
        result = api.lambda_handler(payload, None)
        self.assertEqual(result["statusCode"], 200, result)
        return json.loads(result["body"])

    def test_shape_and_empty_custom(self):
        result = self.call({})
        self.assertEqual(set(result), {"7D", "30D", "1Y", "All", "Custom"})
        for bucket in result.values():
            self.assertEqual(set(bucket), {"growth_trend", "organizations_by_location"})
            self.assertEqual(set(bucket["growth_trend"]), {"total_organizations", "collaborators"})
        self.assertEqual(result["Custom"], {
            "growth_trend": {"total_organizations": [], "collaborators": []},
            "organizations_by_location": [],
        })
        self.assertEqual(result["All"]["growth_trend"]["total_organizations"][-1]["count"], 6)

    def test_independent_custom_ranges(self):
        growth = {"start_date": "2026-06-24", "end_date": "2026-06-30"}
        location = {"location_start_date": "2025-01-01", "location_end_date": "2025-12-31"}
        expected_growth = {
            "total_organizations": [{"period": "2026-06-24", "count": 4}, {"period": "2026-06-30", "count": 5}],
            "collaborators": [{"period": "2026-06-24", "count": 0}, {"period": "2026-06-30", "count": 1}],
        }
        result = self.call(growth)["Custom"]
        self.assertEqual(result["growth_trend"], expected_growth)
        self.assertEqual(result["organizations_by_location"], [])
        result = self.call(location)["Custom"]
        self.assertEqual(result["growth_trend"]["total_organizations"], [])
        self.assertEqual(result["organizations_by_location"], [{"country": "USA", "count": 1}])
        combined = self.call({"body": json.dumps({**growth, **location})})
        self.assertEqual(combined["Custom"]["growth_trend"], expected_growth)
        self.assertEqual(combined["Custom"]["organizations_by_location"], result["organizations_by_location"])

    def test_fixed_windows_and_sparse_granularity(self):
        result = api.build_analytics(api.load_data(), today="2026-06-30")
        self.assertEqual(result["7D"]["growth_trend"]["total_organizations"], [
            {"period": "2026-06-24", "count": 4}, {"period": "2026-06-30", "count": 5},
        ])
        self.assertEqual(result["30D"]["growth_trend"]["collaborators"], [
            {"period": "2026-06-23", "count": 1}, {"period": "2026-06-24", "count": 0}, {"period": "2026-06-30", "count": 1},
        ])
        self.assertEqual(result["1Y"]["growth_trend"], {
            "total_organizations": [{"period": "2025-12", "count": 2}, {"period": "2026-06", "count": 5}],
            "collaborators": [{"period": "2025-12", "count": 0}, {"period": "2026-06", "count": 2}],
        })
        self.assertEqual(result["7D"]["organizations_by_location"], [{"country": "IND", "count": 1}, {"country": "USA", "count": 1}])
        empty = api.build_analytics(api.load_data(), today="2023-01-01")
        self.assertEqual(empty["7D"]["growth_trend"]["total_organizations"], [])

    def test_invalid_ranges_and_bodies(self):
        for prefix in ("", "location_"):
            for start, end in [("bad", "2026-01-01"), ("2026-02-30", "2026-03-01"), ("2026-02-01", "2026-01-01"), ("2026-1-01", "2026-02-01"), (None, "2026-01-01")]:
                with self.subTest(prefix=prefix, start=start):
                    result = api.lambda_handler({prefix + "start_date": start, prefix + "end_date": end}, None)
                    self.assertEqual(result["statusCode"], 400)
                    self.assertEqual(set(json.loads(result["body"])), {"error"})
            self.assertEqual(api.lambda_handler({prefix + "start_date": "2026-01-01"}, None)["statusCode"], 400)
        for body in ("{", "[]", "null", 5):
            self.assertEqual(api.lambda_handler({"body": body}, None)["statusCode"], 400)

    def test_country_rollup_and_top_four(self):
        result = self.call({})["All"]["organizations_by_location"]
        self.assertEqual(result, [{"country": "USA", "count": 4}, {"country": "CAN", "count": 1}, {"country": "IND", "count": 1}])
        data = api.load_data()
        data["country_code"] = ["USA", "IND", "CAN", "GBR", "FRA", "DEU"]
        self.assertEqual(api.locations(data, None), [{"country": code, "count": 1} for code in ["CAN", "DEU", "FRA", "GBR"]])
        data["country_code"] = "USA"
        self.assertEqual(api.locations(data, None), [{"country": "USA", "count": 6}])

    def test_empty_and_single_row_csv(self):
        for size in (0, 1):
            with self.subTest(size=size):
                self.organizations.head(size).to_csv(self.root / "organizations.csv", index=False)
                result = self.call({})
                totals = result["All"]["growth_trend"]["total_organizations"]
                self.assertEqual(totals, [] if size == 0 else [{"period": "2024-01", "count": 1}])

    def test_inclusive_end_day_and_partial_month(self):
        data = api.load_data()
        data.loc[4, "created_at"] = pd.Timestamp("2026-06-30T23:59:59Z")
        window = api.parse_range({"start_date": "2026-06-30", "end_date": "2026-06-30"}, "start_date", "end_date")
        self.assertEqual(api.growth(data, window)["total_organizations"], [{"period": "2026-06-30", "count": 5}])
        partial = api.build_analytics(data, today="2026-06-24")
        self.assertEqual(partial["1Y"]["growth_trend"]["total_organizations"][-1], {"period": "2026-06", "count": 4})

    def test_leap_year_window(self):
        data = api.load_data().iloc[:3].copy()
        data["created_at"] = pd.to_datetime(["2023-02-28", "2023-03-01", "2024-02-29"], utc=True)
        result = api.build_analytics(data, today="2024-02-29")
        self.assertEqual(result["1Y"]["growth_trend"]["total_organizations"], [
            {"period": "2023-03", "count": 2}, {"period": "2024-02", "count": 3},
        ])

    def test_csv_boolean_flags(self):
        self.organizations["is_collaborator"] = ["true", "false", "1", "0", "t", "f"]
        self.organizations.to_csv(self.root / "organizations.csv", index=False)
        self.assertEqual(api.load_data().is_collaborator.tolist(), [True, False, True, False, True, False])

    def test_mixed_iso_dates_in_csv(self):
        self.organizations.loc[4, "created_at"] = "2026-06-30T23:59:59Z"
        self.organizations.loc[5, "created_at"] = "2026-07-01T00:30:00+01:00"
        self.organizations.to_csv(self.root / "organizations.csv", index=False)
        result = self.call({"start_date": "2026-06-30", "end_date": "2026-06-30"})
        self.assertEqual(result["Custom"]["growth_trend"]["total_organizations"], [
            {"period": "2026-06-30", "count": 6},
        ])
        self.assertEqual(result["Custom"]["growth_trend"]["collaborators"], [
            {"period": "2026-06-30", "count": 2},
        ])

    def test_reference_time_is_normalized_to_utc_day(self):
        data = api.load_data()
        expected = api.build_analytics(data, today="2026-06-30")
        for today in ("2026-06-30T15:00:00", pd.Timestamp("2026-07-01T00:30:00+01:00")):
            self.assertEqual(api.build_analytics(data, today=today), expected)

    def test_data_errors_return_generic_server_error(self):
        for error in (FileNotFoundError("private/path"), ValueError("invalid CSV")):
            with self.subTest(error=type(error).__name__):
                with patch.object(api, "load_data", side_effect=error), self.assertLogs(level="ERROR"):
                    result = api.lambda_handler({}, None)
                self.assertEqual(result["statusCode"], 500)
                self.assertEqual(json.loads(result["body"]), {"error": "Unable to load analytics data"})

    def test_duplicate_lookup_rows_do_not_inflate_counts(self):
        states = pd.read_csv(self.root / "states.csv")
        pd.concat([states, states.iloc[:1]]).to_csv(self.root / "states.csv", index=False)
        with self.assertLogs(level="ERROR"):
            result = api.lambda_handler({}, None)
        self.assertEqual(result["statusCode"], 500)


if __name__ == "__main__":
    unittest.main()
