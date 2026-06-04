"""
Local Phase 2 tests for application_analytics_request — Issue #146.
Uses mocks so no real DB credentials are needed.

Run with:
    python test_local.py
"""

import sys
import json
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

# boto3 is provided by the AWS Lambda runtime, not bundled. Stub it so the
# module imports locally even when boto3 isn't installed. get_db_config is
# mocked in every test, so the real client is never exercised.
sys.modules.setdefault("boto3", MagicMock())

# Dummy DB config returned in place of the Parameter Store lookup during tests
MOCK_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "testdb",
    "user": "testuser",
    "password": "testpass",
}


# ── helpers ────────────────────────────────────────────────────────────────

REQUIRED_KEYS = {
    "request_volume_7_days",
    "request_volume_1_month",
    "request_volume_1_year",
    "top_countries",
    "requests_by_category_region",
}

# SQL now does the GROUP BY DATE_TRUNC + COUNT itself, so rows come back
# as (truncated_date, count) tuples rather than raw submission_date values.
SAMPLE_DATES = [
    (datetime(2026, 3, 10), 1),
    (datetime(2026, 4, 1), 1),
    (datetime(2026, 4, 5), 2),
]

SAMPLE_CATEGORY_REGION = [
    ("Education", "India", 20),
    ("Healthcare", "United States", 15),
    ("Food", "India", 10),
]

SAMPLE_TOP_COUNTRIES = [
    ("United Kingdom", 111),
    ("India", 95),
    ("United States", 80),
    ("Canada", 45),
    ("Australia", 30),
]


def make_mock_cursor(fetchall_side_effects):
    """Return a mock cursor whose fetchall() cycles through given return values."""
    cursor = MagicMock()
    cursor.fetchall.side_effect = fetchall_side_effects
    return cursor


def make_mock_conn(cursor):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


# ── test cases ─────────────────────────────────────────────────────────────

@patch("application_analytics_request.get_db_config", lambda db: MOCK_CONFIG)
class TestAllKeysPresent(unittest.TestCase):
    """All 5 required keys must always be in the response body."""

    @patch("psycopg2.connect")
    def test_all_keys_present_with_data(self, mock_connect):
        cursor = make_mock_cursor([
            SAMPLE_DATES,           # 7 days
            SAMPLE_DATES,           # 30 days
            SAMPLE_DATES,           # 1 year
            SAMPLE_TOP_COUNTRIES,   # top countries
            SAMPLE_CATEGORY_REGION, # category/region
        ])
        mock_connect.return_value = make_mock_conn(cursor)

        from application_analytics_request import lambda_handler
        result = lambda_handler({}, None)

        self.assertEqual(result["statusCode"], 200)
        body = result["body"]
        for key in REQUIRED_KEYS:
            self.assertIn(key, body, f"Missing key: {key}")

    @patch("psycopg2.connect")
    def test_all_keys_present_on_empty_db(self, mock_connect):
        cursor = make_mock_cursor([[], [], [], [], []])
        mock_connect.return_value = make_mock_conn(cursor)

        from application_analytics_request import lambda_handler
        result = lambda_handler({}, None)

        self.assertEqual(result["statusCode"], 200)
        body = result["body"]
        for key in REQUIRED_KEYS:
            self.assertIn(key, body, f"Missing key on empty DB: {key}")


@patch("application_analytics_request.get_db_config", lambda db: MOCK_CONFIG)
class TestEachKeyReturnsList(unittest.TestCase):
    """Every key must return a list (either populated or [])."""

    @patch("psycopg2.connect")
    def test_returns_list_with_data(self, mock_connect):
        cursor = make_mock_cursor([
            SAMPLE_DATES,
            SAMPLE_DATES,
            SAMPLE_DATES,
            SAMPLE_TOP_COUNTRIES,
            SAMPLE_CATEGORY_REGION,
        ])
        mock_connect.return_value = make_mock_conn(cursor)

        from application_analytics_request import lambda_handler
        body = json.loads(lambda_handler({}, None)["body"])
        for key in REQUIRED_KEYS:
            self.assertIsInstance(body[key], list, f"{key} is not a list")

    @patch("psycopg2.connect")
    def test_returns_empty_list_on_empty_db(self, mock_connect):
        cursor = make_mock_cursor([[], [], [], [], []])
        mock_connect.return_value = make_mock_conn(cursor)

        from application_analytics_request import lambda_handler
        body = json.loads(lambda_handler({}, None)["body"])
        for key in REQUIRED_KEYS:
            self.assertEqual(body[key], [], f"{key} should be [] on empty DB")


