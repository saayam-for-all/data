"""Tests for Steward Dashboard volunteer review API (issue #273)."""

import json
import os
import sys

import pytest


LAMBDA_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "lambda_functions",
    )
)

sys.path.insert(0, LAMBDA_DIR)

import steward_volunteer_review_api as api


class FakeCursor:
    """Simple database cursor used for unit testing."""

    def __init__(self, total_records=0, rows=None):
        self.total_records = total_records
        self.rows = rows or []
        self.queries = []
        self._query_number = 0

    def execute(self, query, params=None):
        self.queries.append((query, params))
        self._query_number += 1

    def fetchone(self):
        return (self.total_records,)

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeConnection:
    """Simple database connection used for unit testing."""

    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


def test_review_volunteers_returns_paginated_data():
    cursor = FakeCursor(
        total_records=10,
        rows=[
            (
                "SID-00-000-000-371",
                "2026-06-19T08:13:21Z",
            ),
            (
                "SID-00-000-000-091",
                "2026-06-17T22:16:35Z",
            ),
        ],
    )

    result = api.get_review_volunteers(cursor, 1, 2)

    assert len(result["data"]) == 2
    assert result["data"][0] == {
        "user_id": "SID-00-000-000-371",
        "updated_time": "2026-06-19T08:13:21Z",
        "volunteer_review": "Review",
    }

    assert result["pagination"] == {
        "current_page": 1,
        "page_size": 2,
        "total_records": 10,
        "total_pages": 5,
    }


def test_queries_use_under_review_and_pagination_parameters():
    cursor = FakeCursor(total_records=10)

    api.get_review_volunteers(cursor, 2, 5)

    assert cursor.queries[0][1] == ("UNDER_REVIEW",)
    assert cursor.queries[1][1] == ("UNDER_REVIEW", 5, 5)


def test_empty_results_return_empty_array():
    cursor = FakeCursor(total_records=0, rows=[])

    result = api.get_review_volunteers(cursor, 1, 5)

    assert result["data"] == []
    assert result["pagination"]["total_records"] == 0
    assert result["pagination"]["total_pages"] == 0


def test_invalid_pagination_returns_400():
    response = api.lambda_handler(
        {
            "body": json.dumps(
                {
                    "page": 0,
                    "page_size": 5,
                }
            )
        },
        None,
    )

    assert response["statusCode"] == 400


def test_database_error_returns_safe_response(monkeypatch):
    def raise_database_error():
        raise Exception("private database information")

    monkeypatch.setattr(
        api,
        "get_db_connection",
        raise_database_error,
    )

    response = api.lambda_handler(
        {
            "body": json.dumps(
                {
                    "page": 1,
                    "page_size": 5,
                }
            )
        },
        None,
    )

    body = json.loads(response["body"])

    assert response["statusCode"] == 500
    assert body == {
        "message": "Unable to retrieve volunteer applications"
    }
    assert "private database information" not in response["body"]