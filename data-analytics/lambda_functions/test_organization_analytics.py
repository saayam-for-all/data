"""Cursor/mock unit tests for the Organization Analytics API (#228).

These tests do not connect to AWS or a real database.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import organization_analytics as api  # noqa: E402


class FakeCursor:
    """Minimal DB cursor that returns canned rows based on executed SQL."""

    def __init__(self, contributor_exists=True, empty=False, fail_on=None):
        self.contributor_exists = contributor_exists
        self.empty = empty
        self.fail_on = fail_on
        self.executed = []
        self.closed = False
        self._result = []
        self._one = None

    def execute(self, query, params=None):
        sql = " ".join(query.split())
        self.executed.append((sql, params or []))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("simulated query failure")

        lowered = sql.lower()
        if "information_schema.columns" in lowered:
            self._one = (1,) if self.contributor_exists else None
            self._result = []
            return

        if self.empty:
            self._one = {
                "total_organizations": 0,
                "total_collaborators": 0,
                "total_contributors": 0,
                "rating_sum": 0,
                "rating_count": 0,
            }
            self._result = []
            return

        if "as total_organizations" in lowered:
            self._one = {
                "total_organizations": 10,
                "total_collaborators": 4,
                "total_contributors": 6,
                "rating_sum": 42.0,
                "rating_count": 10,
            }
            self._result = []
        elif "as new_organizations" in lowered:
            self._one = None
            self._result = [
                {
                    "period": "2026-01",
                    "new_organizations": 6,
                    "new_collaborators": 2,
                },
                {
                    "period": "2026-02",
                    "new_organizations": 4,
                    "new_collaborators": 2,
                },
            ]
        elif "as city_name" in lowered:
            self._one = None
            self._result = [
                {
                    "state_id": "CA",
                    "state_name": "California",
                    "city_name": "Los Angeles",
                    "organization_count": 6,
                },
                {
                    "state_id": "TX",
                    "state_name": "Texas",
                    "city_name": "Austin",
                    "organization_count": 4,
                },
            ]
        elif "as org_size" in lowered:
            self._one = None
            self._result = [
                {"org_size": "small", "organization_count": 5},
                {"org_size": "medium", "organization_count": 3},
                {"org_size": "large", "organization_count": 2},
            ]
        elif "as rating" in lowered:
            self._one = None
            self._result = [
                {"rating": 4, "organization_count": 4},
                {"rating": 5, "organization_count": 6},
            ]
        elif "as for_profit" in lowered:
            self._one = None
            self._result = [
                {"period": "2026-01", "for_profit": 2, "non_profit": 4},
                {"period": "2026-02", "for_profit": 1, "non_profit": 3},
            ]
        else:
            self._one = None
            self._result = []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._result)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self, cursor_factory=None):
        return self._cursor

    def close(self):
        self.closed = True


class ParseFilterTests(unittest.TestCase):
    def test_valid_standard_payload(self):
        filters = api.parse_filters(
            {
                "time_filter": "30D",
                "start_date": None,
                "end_date": None,
                "group_by": "daily",
                "region": "ALL",
                "organization_type": "ALL",
            }
        )
        self.assertEqual(filters["time_filter"], "30D")
        self.assertEqual(filters["group_by"], "daily")
        self.assertIsNone(filters["start_date"])

    def test_invalid_time_filter(self):
        with self.assertRaises(api.FilterValidationError):
            api.parse_filters({"time_filter": "2D"})

    def test_invalid_group_by(self):
        with self.assertRaises(api.FilterValidationError):
            api.parse_filters({"group_by": "hourly"})

    def test_invalid_organization_type(self):
        with self.assertRaises(api.FilterValidationError):
            api.parse_filters({"organization_type": "nonprofit"})

    def test_custom_requires_both_dates(self):
        with self.assertRaises(api.FilterValidationError):
            api.parse_filters(
                {"time_filter": "CUSTOM", "start_date": "2026-01-01"}
            )

    def test_custom_rejects_inverted_range(self):
        with self.assertRaises(api.FilterValidationError):
            api.parse_filters(
                {
                    "time_filter": "CUSTOM",
                    "start_date": "2026-06-30",
                    "end_date": "2026-01-01",
                }
            )

    def test_custom_date_range_is_kept(self):
        filters = api.parse_filters(
            {
                "time_filter": "CUSTOM",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "group_by": "monthly",
            }
        )
        self.assertEqual(filters["start_date"], "2026-01-01")
        self.assertEqual(filters["end_date"], "2026-06-30")


class FilterClauseTests(unittest.TestCase):
    def test_all_has_no_date_clause(self):
        sql, params = api.build_filter_clause(
            api.parse_filters({"time_filter": "ALL"})
        )
        self.assertEqual(sql, "")
        self.assertEqual(params, [])

    def test_custom_uses_parameterized_dates(self):
        sql, params = api.build_filter_clause(
            api.parse_filters(
                {
                    "time_filter": "CUSTOM",
                    "start_date": "2026-01-01",
                    "end_date": "2026-06-30",
                }
            )
        )
        self.assertIn("%s::date", sql)
        self.assertEqual(params, ["2026-01-01", "2026-06-30"])

    def test_region_california_is_parameterized(self):
        sql, params = api.build_filter_clause(
            api.parse_filters({"region": "California"})
        )
        self.assertNotIn("California", sql)
        self.assertEqual(params, ["California", "California"])

    def test_organization_type_is_parameterized(self):
        sql, params = api.build_filter_clause(
            api.parse_filters({"organization_type": "non_profit"})
        )
        self.assertIn("%s", sql)
        self.assertEqual(params, ["non_profit"])


class ResponseShapeTests(unittest.TestCase):
    def test_growth_trend_is_cumulative(self):
        trend = api.build_growth_trend(
            [
                {
                    "period": "2026-01",
                    "new_organizations": 100,
                    "new_collaborators": 34,
                },
                {
                    "period": "2026-02",
                    "new_organizations": 8,
                    "new_collaborators": 2,
                },
            ]
        )
        self.assertEqual(
            trend,
            [
                {
                    "period": "2026-01",
                    "total_organizations": 100,
                    "total_collaborators": 34,
                },
                {
                    "period": "2026-02",
                    "total_organizations": 108,
                    "total_collaborators": 36,
                },
            ],
        )

    def test_rating_distribution_always_has_1_to_5(self):
        rows = api.build_rating_distribution({4: 46, 5: 64})
        self.assertEqual([row["rating"] for row in rows], [1, 2, 3, 4, 5])
        self.assertEqual(rows[0]["organization_count"], 0)
        self.assertEqual(rows[4]["organization_count"], 64)

    def test_size_distribution_always_has_small_medium_large(self):
        rows = api.build_organizations_by_size({"small": 50})
        self.assertEqual(
            [row["org_size"] for row in rows[:3]],
            ["small", "medium", "large"],
        )
        self.assertEqual(rows[1]["organization_count"], 0)

    def test_null_ratings_do_not_affect_average(self):
        summary = api.build_summary(
            {
                "total_organizations": 3,
                "total_collaborators": 1,
                "total_contributors": 2,
                "rating_sum": 8.0,
                "rating_count": 2,
            }
        )
        self.assertEqual(summary["average_org_rating"], 4.0)


class HandlerTests(unittest.TestCase):
    def _run(self, event, cursor):
        conn = FakeConnection(cursor)
        with patch.object(api, "get_db_connection", return_value=conn):
            return api.lambda_handler(event, None), conn

    def test_valid_payload_response_structure(self):
        cursor = FakeCursor()
        response, conn = self._run(
            {
                "time_filter": "1Y",
                "group_by": "monthly",
                "region": "ALL",
                "organization_type": "ALL",
            },
            cursor,
        )
        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(
            set(body),
            {
                "summary",
                "growth_trend",
                "organizations_by_location",
                "organizations_by_size",
                "collaborator_vs_contributor",
                "rating_distribution",
                "organization_type_distribution",
            },
        )
        self.assertEqual(body["summary"]["total_organizations"], 10)
        self.assertEqual(body["summary"]["total_collaborators"], 4)
        self.assertEqual(body["summary"]["total_contributors"], 6)
        self.assertEqual(body["summary"]["average_org_rating"], 4.2)
        self.assertEqual(body["growth_trend"][-1]["total_organizations"], 10)
        self.assertEqual(body["organizations_by_location"][0]["state_id"], "CA")
        self.assertIn("cities", body["organizations_by_location"][0])
        self.assertEqual(len(body["rating_distribution"]), 5)
        self.assertTrue(cursor.closed)
        self.assertTrue(conn.closed)

    def test_api_gateway_string_body(self):
        cursor = FakeCursor()
        response, _ = self._run(
            {"body": json.dumps({"time_filter": "7D", "group_by": "daily"})},
            cursor,
        )
        self.assertEqual(response["statusCode"], 200)

    def test_invalid_filter_returns_400(self):
        response = api.lambda_handler({"time_filter": "yesterday"}, None)
        self.assertEqual(response["statusCode"], 400)
        body = json.loads(response["body"])
        self.assertIn("error", body)
        self.assertEqual(body["summary"]["total_organizations"], 0)

    def test_empty_result_set(self):
        cursor = FakeCursor(empty=True)
        response, _ = self._run({"time_filter": "ALL"}, cursor)
        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["summary"]["total_organizations"], 0)
        self.assertEqual(body["growth_trend"], [])
        self.assertEqual(body["organizations_by_location"], [])
        self.assertEqual(
            [row["organization_count"] for row in body["organizations_by_size"]],
            [0, 0, 0],
        )

    def test_missing_is_contributor_still_returns_both_types(self):
        cursor = FakeCursor(contributor_exists=False)
        response, _ = self._run({"time_filter": "ALL"}, cursor)
        body = json.loads(response["body"])
        rows = body["collaborator_vs_contributor"]
        self.assertEqual(
            [row["type"] for row in rows], ["collaborator", "contributor"]
        )
        self.assertEqual(rows[1]["organization_count"], 0)

    def test_official_sample_payloads_are_accepted(self):
        payloads = [
            {
                "time_filter": "30D",
                "start_date": None,
                "end_date": None,
                "group_by": "daily",
                "region": "ALL",
                "organization_type": "ALL",
            },
            {
                "time_filter": "1Y",
                "start_date": None,
                "end_date": None,
                "group_by": "monthly",
                "region": "ALL",
                "organization_type": "ALL",
            },
            {
                "time_filter": "1Y",
                "start_date": None,
                "end_date": None,
                "group_by": "monthly",
                "region": "California",
                "organization_type": "ALL",
            },
            {
                "time_filter": "1Y",
                "start_date": None,
                "end_date": None,
                "group_by": "monthly",
                "region": "ALL",
                "organization_type": "non_profit",
            },
            {
                "time_filter": "CUSTOM",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "group_by": "monthly",
                "region": "ALL",
                "organization_type": "ALL",
            },
        ]
        for payload in payloads:
            cursor = FakeCursor()
            response, _ = self._run(payload, cursor)
            self.assertEqual(response["statusCode"], 200, msg=payload)
            body = json.loads(response["body"])
            self.assertIn("summary", body)
            self.assertIn("growth_trend", body)

    def test_query_exception_returns_500_and_closes(self):
        cursor = FakeCursor(fail_on="information_schema.columns")
        response, conn = self._run({"time_filter": "ALL"}, cursor)
        self.assertEqual(response["statusCode"], 500)
        self.assertTrue(cursor.closed)
        self.assertTrue(conn.closed)

    def test_connection_exception_returns_500(self):
        with patch.object(
            api, "get_db_connection", side_effect=RuntimeError("db down")
        ):
            response = api.lambda_handler({"time_filter": "ALL"}, None)
        self.assertEqual(response["statusCode"], 500)
        body = json.loads(response["body"])
        self.assertEqual(body["summary"]["total_organizations"], 0)

    def test_get_db_connection_does_not_use_parameter_store(self):
        source = Path(api.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import boto3", source)
        self.assertNotIn("get_parameter", source)
        self.assertNotIn("/dev/saayam/db", source)


class ConnectionConfigTests(unittest.TestCase):
    @patch("organization_analytics.psycopg2.connect")
    def test_uses_database_url(self, connect):
        with patch.dict(
            "os.environ", {"DATABASE_URL": "postgresql://u:p@localhost:5432/db"}
        ):
            api.get_db_connection()
        connect.assert_called_once_with("postgresql://u:p@localhost:5432/db")

    @patch("organization_analytics.psycopg2.connect")
    def test_uses_pg_env_vars(self, connect):
        env = {
            "PGHOST": "127.0.0.1",
            "PGPORT": "5433",
            "PGDATABASE": "saayam_local",
            "PGUSER": "analyst",
            "PGPASSWORD": "secret",
        }
        with patch.dict("os.environ", env, clear=True):
            api.get_db_connection()
        kwargs = connect.call_args.kwargs
        self.assertEqual(kwargs["host"], "127.0.0.1")
        self.assertEqual(kwargs["dbname"], "saayam_local")
        self.assertEqual(kwargs["user"], "analyst")


if __name__ == "__main__":
    unittest.main()
