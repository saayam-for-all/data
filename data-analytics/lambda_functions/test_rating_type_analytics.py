"""CSV-backed and cursor-based tests for the Issue #380 Lambda."""

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import rating_type_analytics as api


ORGANIZATIONS = [
    ("1", "5", "non_profit", "VA", "2026-09-26 09:00:00"),
    ("2", "4", "for_profit", "VA", "2026-09-25 10:00:00"),
    ("3", "3", "non_profit", "VA", "2026-08-31 11:00:00"),
    ("4", "2", "for_profit", "ON", "2026-08-01 12:00:00"),
    ("5", "1", "non_profit", "VA", "2025-11-01 13:00:00"),
    ("6", "5", "for_profit", "VA", "2024-02-01 14:00:00"),
]


class RatingTypeAnalyticsTests(unittest.TestCase):
    """Exercise the public handler with actual local CSV files."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(
            os.environ,
            {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": self.directory.name},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.today = patch.object(api, "utc_today", return_value=date(2026, 9, 26))
        self.today.start()
        self.addCleanup(self.today.stop)
        self.write_organizations(ORGANIZATIONS)
        pd.DataFrame(
            [("VA", "1"), ("ON", "2")], columns=["state_id", "country_id"],
        ).to_csv(Path(self.directory.name, "states.csv"), index=False)
        pd.DataFrame(
            [("1", "USA", "United States"), ("2", "CAN", "Canada")],
            columns=["country_id", "country_code", "country_name"],
        ).to_csv(Path(self.directory.name, "countries.csv"), index=False)

    def write_organizations(self, rows):
        """Replace the CSV to test normal, empty, and one-row inputs."""
        pd.DataFrame(
            rows,
            columns=["org_id", "org_rating", "org_type", "state_id", "created_at"],
        ).to_csv(Path(self.directory.name, "organizations.csv"), index=False)

    def invoke(self, event=None):
        """Run the Lambda and decode its API Gateway response body."""
        result = api.lambda_handler(event if event is not None else {}, None)
        return result["statusCode"], json.loads(result["body"])

    def test_no_body_has_exactly_five_buckets_and_empty_custom(self):
        status, body = self.invoke()
        self.assertEqual(status, 200)
        self.assertEqual(list(body), ["7D", "30D", "1Y", "All", "Custom"])
        self.assertEqual(body["Custom"], api.empty_bucket())
        for bucket in body.values():
            self.assertEqual(set(bucket), {"rating_distribution", "organization_mix_trend"})
            self.assertEqual(set(bucket["organization_mix_trend"]), set(api.SERIES))

    def test_country_code_and_name_filter_both_charts(self):
        for country in ("CAN", "canada"):
            with self.subTest(country=country):
                status, body = self.invoke({"country": country})
                self.assertEqual(status, 200)
                self.assertEqual(body["All"]["rating_distribution"], [{"rating": 2, "count": 1}])
                self.assertEqual(body["All"]["organization_mix_trend"]["non_profit"], [])
                self.assertEqual(
                    body["All"]["organization_mix_trend"]["for_profit"],
                    [{"period": "2026-08", "count": 1}],
                )

    def test_rating_only_custom_is_categorical_and_sparse(self):
        status, body = self.invoke({
            "rating_start_date": "2026-09-25", "rating_end_date": "2026-09-26",
        })
        self.assertEqual(status, 200)
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"], [
            {"rating": 4, "count": 1}, {"rating": 5, "count": 1},
        ])
        self.assertEqual(body["Custom"]["organization_mix_trend"], api.empty_bucket()["organization_mix_trend"])

    def test_type_only_custom_is_daily_cumulative_and_sparse(self):
        status, body = self.invoke({
            "type_start_date": "2026-09-25", "type_end_date": "2026-09-26",
        })
        self.assertEqual(status, 200)
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"], [])
        self.assertEqual(body["Custom"]["organization_mix_trend"], {
            "non_profit": [{"period": "2026-09-26", "count": 3}],
            "for_profit": [{"period": "2026-09-25", "count": 3}],
        })

    def test_both_custom_pairs_use_independent_ranges(self):
        status, body = self.invoke({"body": json.dumps({
            "country": "USA",
            "rating_start_date": "2026-08-31", "rating_end_date": "2026-09-01",
            "type_start_date": "2026-09-25", "type_end_date": "2026-09-26",
        })})
        self.assertEqual(status, 200)
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"], [{"rating": 3, "count": 1}])
        self.assertEqual(body["Custom"]["organization_mix_trend"]["non_profit"], [
            {"period": "2026-09-26", "count": 3},
        ])

    def test_fixed_mix_counts_include_pre_window_baseline(self):
        status, body = self.invoke()
        self.assertEqual(status, 200)
        self.assertEqual(body["7D"]["rating_distribution"], [
            {"rating": 4, "count": 1}, {"rating": 5, "count": 1},
        ])
        self.assertEqual(body["7D"]["organization_mix_trend"], {
            "non_profit": [{"period": "2026-09-26", "count": 3}],
            "for_profit": [{"period": "2026-09-25", "count": 3}],
        })
        self.assertEqual(body["30D"]["organization_mix_trend"]["non_profit"], [
            {"period": "2026-08-31", "count": 2},
            {"period": "2026-09-26", "count": 3},
        ])
        self.assertEqual(body["1Y"]["organization_mix_trend"]["non_profit"], [
            {"period": "2025-11", "count": 1},
            {"period": "2026-08", "count": 2},
            {"period": "2026-09", "count": 3},
        ])
        self.assertEqual(body["All"]["organization_mix_trend"]["for_profit"], [
            {"period": "2024-02", "count": 1},
            {"period": "2026-08", "count": 2},
            {"period": "2026-09", "count": 3},
        ])

    def test_empty_and_single_row_csvs(self):
        self.write_organizations([])
        status, body = self.invoke()
        self.assertEqual(status, 200)
        self.assertTrue(all(bucket == api.empty_bucket() for bucket in body.values()))

        self.write_organizations(ORGANIZATIONS[:1])
        status, body = self.invoke()
        self.assertEqual(status, 200)
        self.assertEqual(body["All"]["rating_distribution"], [{"rating": 5, "count": 1}])

    def test_unknown_country_returns_empty_charts(self):
        status, body = self.invoke({"country": "UNKNOWN"})
        self.assertEqual(status, 200)
        self.assertTrue(all(bucket == api.empty_bucket() for bucket in body.values()))

    def test_invalid_ranges_and_country_return_400(self):
        cases = [
            {"rating_start_date": "2026-09-01"},
            {"type_end_date": "2026-09-01"},
            {"rating_start_date": "2026-02-30", "rating_end_date": "2026-03-01"},
            {"type_start_date": "2026-10-01", "type_end_date": "2026-09-01"},
            {"country": ""},
            {"country": ["USA"]},
            {"body": "not-json"},
        ]
        for event in cases:
            with self.subTest(event=event):
                status, body = self.invoke(event)
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_invalid_second_range_does_not_return_partial_custom(self):
        status, body = self.invoke({
            "rating_start_date": "2026-09-01", "rating_end_date": "2026-09-26",
            "type_start_date": "2026-09-01",
        })
        self.assertEqual(status, 400)
        self.assertNotIn("Custom", body)

    def test_invalid_ratings_and_types_do_not_enter_charts(self):
        self.write_organizations(ORGANIZATIONS + [
            ("7", "4.5", "other", "VA", "2026-09-26 11:00:00"),
        ])
        status, body = self.invoke()
        self.assertEqual(status, 200)
        self.assertEqual(body["7D"]["rating_distribution"], [
            {"rating": 4, "count": 1}, {"rating": 5, "count": 1},
        ])
        self.assertEqual(body["7D"]["organization_mix_trend"]["non_profit"], [
            {"period": "2026-09-26", "count": 3},
        ])

    def test_postgres_cursor_path_closes_resources(self):
        class Cursor:
            closed = False

            def execute(self, query):
                self.query = query

            def fetchall(self):
                return [(5, "non_profit", datetime(2026, 9, 26, tzinfo=timezone.utc), "USA", "United States")]

            def close(self):
                self.closed = True

        class Connection:
            closed = False

            def __init__(self):
                self.cursor_object = Cursor()

            def cursor(self):
                return self.cursor_object

            def close(self):
                self.closed = True

        connection = Connection()
        with patch.dict(os.environ, {"USE_MOCK_DATA": "false", "DB_DSN": "test-dsn"}), patch.object(
            api, "psycopg2", create=True,
        ) as driver:
            driver.connect.return_value = connection
            status, body = self.invoke()
        self.assertEqual(status, 200)
        self.assertEqual(body["All"]["rating_distribution"], [{"rating": 5, "count": 1}])
        self.assertIn("JOIN virginia_dev_saayam_rdbms.states", connection.cursor_object.query)
        self.assertTrue(connection.cursor_object.closed)
        self.assertTrue(connection.closed)

    def test_backend_error_is_safe(self):
        with patch.object(api, "load_mock_records", side_effect=RuntimeError("secret database detail")):
            status, body = self.invoke()
        self.assertEqual(status, 500)
        self.assertNotIn("secret", json.dumps(body))


if __name__ == "__main__":
    unittest.main()
