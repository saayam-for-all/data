"""Tests for the Size & Contribution Analytics Lambda (issue #376)."""

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd


MODULE_PATH = (
    Path(__file__).parents[1]
    / "lambda_functions"
    / "org_size_contribution_analytics.py"
)
SPEC = importlib.util.spec_from_file_location("org_size_contribution_analytics", MODULE_PATH)
ANALYTICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYTICS)


class SizeContributionAnalyticsTests(unittest.TestCase):
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

    def _write_standard_tables(self, include_contributor=True, rows=None):
        columns = [
            "org_id",
            "org_size",
            "is_collaborator",
            "org_type",
            "state_id",
            "created_at",
        ]
        if include_contributor:
            columns.insert(3, "is_contributor")

        if rows is None:
            rows = [
                ["ORG1", "small", True, True, "non_profit", "CA", "2026-09-22"],
                ["ORG2", "medium", False, True, "for_profit", "TX", "2026-09-01"],
                ["ORG3", "large", True, False, "non_profit", "MH", "2025-10-01"],
                ["ORG4", "small", False, False, "Non-Profit", "CA", "2024-01-01"],
            ]
        if not include_contributor:
            rows = [[row[index] for index in range(len(row)) if index != 3] for row in rows]

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
        result = ANALYTICS.build_response({}, today=date(2026, 9, 23))
        self.assertEqual(list(result), ["7D", "30D", "1Y", "All", "Custom"])

    def test_every_bucket_contains_exactly_two_charts(self):
        result = ANALYTICS.build_response({}, today=date(2026, 9, 23))
        for bucket in result.values():
            self.assertEqual(
                set(bucket),
                {"organizations_by_size", "collaborator_vs_contributor"},
            )

    def test_custom_is_empty_without_custom_params(self):
        result = ANALYTICS.build_response({}, today=date(2026, 9, 23))
        self.assertEqual(result["Custom"], ANALYTICS._empty_charts())

    def test_size_custom_returns_only_size_chart(self):
        result = ANALYTICS.build_response(
            {"size_start_date": "2026-01-01", "size_end_date": "2026-12-31"}
        )
        self.assertEqual(list(result), ["Custom"])
        self.assertTrue(result["Custom"]["organizations_by_size"])
        self.assertEqual(result["Custom"]["collaborator_vs_contributor"], [])

    def test_contribution_custom_returns_only_contribution_chart(self):
        result = ANALYTICS.build_response(
            {
                "contribution_start_date": "2026-01-01",
                "contribution_end_date": "2026-12-31",
            }
        )
        self.assertEqual(list(result), ["Custom"])
        self.assertEqual(result["Custom"]["organizations_by_size"], [])
        self.assertEqual(len(result["Custom"]["collaborator_vs_contributor"]), 2)

    def test_both_custom_ranges_populate_both_charts(self):
        result = ANALYTICS.build_response(
            {
                "size_start_date": "2024-01-01",
                "size_end_date": "2026-12-31",
                "contribution_start_date": "2025-01-01",
                "contribution_end_date": "2026-12-31",
            }
        )
        self.assertEqual(list(result), ["Custom"])
        self.assertTrue(result["Custom"]["organizations_by_size"])
        self.assertEqual(len(result["Custom"]["collaborator_vs_contributor"]), 2)

    def test_country_code_filter(self):
        result = ANALYTICS.build_response({"country": "IND"})
        total = sum(row["count"] for row in result["All"]["organizations_by_size"])
        self.assertEqual(total, 1)

    def test_country_name_filter_accepts_spaces(self):
        result = ANALYTICS.build_response({"country": "United States"})
        total = sum(row["count"] for row in result["All"]["organizations_by_size"])
        self.assertEqual(total, 3)

    def test_organization_type_normalizes_hyphen_and_case(self):
        result = ANALYTICS.build_response({"organization_type": "non_profit"})
        total = sum(row["count"] for row in result["All"]["organizations_by_size"])
        self.assertEqual(total, 3)

    def test_contribution_counts_are_independent(self):
        result = ANALYTICS.build_response({})
        rows = result["All"]["collaborator_vs_contributor"]
        self.assertEqual(rows[0], {"type": "Collaborator", "count": 2, "percentage": 50.0})
        self.assertEqual(rows[1], {"type": "Contributor", "count": 2, "percentage": 50.0})

    def test_missing_contributor_column_becomes_zero(self):
        self._write_standard_tables(include_contributor=False)
        result = ANALYTICS.build_response({})
        contributor = result["All"]["collaborator_vs_contributor"][1]
        self.assertEqual(contributor["count"], 0)
        self.assertEqual(contributor["percentage"], 0.0)

    def test_incomplete_date_pair_returns_400(self):
        response = ANALYTICS.lambda_handler({"size_start_date": "2026-01-01"})
        self.assertEqual(response["statusCode"], 400)

    def test_bad_date_format_returns_400(self):
        response = ANALYTICS.lambda_handler(
            {"size_start_date": "01-01-2026", "size_end_date": "12-31-2026"}
        )
        self.assertEqual(response["statusCode"], 400)

    def test_start_after_end_returns_400(self):
        response = ANALYTICS.lambda_handler(
            {"size_start_date": "2026-12-31", "size_end_date": "2026-01-01"}
        )
        self.assertEqual(response["statusCode"], 400)

    def test_invalid_organization_type_returns_400(self):
        response = ANALYTICS.lambda_handler({"organization_type": "government"})
        self.assertEqual(response["statusCode"], 400)

    def test_empty_organizations_file_does_not_crash(self):
        self._write_standard_tables(rows=[])
        result = ANALYTICS.build_response({}, today=date(2026, 9, 23))
        for bucket in result.values():
            self.assertEqual(bucket, ANALYTICS._empty_charts())

    def test_single_row_file_does_not_crash(self):
        row = [["ORG1", "small", True, True, "non_profit", "CA", "2026-09-22"]]
        self._write_standard_tables(rows=row)
        result = ANALYTICS.build_response({}, today=date(2026, 9, 23))
        self.assertEqual(result["All"]["organizations_by_size"], [{"size": "small", "count": 1}])

    def test_api_gateway_json_body_is_supported(self):
        response = ANALYTICS.lambda_handler(
            {"body": json.dumps({"organization_type": "non_profit"})}
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(set(self._body(response)), {"7D", "30D", "1Y", "All", "Custom"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
