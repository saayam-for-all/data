"""Contract and data-source tests using real temporary CSVs, without AWS."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

import size_contribution_analytics as api
from create_mock_data import sample_tables, write_tables


NOW = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)


class AnalyticsTests(unittest.TestCase):
    """Exercise the public handler with on-disk CSVs and a fixed UTC clock."""

    def setUp(self):
        """Isolate every case from local configuration and other test cases."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.tables = sample_tables(NOW)
        write_tables(self.directory, self.tables)
        self.env = patch.dict(os.environ, {
            "USE_MOCK_DATA": "true", "MOCK_DATA_DIR": str(self.directory)
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.clock = patch.object(api, "utc_now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def call(self, event=None, status=200):
        """Decode the real proxy response and assert JSON/CORS contracts."""
        response = api.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], status, response)
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        self.assertEqual(response["headers"]["Access-Control-Allow-Origin"], "*")
        body = json.loads(response["body"])
        if status == 200:
            for charts in body.values():
                self.assertEqual(set(charts), {
                    "organizations_by_size", "collaborator_vs_contributor"
                })
        else:
            self.assertTrue(body["error"])
        return body

    def write_orgs(self, organizations):
        """Replace only the isolated test's organizations table."""
        organizations.to_csv(self.directory / "organizations.csv", index=False)

    def total(self, charts):
        """Calculate a total from the public size chart."""
        return sum(row["count"] for row in charts["organizations_by_size"])

    def test_default_exact_buckets_and_expected_counts(self):
        result = self.call({})
        self.assertEqual(list(result), ["7D", "30D", "1Y", "All", "Custom"])
        self.assertEqual([self.total(result[k]) for k in result], [3, 4, 6, 7, 0])
        self.assertEqual(result["Custom"], api.empty_charts())
        self.assertEqual(result["7D"]["organizations_by_size"], [
            {"size": "medium", "count": 1}, {"size": "small", "count": 2}
        ])
        self.assertEqual(result["7D"]["collaborator_vs_contributor"], [
            {"type": "Collaborator", "count": 2, "percentage": 66.7},
            {"type": "Contributor", "count": 1, "percentage": 33.3},
        ])

    def test_request_body_variants(self):
        expected = self.call({"country": "USA"})
        for event in ({"body": {"country": "USA"}},
                      {"body": '{"country":"USA"}', "httpMethod": "POST"}):
            with self.subTest(event=event):
                self.assertEqual(self.call(event), expected)
        for event in (None, {}, {"body": None}, {"body": ""}, {"body": "{}"}):
            with self.subTest(event=event):
                self.assertEqual(self.total(self.call(event)["All"]), 7)

    def test_country_code_name_and_combined_type_filters(self):
        for country in ("USA", "usa", " United States "):
            with self.subTest(country=country):
                self.assertEqual(self.total(self.call({"country": country})["All"]), 4)
        self.assertEqual(self.total(self.call({"organization_type": "non_profit"})["All"]), 5)
        self.assertEqual(self.total(self.call({"organization_type": "for_profit"})["All"]), 2)
        self.assertEqual(self.total(self.call({
            "country": "USA", "organization_type": "non_profit"
        })["All"]), 3)
        self.assertEqual(self.call({"country": "ALL", "organization_type": "all"}), self.call({}))

    def test_size_only_custom(self):
        result = self.call({"size_start_date": "2026-09-19", "size_end_date": "2026-09-28"})
        self.assertEqual(list(result), ["Custom"])
        self.assertEqual(self.total(result["Custom"]), 4)
        self.assertEqual(result["Custom"]["collaborator_vs_contributor"], [])

    def test_contribution_only_custom(self):
        result = self.call({
            "contribution_start_date": "2025-08-25",
            "contribution_end_date": "2025-08-25",
        })
        self.assertEqual(list(result), ["Custom"])
        self.assertEqual(result["Custom"], {
            "organizations_by_size": [],
            "collaborator_vs_contributor": [
                {"type": "Collaborator", "count": 0, "percentage": 0.0},
                {"type": "Contributor", "count": 1, "percentage": 100.0},
            ],
        })

    def test_both_custom_ranges_use_different_windows(self):
        result = self.call({
            "size_start_date": "2026-09-19", "size_end_date": "2026-09-28",
            "contribution_start_date": "2025-08-25", "contribution_end_date": "2025-08-25",
            "country": "USA", "organization_type": "non_profit",
        })
        self.assertEqual(list(result), ["Custom"])
        self.assertEqual(self.total(result["Custom"]), 2)
        self.assertEqual(result["Custom"]["collaborator_vs_contributor"], [
            {"type": "Collaborator", "count": 0, "percentage": 0.0},
            {"type": "Contributor", "count": 1, "percentage": 100.0},
        ])

    def test_custom_does_not_compute_fixed_charts(self):
        with patch.object(
            api, "contribution_chart", side_effect=AssertionError("unrequested chart")
        ):
            self.call({"size_start_date": "2026-09-01", "size_end_date": "2026-09-30"})
        with patch.object(api, "size_chart", side_effect=AssertionError("unrequested chart")):
            self.call({
                "contribution_start_date": "2026-09-01",
                "contribution_end_date": "2026-09-30",
            })

    def test_independent_flags_can_total_above_or_below_100_percent(self):
        for index, expected in ((0, 100.0), (1, 0.0)):
            with self.subTest(index=index):
                self.write_orgs(self.tables[0].iloc[[index]])
                charts = self.call({})["All"]
                self.assertEqual(self.total(charts), 1)
                self.assertEqual(
                    [r["percentage"] for r in charts["collaborator_vs_contributor"]],
                    [expected, expected],
                )

    def test_missing_contributor_is_zero(self):
        self.write_orgs(self.tables[0].drop(columns="is_contributor"))
        result = self.call({})
        for key in ("7D", "30D", "1Y", "All"):
            self.assertEqual(result[key]["collaborator_vs_contributor"][1], {
                "type": "Contributor", "count": 0, "percentage": 0.0
            })

    def test_boolean_strings_and_numbers_are_not_truthiness(self):
        organizations = self.tables[0].iloc[:6].copy()
        organizations["is_collaborator"] = ["TRUE", "FALSE", "t", "f", "1", "0"]
        organizations["is_contributor"] = ["False", "True", "0.0", "1.0", "", None]
        self.write_orgs(organizations)
        self.assertEqual(self.call({})["All"]["collaborator_vs_contributor"], [
            {"type": "Collaborator", "count": 3, "percentage": 50.0},
            {"type": "Contributor", "count": 2, "percentage": 33.3},
        ])

    def test_empty_header_only_and_zero_byte_organizations(self):
        for zero_byte in (False, True):
            with self.subTest(zero_byte=zero_byte):
                self.write_orgs(self.tables[0].iloc[:0])
                if zero_byte:
                    (self.directory / "organizations.csv").write_text("")
                for event in (
                    {},
                    {"size_start_date": "2026-01-01", "size_end_date": "2026-12-31"},
                    {"contribution_start_date": "2026-01-01",
                     "contribution_end_date": "2026-12-31"},
                ):
                    self.assertTrue(all(
                        c == api.empty_charts() for c in self.call(event).values()
                    ))

    def test_unknown_country_and_empty_custom_return_empty_arrays(self):
        result = self.call({"country": "Atlantis"})
        self.assertTrue(all(c == api.empty_charts() for c in result.values()))
        self.assertEqual(self.call({
            "size_start_date": "2000-01-01", "size_end_date": "2000-01-01",
            "contribution_start_date": "2000-01-01", "contribution_end_date": "2000-01-01",
        }), {"Custom": api.empty_charts()})

    def test_raw_size_categories_are_preserved_without_zero_filling(self):
        organizations = self.tables[0].iloc[[0]].copy()
        organizations["org_size"] = "Future_Enum"
        self.write_orgs(organizations)
        self.assertEqual(self.call({})["7D"]["organizations_by_size"], [
            {"size": "Future_Enum", "count": 1}
        ])

    def test_all_preserves_organizations_without_geography(self):
        self.write_orgs(self.tables[0].iloc[[7]])
        self.assertEqual(self.total(self.call({})["All"]), 1)
        self.assertEqual(self.call({"country": "USA"})["All"], api.empty_charts())

    def test_lookup_aliases_and_optional_country_columns(self):
        (self.directory / "states.csv").rename(self.directory / "state.csv")
        (self.directory / "countries.csv").rename(self.directory / "country.csv")
        self.assertEqual(self.total(self.call({"country": "USA"})["All"]), 4)
        for dropped, country in (("country_name", "USA"), ("country_code", "United States")):
            with self.subTest(dropped=dropped):
                self.tables[2].drop(columns=dropped).to_csv(
                    self.directory / "country.csv", index=False
                )
                self.assertEqual(self.total(self.call({"country": country})["All"]), 4)

    def test_utc_custom_includes_whole_end_day(self):
        organizations = pd.concat([self.tables[0].iloc[[0]]] * 4, ignore_index=True)
        organizations["org_id"] = ["a", "b", "c", "d"]
        organizations["created_at"] = [
            "2026-01-01T00:00:00Z", "2026-01-01T23:59:59.999999Z",
            "2026-01-02T00:00:00Z", "2026-01-02T00:30:00+01:00",
        ]
        self.write_orgs(organizations)
        result = self.call({"size_start_date": "2026-01-01", "size_end_date": "2026-01-01"})
        self.assertEqual(self.total(result["Custom"]), 3)

    def test_rolling_window_boundaries_and_future_exclusion(self):
        for key, days in (("7D", 7), ("30D", 30), ("1Y", 365)):
            with self.subTest(bucket=key):
                organizations = pd.concat([self.tables[0].iloc[[0]]] * 4, ignore_index=True)
                organizations["org_id"] = ["a", "b", "c", "d"]
                boundary = NOW - timedelta(days=days)
                organizations["created_at"] = [
                    boundary, boundary - timedelta(microseconds=1),
                    NOW, NOW + timedelta(microseconds=1),
                ]
                self.write_orgs(organizations)
                result = self.call({})
                self.assertEqual(self.total(result[key]), 2)
                self.assertEqual(self.total(result["All"]), 3)

    def test_invalid_date_pairs_fail_before_loading(self):
        for prefix in ("size", "contribution"):
            start, end = f"{prefix}_start_date", f"{prefix}_end_date"
            bad_pairs = [
                {start: "2026-01-01"}, {end: "2026-01-01"},
                {start: None, end: "2026-01-01"}, {start: "", end: "2026-01-01"},
                {start: 20260101, end: "2026-01-01"},
                {start: "2026-02-30", end: "2026-03-01"},
                {start: "2026-1-01", end: "2026-01-02"},
                {start: "2026-01-01T00:00:00", end: "2026-01-02"},
                {start: "2026-02-01", end: "2026-01-01"},
            ]
            for filters in bad_pairs:
                with self.subTest(filters=filters), patch.object(api, "load_tables") as loader:
                    self.call(filters, 400)
                    loader.assert_not_called()

    def test_valid_first_range_does_not_hide_invalid_second(self):
        self.call({
            "size_start_date": "2026-01-01", "size_end_date": "2026-12-31",
            "contribution_start_date": "2026-01-01",
        }, 400)

    def test_invalid_bodies_and_filters(self):
        for event in ([], "{}", {"body": "{"}, {"body": "[]"}, {"body": "null"},
                      {"body": 1}, {"body": False}, {"country": None}, {"country": []},
                      {"country": " "}, {"organization_type": "charity"},
                      {"organization_type": False}, {"time_filter": "7D"},
                      {"isBase64Encoded": True, "body": "e30="}):
            with self.subTest(event=event):
                self.call(event, 400)

    def test_duplicate_keys_rejected_to_prevent_double_counting(self):
        for index in range(3):
            with self.subTest(table=index):
                tables = list(self.tables)
                tables[index] = pd.concat([tables[index], tables[index].iloc[[0]]])
                write_tables(self.directory, tables)
                self.call({}, 500)

    def test_bad_data_returns_clear_server_errors(self):
        for column, value in (("created_at", "bad-date"), ("org_size", ""),
                              ("is_collaborator", "maybe"), ("org_id", "")):
            with self.subTest(column=column):
                organizations = self.tables[0].astype(object).copy()
                organizations.loc[0, column] = value
                self.write_orgs(organizations)
                self.assertIn(column, self.call({}, 500)["error"])
        self.write_orgs(self.tables[0].drop(columns="org_size"))
        self.assertIn("org_size", self.call({}, 500)["error"])

    def test_missing_files_and_invalid_mode(self):
        (self.directory / "organizations.csv").unlink()
        self.assertIn("MOCK_DATA_DIR", self.call({}, 500)["error"])
        with patch.dict(os.environ, {"USE_MOCK_DATA": "typo"}):
            self.assertIn("USE_MOCK_DATA", self.call({}, 500)["error"])

    def test_database_path_uses_same_analytics_and_closes_connection(self):
        expected = self.call({})
        driver = MagicMock()
        connection = driver.connect.return_value
        with (
            patch.dict(os.environ, {
                "USE_MOCK_DATA": "false", "DB_HOST": "localhost", "DB_NAME": "test",
                "DB_USER": "test", "DB_PASSWORD": "test",
            }),
            patch.object(api, "psycopg2", driver),
            patch.object(api, "read_db_table", side_effect=self.tables),
        ):
            self.assertEqual(self.call({}), expected)
            connection.set_session.assert_called_once_with(
                readonly=True, isolation_level="REPEATABLE READ"
            )
            connection.close.assert_called_once()

    def test_database_cleanup_on_failure_and_no_secret_in_response(self):
        driver = MagicMock()
        with (
            patch.dict(os.environ, {
                "USE_MOCK_DATA": "false", "DB_HOST": "localhost", "DB_NAME": "test",
                "DB_USER": "test", "DB_PASSWORD": "private-password",
            }),
            patch.object(api, "psycopg2", driver),
            patch.object(api, "read_db_table", side_effect=RuntimeError("private-password")),
            self.assertLogs(api.LOGGER),
        ):
            self.assertNotIn("private-password", self.call({}, 500)["error"])
            driver.connect.return_value.close.assert_called_once()

    def test_no_driver_needed_for_mock_mode(self):
        with patch.object(api, "psycopg2", None):
            self.call({})
            with patch.dict(os.environ, {"USE_MOCK_DATA": "false"}):
                self.assertIn("psycopg2", self.call({}, 500)["error"])

    def test_import_and_run_when_psycopg2_is_not_installed(self):
        code = (
            "import sys; sys.modules['psycopg2'] = None; "
            "import size_contribution_analytics as api; "
            "assert api.psycopg2 is None; "
            "assert api.lambda_handler({}, None)['statusCode'] == 200"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parent,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(api.sql is not None, "optional psycopg2 is not installed")
    def test_database_selects_available_columns_with_safe_identifiers(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [(column,) for column in api.ORG_COLUMNS],
            [("a", "small", True, "non_profit", "CA", NOW)],
        ]
        result = api.read_db_table(
            connection, 'schema"name', "organizations", api.ORG_COLUMNS,
            ("is_contributor",),
        )
        self.assertEqual(list(result.columns), list(api.ORG_COLUMNS))
        self.assertEqual(len(result), 1)
        metadata_call, select_call = cursor.execute.call_args_list
        self.assertEqual(metadata_call.args[1], ('schema"name', "organizations"))
        self.assertIsInstance(select_call.args[0], api.sql.Composed)
        self.assertIn(api.sql.Identifier('schema"name'), select_call.args[0].seq)

    def test_database_missing_columns_are_reported(self):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []
        with self.assertRaisesRegex(api.DataError, "missing columns"):
            api.read_db_table(connection, "schema", "organizations", api.ORG_COLUMNS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