@patch("application_analytics_request.get_db_config", lambda db: MOCK_CONFIG)
class TestNoCrashOnEmptyDB(unittest.TestCase):
    """Lambda must not raise — returns 200 with empty lists on empty DB."""

    @patch("psycopg2.connect")
    def test_no_crash_empty_db(self, mock_connect):
        cursor = make_mock_cursor([[], [], [], [], []])
        mock_connect.return_value = make_mock_conn(cursor)

        from application_analytics_request import lambda_handler
        try:
            result = lambda_handler({}, None)
        except Exception as e:
            self.fail(f"lambda_handler raised an exception on empty DB: {e}")

        self.assertEqual(result["statusCode"], 200)

    @patch("psycopg2.connect")
    def test_no_crash_on_query_exception(self, mock_connect):
        """If individual queries fail, still returns 200 with [] for those keys."""
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("query failed")
        mock_connect.return_value = make_mock_conn(cursor)

        from application_analytics_request import lambda_handler
        result = lambda_handler({}, None)
        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        for key in REQUIRED_KEYS:
            self.assertEqual(body[key], [])


@patch("application_analytics_request.get_db_config", lambda db: MOCK_CONFIG)
class TestFilters(unittest.TestCase):
    """Filters passed via event should not crash and return valid structure."""

    @patch("psycopg2.connect")
    def test_filter_by_category(self, mock_connect):
        cursor = make_mock_cursor([
            SAMPLE_DATES,
            SAMPLE_DATES,
            SAMPLE_DATES,
            SAMPLE_TOP_COUNTRIES,
            [("Education", "India", 20)],
        ])
        mock_connect.return_value = make_mock_conn(cursor)

        from application_analytics_request import lambda_handler
        result = lambda_handler({"category": "Education"}, None)
        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertIsInstance(body["requests_by_category_region"], list)

    @patch("psycopg2.connect")
    def test_filter_by_country(self, mock_connect):
        cursor = make_mock_cursor([
            SAMPLE_DATES,
            SAMPLE_DATES,
            SAMPLE_DATES,
            SAMPLE_TOP_COUNTRIES,
            [("Healthcare", "India", 10)],
        ])
        mock_connect.return_value = make_mock_conn(cursor)

        from application_analytics_request import lambda_handler
        result = lambda_handler({"country": "INDIA"}, None)
        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertIsInstance(body["requests_by_category_region"], list)

    @patch("psycopg2.connect")
    def test_sort_by_category(self, mock_connect):
        cursor = make_mock_cursor([
            SAMPLE_DATES,
            SAMPLE_DATES,
            SAMPLE_DATES,
            SAMPLE_TOP_COUNTRIES,
            SAMPLE_CATEGORY_REGION,
        ])
        mock_connect.return_value = make_mock_conn(cursor)

        from application_analytics_request import lambda_handler
        result = lambda_handler({"sort_by": "category"}, None)
        self.assertEqual(result["statusCode"], 200)


@patch("application_analytics_request.get_db_config", lambda db: MOCK_CONFIG)
class TestDBConnectionFailure(unittest.TestCase):
    """If DB connection fails, return 500 with error message — no crash."""

    @patch("psycopg2.connect", side_effect=Exception("could not connect"))
    def test_returns_500_on_connection_failure(self, mock_connect):
        from application_analytics_request import lambda_handler
        result = lambda_handler({}, None)
        self.assertEqual(result["statusCode"], 500)
        body = result["body"]
        self.assertIn("error", body)

    @patch("psycopg2.connect", side_effect=Exception("could not connect"))
    def test_no_crash_on_connection_failure(self, mock_connect):
        from application_analytics_request import lambda_handler
        try:
            lambda_handler({}, None)
        except Exception as e:
            self.fail(f"lambda_handler crashed on DB failure: {e}")


@patch("application_analytics_request.get_db_config", lambda db: MOCK_CONFIG)
class TestConnectionCloses(unittest.TestCase):
    """Cursor and connection must be closed in the finally block."""

    @patch("psycopg2.connect")
    def test_connection_closed_on_success(self, mock_connect):
        cursor = make_mock_cursor([[], [], [], [], []])
        conn = make_mock_conn(cursor)
        mock_connect.return_value = conn

        from application_analytics_request import lambda_handler
        lambda_handler({}, None)

        cursor.close.assert_called_once()
        conn.close.assert_called_once()

    @patch("psycopg2.connect")
    def test_connection_closed_on_query_error(self, mock_connect):
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("query error")
        conn = make_mock_conn(cursor)
        mock_connect.return_value = conn

        from application_analytics_request import lambda_handler
        lambda_handler({}, None)

        conn.close.assert_called_once()


# ── run ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
