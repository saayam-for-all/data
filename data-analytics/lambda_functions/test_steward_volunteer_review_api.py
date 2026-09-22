"""Local unit tests for the Issue #273 Steward Dashboard Lambda API."""

import json
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
import steward_volunteer_review_api as api


class FakeCursor:
    """Small cursor double that records the query and returns supplied rows."""

    def __init__(self, rows):
        self.rows = rows
        self.executions = []
        self.closed = False

    def execute(self, query, params):
        self.executions.append((query, params))

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


class FakeConnection:
    """Small connection double for cursor-based local tests."""

    def __init__(self, rows):
        self.cursor_instance = FakeCursor(rows)
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


class StewardVolunteerReviewApiTests(unittest.TestCase):
    def make_connect_region(self, virginia_rows, ireland_rows=None):
        """Return a region connection factory and its connections for assertions."""
        virginia = FakeConnection(virginia_rows)
        ireland = FakeConnection(ireland_rows or []) if ireland_rows is not None else None

        def connect_region(parameter_env_var):
            if parameter_env_var == "VIRGINIA_DB_PARAM":
                return virginia
            return ireland

        return connect_region, virginia, ireland

    def invoke(self, connect_region, event=None):
        with patch.object(api, "connect_region", side_effect=connect_region):
            return api.lambda_handler(event or {"page": 1, "page_size": 5}, None)

    def test_returns_descending_page_with_expected_fields(self):
        rows = [
            ("SID-2", datetime(2026, 5, 10, 7, 15)),
            ("SID-1", datetime(2026, 5, 12, 7, 15)),
        ]
        connect, _, _ = self.make_connect_region(rows)
        response = self.invoke(connect)
        body = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual([row["user_id"] for row in body["data"]], ["SID-1", "SID-2"])
        self.assertEqual(body["data"][0]["updated_time"], "2026-05-12T07:15:00Z")
        self.assertEqual(body["data"][0]["volunteer_review"], "Review")

    def test_uses_parameterized_status_filter(self):
        connect, virginia, _ = self.make_connect_region([])
        self.invoke(connect)
        query, params = virginia.cursor_instance.executions[0]

        self.assertIn("va.application_status = %s", query)
        self.assertEqual(params, ("UNDER_REVIEW",))

    def test_pagination_and_page_size_selection(self):
        rows = [(f"SID-{number}", datetime(2026, 5, number, 7, 15)) for number in range(1, 7)]
        connect, _, _ = self.make_connect_region(rows)
        response = self.invoke(connect, {"page": 2, "page_size": 2})
        body = json.loads(response["body"])

        self.assertEqual(len(body["data"]), 2)
        self.assertEqual(body["pagination"], {
            "current_page": 2,
            "page_size": 2,
            "total_records": 6,
            "total_pages": 3,
        })

    def test_merges_regions_before_paginating(self):
        connect, _, _ = self.make_connect_region(
            [("SID-VA", datetime(2026, 5, 10, 7, 15))],
            [("SID-IE", datetime(2026, 5, 12, 7, 15))],
        )
        response = self.invoke(connect)
        body = json.loads(response["body"])

        self.assertEqual([row["user_id"] for row in body["data"]], ["SID-IE", "SID-VA"])

    def test_empty_queue_is_successful(self):
        connect, _, _ = self.make_connect_region([])
        response = self.invoke(connect)
        body = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["data"], [])
        self.assertEqual(body["pagination"]["total_records"], 0)

    def test_database_error_is_safe(self):
        def fail_to_connect(_):
            raise RuntimeError("sensitive connection details")

        response = self.invoke(fail_to_connect)
        body = json.loads(response["body"])

        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(body["data"], [])
        self.assertNotIn("sensitive", response["body"])

    def test_parses_api_gateway_body_and_clamps_bad_pagination(self):
        connect, _, _ = self.make_connect_region([])
        response = self.invoke(connect, {"body": json.dumps({"page": 0, "page_size": 999})})
        body = json.loads(response["body"])

        self.assertEqual(body["pagination"]["current_page"], 1)
        self.assertEqual(body["pagination"]["page_size"], api.MAX_PAGE_SIZE)

    def test_status_can_be_configured_for_the_target_environment(self):
        connect, virginia, _ = self.make_connect_region([])
        with patch.dict(os.environ, {"VOLUNTEER_REVIEW_STATUS": "IN_REVIEW"}):
            self.invoke(connect)

        self.assertEqual(virginia.cursor_instance.executions[0][1], ("IN_REVIEW",))


if __name__ == "__main__":
    unittest.main()
