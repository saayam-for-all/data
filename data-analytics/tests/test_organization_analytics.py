"""
Unit tests for organization_analytics.py (issue #228).

Uses unittest.mock to fake psycopg2 connections/cursors, so these run
without a real database - mirrors the "cursor-based/mock database unit
tests" requirement in the issue.

Run with:
    python -m unittest test_organization_analytics.py -v
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import organization_analytics as api


def make_mock_cursor(fetchone_results=None, fetchall_results=None, column_exists=True):
    """
    fetchone_results: list of dict rows returned in order across successive
                       fetchone() calls.
    fetchall_results:  list of list-of-dict rows returned in order across
                       successive fetchall() calls.
    """
    cursor = MagicMock()
    fetchone_results = list(fetchone_results or [])
    fetchall_results = list(fetchall_results or [])

    def fetchone_side_effect(*args, **kwargs):
        return fetchone_results.pop(0) if fetchone_results else None

    def fetchall_side_effect(*args, **kwargs):
        return fetchall_results.pop(0) if fetchall_results else []

    cursor.fetchone.side_effect = fetchone_side_effect
    cursor.fetchall.side_effect = fetchall_side_effect
    return cursor


class TestFilters(unittest.TestCase):
    def test_build_date_filter_valid_ranges(self):
        for tf in ["7D", "30D", "1Y", "ALL"]:
            condition, params = api.build_date_filter(tf)
            self.assertIsInstance(condition, str)
            self.assertEqual(params, ())

    def test_build_date_filter_custom_requires_dates(self):
        with self.assertRaises(ValueError):
            api.build_date_filter("CUSTOM", None, None)

    def test_build_date_filter_custom_with_dates(self):
        condition, params = api.build_date_filter("CUSTOM", "2026-01-01", "2026-06-30")
        self.assertIn("BETWEEN", condition)
        self.assertEqual(params, ("2026-01-01", "2026-06-30"))

    def test_build_date_filter_invalid(self):
        with self.assertRaises(ValueError):
            api.build_date_filter("INVALID")

    def test_get_grouping_valid(self):
        for g in ["daily", "weekly", "monthly", "yearly"]:
            period, date_string = api.get_grouping(g)
            self.assertTrue(period)
            self.assertTrue(date_string)

    def test_get_grouping_invalid(self):
        with self.assertRaises(ValueError):
            api.get_grouping("hourly")

    def test_build_common_where_no_filters(self):
        where_clause, params = api.build_common_where("ALL", None, None, "ALL", "ALL")
        self.assertEqual(where_clause, "")
        self.assertEqual(params, [])

    def test_build_common_where_region_and_type(self):
        where_clause, params = api.build_common_where(
            "ALL", None, None, "California", "non_profit"
        )
        self.assertIn("WHERE", where_clause)
        self.assertIn("California", params)
        self.assertIn("non_profit", params)


class TestFetchFunctions(unittest.TestCase):
    def test_fetch_summary_with_data(self):
        cursor = make_mock_cursor(
            fetchone_results=[
                {
                    "total_organizations": 126,
                    "total_collaborators": 42,
                    "total_contributors": 84,
                    "average_org_rating": 4.2,
                }
            ]
        )
        result = api.fetch_summary(cursor, True, "ALL", None, None, "ALL", "ALL")
        self.assertEqual(result["total_organizations"], 126)
        self.assertEqual(result["average_org_rating"], 4.2)

    def test_fetch_summary_empty_result_set(self):
        cursor = make_mock_cursor(fetchone_results=[None])
        result = api.fetch_summary(cursor, True, "ALL", None, None, "ALL", "ALL")
        self.assertEqual(
            result,
            {
                "total_organizations": 0,
                "total_collaborators": 0,
                "total_contributors": 0,
                "average_org_rating": 0,
            },
        )

    def test_fetch_rating_distribution_fills_missing_buckets(self):
        # Only ratings 4 and 5 present in DB; 1-3 should still show as 0.
        cursor = make_mock_cursor(
            fetchall_results=[[{"rating": 4, "organization_count": 46}, {"rating": 5, "organization_count": 64}]]
        )
        result = api.fetch_rating_distribution(cursor, "ALL", None, None, "ALL", "ALL")
        self.assertEqual(len(result), 5)
        ratings = {row["rating"]: row["organization_count"] for row in result}
        self.assertEqual(ratings[1], 0)
        self.assertEqual(ratings[4], 46)
        self.assertEqual(ratings[5], 64)

    def test_fetch_rating_distribution_handles_null_ratings_safely(self):
        # NULL ratings must not raise; query excludes them via NOT NULL guard.
        cursor = make_mock_cursor(fetchall_results=[[]])
        result = api.fetch_rating_distribution(cursor, "ALL", None, None, "ALL", "ALL")
        self.assertEqual(sum(r["organization_count"] for r in result), 0)

    def test_fetch_collaborator_vs_contributor_percentages(self):
        cursor = make_mock_cursor(
            fetchone_results=[{"collaborator_count": 42, "contributor_count": 84}]
        )
        result = api.fetch_collaborator_vs_contributor(cursor, True, "ALL", None, None, "ALL", "ALL")
        collab = next(r for r in result if r["type"] == "collaborator")
        contrib = next(r for r in result if r["type"] == "contributor")
        self.assertEqual(collab["organization_count"], 42)
        self.assertEqual(contrib["organization_count"], 84)
        self.assertAlmostEqual(collab["percentage"], 33.3, places=1)
        self.assertAlmostEqual(contrib["percentage"], 66.7, places=1)

    def test_fetch_collaborator_vs_contributor_zero_total(self):
        cursor = make_mock_cursor(
            fetchone_results=[{"collaborator_count": 0, "contributor_count": 0}]
        )
        result = api.fetch_collaborator_vs_contributor(cursor, True, "ALL", None, None, "ALL", "ALL")
        for row in result:
            self.assertEqual(row["percentage"], 0)

    def test_fetch_collaborator_vs_contributor_missing_is_contributor_column(self):
        # Simulates dev DB where is_contributor doesn't exist yet.
        cursor = make_mock_cursor(
            fetchone_results=[{"collaborator_count": 42, "contributor_count": 0}]
        )
        result = api.fetch_collaborator_vs_contributor(cursor, False, "ALL", None, None, "ALL", "ALL")
        contrib = next(r for r in result if r["type"] == "contributor")
        self.assertEqual(contrib["organization_count"], 0)

    def test_fetch_organizations_by_size_empty_result_set(self):
        cursor = make_mock_cursor(fetchall_results=[[]])
        result = api.fetch_organizations_by_size(cursor, "ALL", None, None, "ALL", "ALL")
        self.assertEqual(result, [])

    def test_fetch_growth_trend_returns_periods(self):
        cursor = make_mock_cursor(
            fetchall_results=[
                [
                    {"period": "2026-01", "total_organizations": 100, "total_collaborators": 34},
                    {"period": "2026-02", "total_organizations": 108, "total_collaborators": 36},
                ]
            ]
        )
        result = api.fetch_growth_trend(cursor, "monthly", "ALL", None, None, "ALL", "ALL")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["total_organizations"], 108)

    def test_fetch_organization_type_distribution(self):
        cursor = make_mock_cursor(
            fetchall_results=[
                [{"period": "2026-01", "for_profit": 41, "non_profit": 68, "total": 109}]
            ]
        )
        result = api.fetch_organization_type_distribution(
            cursor, "monthly", "ALL", None, None, "ALL", "ALL"
        )
        self.assertEqual(result[0]["total"], 109)

    def test_fetch_organizations_by_location_state_and_city(self):
        cursor = make_mock_cursor(
            fetchall_results=[
                [{"state_id": "CA", "state_name": "California", "organization_count": 32, "percentage": 25.4}],
                [{"city_name": "Springfield", "organization_count": 5, "percentage": 4.0}],
            ]
        )
        result = api.fetch_organizations_by_location(cursor, "ALL", None, None, "ALL", "ALL")
        self.assertEqual(result["by_state"][0]["state_name"], "California")
        self.assertEqual(result["by_city"][0]["city_name"], "Springfield")


class TestLambdaHandler(unittest.TestCase):
    def _mock_conn_cursor(self, cursor):
        conn = MagicMock()
        conn.cursor.return_value = cursor
        return conn

    @patch("organization_analytics.column_exists", return_value=True)
    @patch("organization_analytics.get_db_connection")
    def test_lambda_handler_valid_filters_returns_200(self, mock_get_conn, mock_col_exists):
        cursor = make_mock_cursor(
            fetchone_results=[
                {
                    "total_organizations": 10,
                    "total_collaborators": 4,
                    "total_contributors": 6,
                    "average_org_rating": 4.0,
                },
                {"collaborator_count": 4, "contributor_count": 6},
            ],
            fetchall_results=[[], [], [], [], []],
        )
        mock_get_conn.return_value = self._mock_conn_cursor(cursor)

        event = {
            "time_filter": "30D",
            "start_date": None,
            "end_date": None,
            "group_by": "daily",
            "region": "ALL",
            "organization_type": "ALL",
        }
        response = api.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["summary"]["total_organizations"], 10)

    def test_lambda_handler_invalid_time_filter(self):
        event = {"time_filter": "NOT_REAL", "group_by": "monthly"}
        response = api.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 400)

    def test_lambda_handler_custom_missing_dates(self):
        event = {"time_filter": "CUSTOM", "group_by": "monthly"}
        response = api.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 400)

    def test_lambda_handler_invalid_group_by(self):
        event = {"time_filter": "ALL", "group_by": "hourly"}
        response = api.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 400)

    def test_lambda_handler_custom_valid_range(self):
        with patch("organization_analytics.column_exists", return_value=True), \
             patch("organization_analytics.get_db_connection") as mock_get_conn:
            cursor = make_mock_cursor(
                fetchone_results=[
                    {
                        "total_organizations": 5,
                        "total_collaborators": 2,
                        "total_contributors": 3,
                        "average_org_rating": 3.5,
                    },
                    {"collaborator_count": 2, "contributor_count": 3},
                ],
                fetchall_results=[[], [], [], [], []],
            )
            mock_get_conn.return_value = self._mock_conn_cursor(cursor)
            event = {
                "time_filter": "CUSTOM",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "group_by": "monthly",
                "region": "ALL",
                "organization_type": "ALL",
            }
            response = api.lambda_handler(event, None)
            self.assertEqual(response["statusCode"], 200)

    @patch("organization_analytics.get_db_connection", side_effect=Exception("connection refused"))
    def test_lambda_handler_db_exception_returns_500_with_safe_body(self, mock_get_conn):
        event = {"time_filter": "ALL", "group_by": "monthly"}
        response = api.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 500)
        body = json.loads(response["body"])
        self.assertEqual(body["summary"]["total_organizations"], 0)
        self.assertEqual(body["growth_trend"], [])


if __name__ == "__main__":
    unittest.main()
