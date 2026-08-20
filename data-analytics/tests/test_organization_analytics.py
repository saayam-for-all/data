"""Cursor-based unit tests for the Organization Analytics Lambda."""

import json
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

LAMBDA_DIRECTORY = Path(__file__).resolve().parents[1] / "lambda_functions"
sys.path.insert(0, str(LAMBDA_DIRECTORY))

import organization_analytics as analytics

EXPECTED_RESPONSE_KEYS = {
    "summary",
    "growth_trend",
    "organizations_by_location",
    "organizations_by_size",
    "collaborator_vs_contributor",
    "rating_distribution",
    "organization_type_distribution",
}


def make_connection(cursor):
    connection = MagicMock()
    connection.cursor.return_value = cursor
    return connection


def happy_cursor():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {"exists": True},
        {
            "total_organizations": 126,
            "total_collaborators": 42,
            "total_contributors": 84,
            "average_org_rating": 4.2,
        },
        {"total": 126, "collaborators": 42, "contributors": 84},
    ]
    cursor.fetchall.side_effect = [
        [
            {
                "period": "2026-01",
                "total_organizations": 100,
                "total_collaborators": 34,
            }
        ],
        [
            {
                "state_id": "CA",
                "state_name": "California",
                "organization_count": 32,
                "percentage": 25.4,
            }
        ],
        [{"state_id": "CA", "city_name": "Los Angeles", "organization_count": 12}],
        [
            {"org_size": "small", "organization_count": 50},
            {"org_size": "medium", "organization_count": 45},
            {"org_size": "large", "organization_count": 31},
        ],
        [
            {"rating": 1, "organization_count": 1},
            {"rating": 2, "organization_count": 3},
            {"rating": 3, "organization_count": 12},
            {"rating": 4, "organization_count": 46},
            {"rating": 5, "organization_count": 64},
        ],
        [
            {
                "period": "2026-01",
                "for_profit": 41,
                "non_profit": 68,
                "total": 109,
            }
        ],
    ]
    return cursor


