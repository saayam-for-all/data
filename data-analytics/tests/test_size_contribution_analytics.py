"""Issue #376: stdlib unittest tests; no third-party test runner required."""

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parent.parent / "lambda_functions" / "size_contribution_analytics.py"
spec = importlib.util.spec_from_file_location("size_contribution_analytics", MODULE_PATH)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class SizeContributionTests(unittest.TestCase):
    """Exercise independent windows, filters, bad requests, and edge cases."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.orgs = [
            # Two organizations belong to BOTH flags; one belongs to NEITHER.
            ("A", "Small", True, True, "Non-Profit", "CA", "2026-09-23 22:00:00"),
            ("B", "Medium", "TRUE", "TRUE", "non_profit", "NY", "2026-09-22 02:00:00"),
            ("C", "Large", False, False, "For-profit", "NY", "2026-09-20 09:00:00"),
            ("D", "Small", False, True, "Non-Profit", "ON", "2026-08-30 07:00:00"),
            ("E", "Medium", True, False, "Non-Profit", "CA", "2025-03-01 10:00:00"),
        ]
        self.write_csvs()
        env = patch.dict(os.environ, {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": str(self.directory)})
        env.start()
        self.addCleanup(env.stop)
        clock = patch.object(api, "today", return_value=date(2026, 9, 23))
        clock.start()
        self.addCleanup(clock.stop)

    def write_csvs(self, no_contributor=False):
        """Write test-only data outside the repo; these CSVs never ship in the PR."""
        columns = ("org_id", "org_size", "is_collaborator", "is_contributor", "org_type", "state_id", "created_at")
        frame = pd.DataFrame(self.orgs, columns=columns)
        if no_contributor:
            frame = frame.drop(columns=["is_contributor"])
        frame.to_csv(self.directory / "organizations.csv", index=False)
        pd.DataFrame([
            {"state_id": "CA", "country_id": 1},
            {"state_id": "NY", "country_id": 1},
            {"state_id": "ON", "country_id": 2},
        ]).to_csv(self.directory / "states.csv", index=False)
        pd.DataFrame([
            {"country_id": 1, "country_code": "USA", "country_name": "UNITED STATES"},
            {"country_id": 2, "country_code": "CAN", "country_name": "CANADA"},
        ]).to_csv(self.directory / "countries.csv", index=False)

    def call(self, event):
        result = api.lambda_handler(event, None)
        return result["statusCode"], json.loads(result["body"])

    def test_no_params_returns_exactly_five_buckets(self):
        code, body = self.call({})
        self.assertEqual(code, 200)
        self.assertEqual(list(body), ["7D", "30D", "1Y", "All", "Custom"])
        for bucket in body.values():
            self.assertEqual(set(bucket), {"organizations_by_size", "collaborator_vs_contributor"})
        self.assertEqual(body["Custom"], {"organizations_by_size": [], "collaborator_vs_contributor": []})
        self.assertEqual(sum(row["count"] for row in body["7D"]["organizations_by_size"]), 3)
        self.assertEqual(sum(row["count"] for row in body["30D"]["organizations_by_size"]), 4)
        self.assertEqual(sum(row["count"] for row in body["All"]["organizations_by_size"]), 5)

    def test_counts_independent_and_normalized(self):
        _, body = self.call({})
        snapshot = body["7D"]
        self.assertEqual(snapshot["organizations_by_size"], [
            {"size": "large", "count": 1},
            {"size": "medium", "count": 1},
            {"size": "small", "count": 1},
        ])
        self.assertEqual(snapshot["collaborator_vs_contributor"], [
            {"type": "Collaborator", "count": 2, "percentage": 66.7},
            {"type": "Contributor", "count": 2, "percentage": 66.7},
        ])
        self.assertGreater(sum(x["count"] for x in snapshot["collaborator_vs_contributor"]), 3)

    def test_country_by_code_and_name(self):
        for filter_name in ("USA", "United States"):
            with self.subTest(country=filter_name):
                code, body = self.call({"country": filter_name})
                self.assertEqual(code, 200)
                self.assertEqual(sum(x["count"] for x in body["All"]["organizations_by_size"]), 4)
        _, body = self.call({"country": "CAN"})
        self.assertEqual(body["All"]["organizations_by_size"], [{"size": "small", "count": 1}])

    def test_organization_type_filter(self):
        _, body = self.call({"organization_type": "non_profit"})
        self.assertEqual(sum(r["count"] for r in body["All"]["organizations_by_size"]), 4)
        _, body = self.call({"organization_type": "for_profit"})
        self.assertEqual(body["All"]["organizations_by_size"], [{"size": "large", "count": 1}])
        _, body = self.call({"country": "CAN", "organization_type": "for_profit"})
        self.assertEqual(body["All"], {"organizations_by_size": [], "collaborator_vs_contributor": []})

    def test_size_custom_only(self):
        code, body = self.call({"size_start_date": "2026-09-21", "size_end_date": "2026-09-23"})
        self.assertEqual(code, 200)
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(body["Custom"]["organizations_by_size"], [
            {"size": "medium", "count": 1}, {"size": "small", "count": 1},
        ])
        self.assertEqual(body["Custom"]["collaborator_vs_contributor"], [])

    def test_contribution_custom_only(self):
        code, body = self.call({"contribution_start_date": "2026-08-01", "contribution_end_date": "2026-08-31"})
        self.assertEqual(code, 200)
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(body["Custom"]["organizations_by_size"], [])
        self.assertEqual(body["Custom"]["collaborator_vs_contributor"], [
            {"type": "Collaborator", "count": 0, "percentage": 0.0},
            {"type": "Contributor", "count": 1, "percentage": 100.0},
        ])

    def test_both_custom_pairs_use_their_own_windows(self):
        code, body = self.call({
            "size_start_date": "2026-09-21", "size_end_date": "2026-09-23",
            "contribution_start_date": "2026-08-01", "contribution_end_date": "2026-08-31",
        })
        self.assertEqual(code, 200)
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(sum(r["count"] for r in body["Custom"]["organizations_by_size"]), 2)
        self.assertEqual(body["Custom"]["collaborator_vs_contributor"][1]["count"], 1)

    def test_bad_dates_and_incomplete_pairs_400(self):
        cases = (
            {"size_start_date": "2026-09-23"},
            {"contribution_end_date": "2026-09-23"},
            {"size_start_date": "2026-02-30", "size_end_date": "2026-03-01"},
            {"contribution_start_date": "2026-09-23", "contribution_end_date": "2026-09-22"},
            {"size_start_date": None, "size_end_date": "2026-09-22"},
            {"size_start_date": "2026-09-23", "size_end_date": "2026-09-22",
             "contribution_start_date": "2026-08-01", "contribution_end_date": "2026-08-31"},
        )
        for event in cases:
            with self.subTest(event=event):
                code, body = self.call(event)
                self.assertEqual(code, 400)
                self.assertEqual(set(body), {"error"})

    def test_bad_filters_or_json_400(self):
        for event in ({"country": 42}, {"organization_type": "charity"},
                      {"body": "{bad json"}, {"body": [42]}):
            with self.subTest(event=event):
                code, body = self.call(event)
                self.assertEqual(code, 400)
                self.assertIn("error", body)

    def test_api_gateway_body_and_query_string(self):
        event = {"queryStringParameters": {"country": "CAN"},
                 "body": json.dumps({"country": "USA", "size_start_date": "2026-09-21",
                                     "size_end_date": "2026-09-23"})}
        code, body = self.call(event)
        self.assertEqual(code, 200)
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(sum(x["count"] for x in body["Custom"]["organizations_by_size"]), 2)

    def test_missing_contributor_column_is_zero(self):
        self.write_csvs(no_contributor=True)
        code, body = self.call({})
        self.assertEqual(code, 200)
        self.assertEqual(body["7D"]["collaborator_vs_contributor"][1],
                         {"type": "Contributor", "count": 0, "percentage": 0.0})

    def test_empty_csv_is_safe(self):
        self.orgs = []
        self.write_csvs()
        code, body = self.call({})
        self.assertEqual(code, 200)
        for window in body.values():
            self.assertEqual(window, {"organizations_by_size": [], "collaborator_vs_contributor": []})
        code, body = self.call({"size_start_date": "2026-09-01", "size_end_date": "2026-09-30",
                                "contribution_start_date": "2026-09-01", "contribution_end_date": "2026-09-30"})
        self.assertEqual(code, 200)
        self.assertEqual(body["Custom"], {"organizations_by_size": [], "collaborator_vs_contributor": []})

    def test_one_row_is_safe(self):
        self.orgs = self.orgs[:1]
        self.write_csvs()
        code, body = self.call({})
        self.assertEqual(code, 200)
        self.assertEqual(body["7D"]["organizations_by_size"], [{"size": "small", "count": 1}])
        self.assertEqual(body["7D"]["collaborator_vs_contributor"][0]["percentage"], 100.0)

    def test_missing_data_files_returns_500(self):
        (self.directory / "organizations.csv").unlink()
        code, body = self.call({})
        self.assertEqual(code, 500)
        self.assertIn("error", body)

    def test_uses_optional_postgres_client_and_closes_connection(self):
        """Mock the DB client without needing PostgreSQL or a live Saayam DB."""
        from unittest.mock import MagicMock
        connection = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [{"column_name": "org_id"}, {"column_name": "created_at"}],
            [{"org_id": "PG-1", "org_size": "Small", "is_collaborator": True,
              "is_contributor": False, "org_type": "Non-Profit", "state_id": "CA",
              "created_at": "2026-09-22", "country_code": "USA", "country_name": "UNITED STATES"}],
        ]
        connection.cursor.return_value.__enter__.return_value = cursor
        fake_psycopg2 = MagicMock()
        fake_psycopg2.connect.return_value = connection
        with patch.dict(os.environ, {"USE_MOCK_DATA": "false", "DATABASE_URL": "postgresql://example"}), \
             patch.object(api, "psycopg2", fake_psycopg2), patch.object(api, "RealDictCursor", object()):
            code, body = self.call({})
        self.assertEqual(code, 200)
        self.assertEqual(body["7D"]["organizations_by_size"], [{"size": "small", "count": 1}])
        self.assertEqual(body["7D"]["collaborator_vs_contributor"][1]["count"], 0)
        self.assertIn("FALSE AS is_contributor", cursor.execute.call_args_list[1].args[0])
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