class TestRequestValidation(unittest.TestCase):
    def test_accepts_all_documented_payloads(self):
        payloads = [
            {"time_filter": "30D", "group_by": "daily"},
            {"time_filter": "1Y", "group_by": "monthly"},
            {"time_filter": "1Y", "region": "California"},
            {"time_filter": "1Y", "organization_type": "non_profit"},
            {
                "time_filter": "CUSTOM",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "group_by": "monthly",
            },
            {"time_filter": "ALL", "organization_type": "ALL"},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                result = analytics.validate_filters(payload)
                self.assertIn(result["time_filter"], analytics.VALID_TIME_FILTERS)

    def test_normalizes_organization_type_variants(self):
        self.assertEqual(
            analytics.validate_filters({"organization_type": "Non-Profit"})[
                "organization_type"
            ],
            "non_profit",
        )
        self.assertEqual(
            analytics.validate_filters({"organization_type": "all"})[
                "organization_type"
            ],
            "ALL",
        )

    def test_custom_requires_both_dates(self):
        with self.assertRaisesRegex(
            analytics.RequestValidationError, "both start_date"
        ):
            analytics.validate_filters(
                {"time_filter": "CUSTOM", "start_date": "2026-01-01"}
            )

    def test_rejects_invalid_filters_and_dates(self):
        invalid_payloads = [
            {"time_filter": "90D"},
            {"group_by": "quarterly"},
            {"organization_type": "government"},
            {"time_filter": "CUSTOM", "start_date": "bad", "end_date": "2026-01-02"},
            {
                "time_filter": "CUSTOM",
                "start_date": "2026-02-01",
                "end_date": "2026-01-01",
            },
        ]
        for payload in invalid_payloads:
            with (
                self.subTest(payload=payload),
                self.assertRaises(analytics.RequestValidationError),
            ):
                analytics.validate_filters(payload)

    def test_malformed_api_gateway_body_returns_400(self):
        result = analytics.lambda_handler({"body": "{"}, None)
        self.assertEqual(result["statusCode"], 400)
        self.assertIn("valid JSON", json.loads(result["body"])["error"])


class TestSqlFilters(unittest.TestCase):
    def test_custom_range_includes_entire_end_date(self):
        filters = analytics.validate_filters(
            {
                "time_filter": "CUSTOM",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
            }
        )
        where_sql, params = analytics.build_where_clause(filters)
        self.assertIn("o.created_at >= %(start_date)s", where_sql)
        self.assertIn("o.created_at < %(end_exclusive)s", where_sql)
        self.assertEqual(params["start_date"], date(2026, 1, 1))
        self.assertEqual(params["end_exclusive"], date(2026, 7, 1))

    def test_values_are_parameters_not_interpolated(self):
        region = "California' OR 1=1 --"
        filters = analytics.validate_filters(
            {
                "region": region,
                "organization_type": "for-profit",
            }
        )
        where_sql, params = analytics.build_where_clause(filters)
        self.assertNotIn(region, where_sql)
        self.assertEqual(params["region"], region)
        self.assertEqual(params["organization_type"], "for_profit")

    def test_state_table_defaults_to_ticket_name_and_supports_legacy_name(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(analytics.get_database_layout()[1], "states")
        with patch.dict(os.environ, {"SAAYAM_STATE_TABLE": "state"}, clear=True):
            self.assertEqual(analytics.get_database_layout()[1], "state")


class TestLambdaHandler(unittest.TestCase):
    @patch("organization_analytics.get_db_connection")
    def test_standard_request_returns_complete_dashboard(self, get_connection):
        cursor = happy_cursor()
        connection = make_connection(cursor)
        get_connection.return_value = connection

        result = analytics.lambda_handler(
            {
                "body": json.dumps(
                    {
                        "time_filter": "30D",
                        "start_date": None,
                        "end_date": None,
                        "group_by": "daily",
                        "region": "ALL",
                        "organization_type": "ALL",
                    }
                )
            },
            None,
        )

        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertEqual(set(body), EXPECTED_RESPONSE_KEYS)
        self.assertEqual(body["summary"]["total_organizations"], 126)
        self.assertEqual(body["summary"]["average_org_rating"], 4.2)
        self.assertEqual(
            body["organizations_by_location"][0]["cities"][0]["city_name"],
            "Los Angeles",
        )
        self.assertEqual(
            [item["rating"] for item in body["rating_distribution"]], [1, 2, 3, 4, 5]
        )
        cursor.close.assert_called_once()
        connection.close.assert_called_once()

    @patch("organization_analytics.get_db_connection")
    def test_empty_result_set_is_safe(self, get_connection):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"exists": True},
            {
                "total_organizations": 0,
                "total_collaborators": 0,
                "total_contributors": 0,
                "average_org_rating": None,
            },
            {"total": 0, "collaborators": 0, "contributors": 0},
        ]
        cursor.fetchall.side_effect = [
            [],
            [],
            [],
            [
                {"org_size": "small", "organization_count": 0},
                {"org_size": "medium", "organization_count": 0},
                {"org_size": "large", "organization_count": 0},
            ],
            [{"rating": value, "organization_count": 0} for value in range(1, 6)],
            [],
        ]
        get_connection.return_value = make_connection(cursor)

        result = analytics.lambda_handler({"time_filter": "7D"}, None)
        body = json.loads(result["body"])

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(body["summary"]["total_organizations"], 0)
        self.assertEqual(body["summary"]["average_org_rating"], 0.0)
        self.assertEqual(body["growth_trend"], [])
        self.assertEqual(body["organizations_by_location"], [])
        self.assertEqual(body["collaborator_vs_contributor"][0]["percentage"], 0.0)
        self.assertEqual(len(body["rating_distribution"]), 5)

    @patch("organization_analytics.get_db_connection")
    def test_missing_contributor_column_returns_zero_without_bad_queries(
        self, get_connection
    ):
        cursor = happy_cursor()
        cursor.fetchone.side_effect = [
            {"exists": False},
            {
                "total_organizations": 126,
                "total_collaborators": 42,
                "total_contributors": 0,
                "average_org_rating": 4.2,
            },
            {"total": 126, "collaborators": 42, "contributors": 0},
        ]
        get_connection.return_value = make_connection(cursor)

        result = analytics.lambda_handler({}, None)
        body = json.loads(result["body"])

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(body["summary"]["total_contributors"], 0)
        metric_queries = [call.args[0] for call in cursor.execute.call_args_list[1:]]
        self.assertTrue(
            all("o.is_contributor" not in query for query in metric_queries)
        )

    @patch("organization_analytics.get_db_connection")
    def test_one_query_exception_uses_default_and_rolls_back(self, get_connection):
        cursor = happy_cursor()
        cursor.execute.side_effect = [None, RuntimeError("query failed")] + [None] * 7
        cursor.fetchone.side_effect = [
            {"exists": True},
            {"total": 126, "collaborators": 42, "contributors": 84},
        ]
        connection = make_connection(cursor)
        get_connection.return_value = connection

        with patch.object(analytics.LOGGER, "exception"):
            result = analytics.lambda_handler({}, None)
        body = json.loads(result["body"])

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(body["summary"], analytics.get_default_response()["summary"])
        self.assertEqual(body["growth_trend"][0]["total_organizations"], 100)
        connection.rollback.assert_called_once()

    @patch("organization_analytics.get_db_connection")
    def test_connection_exception_returns_500_defaults(self, get_connection):
        get_connection.side_effect = RuntimeError("database unavailable")
        with patch.object(analytics.LOGGER, "exception"):
            result = analytics.lambda_handler({}, None)
        body = json.loads(result["body"])
        self.assertEqual(result["statusCode"], 500)
        self.assertEqual(set(body), EXPECTED_RESPONSE_KEYS)
        self.assertEqual(body["summary"]["total_organizations"], 0)


if __name__ == "__main__":
    unittest.main()
