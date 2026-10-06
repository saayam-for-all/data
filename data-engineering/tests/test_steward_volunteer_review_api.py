"""Tests for the Steward Dashboard Review Volunteers API (issue #273).

The users / volunteer_applications tables aren't reachable in CI, so these
mock the DB layer (helpers.get_db_connection) the same way CONTRIBUTING.md
asks contributors to mock AWS/DB calls for local-only development. For a
real end-to-end check against Postgres, run
`docker compose -f infrastructure/docker-compose.yml up db` (seeds
infrastructure/db/init/002_steward_volunteer_review.sql) and invoke
lambda_handler with DB_HOST=localhost (and friends) set, no DB_CREDENTIALS_PARAM.
"""
import json
import os
import sys
from datetime import datetime, timezone

import psycopg2
import pytest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "src", "steward-volunteer-review"),
)

import helpers  # noqa: E402
import steward_volunteer_review_api as api  # noqa: E402


class FakeCursor:
    def __init__(self, count_result, rows):
        self._count_result = count_result
        self._rows = rows
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return (self._count_result,)

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class RaisingConnection:
    def cursor(self):
        raise psycopg2.OperationalError("connection refused at 10.0.0.5:5432")

    def close(self):
        pass


def invoke(monkeypatch, connection, body, wrap_in_body=True):
    monkeypatch.setattr(helpers, "get_db_connection", lambda: connection)
    event = {"body": json.dumps(body)} if wrap_in_body else body
    return api.lambda_handler(event, None)


def test_matches_documented_request_and_response_shape(monkeypatch):
    updated = datetime(2026, 5, 12, 7, 15, tzinfo=timezone.utc)
    cursor = FakeCursor(count_result=20, rows=[("SID-00-000-000-001", updated)])
    conn = FakeConnection(cursor)

    resp = invoke(monkeypatch, conn, {"page": 1, "page_size": 5}, wrap_in_body=False)

    assert resp["statusCode"] == 200
    payload = json.loads(resp["body"])
    assert payload == {
        "data": [
            {
                "user_id": "SID-00-000-000-001",
                "updated_time": "2026-05-12T07:15:00+00:00",
                "volunteer_review": "Review",
            }
        ],
        "pagination": {
            "current_page": 1,
            "page_size": 5,
            "total_records": 20,
            "total_pages": 4,
        },
    }
    assert conn.closed is True


def test_empty_results_return_empty_array(monkeypatch):
    cursor = FakeCursor(count_result=0, rows=[])
    conn = FakeConnection(cursor)

    resp = invoke(monkeypatch, conn, {"page": 1, "page_size": 5})

    assert resp["statusCode"] == 200
    payload = json.loads(resp["body"])
    assert payload["data"] == []
    assert payload["pagination"]["total_records"] == 0
    assert payload["pagination"]["total_pages"] == 0


def test_defaults_page_and_page_size_when_omitted(monkeypatch):
    cursor = FakeCursor(count_result=0, rows=[])
    conn = FakeConnection(cursor)

    resp = invoke(monkeypatch, conn, {})

    assert resp["statusCode"] == 200
    payload = json.loads(resp["body"])
    assert payload["pagination"]["current_page"] == 1
    assert payload["pagination"]["page_size"] == helpers.DEFAULT_PAGE_SIZE


def test_second_page_uses_correct_offset(monkeypatch):
    cursor = FakeCursor(count_result=12, rows=[])
    conn = FakeConnection(cursor)

    invoke(monkeypatch, conn, {"page": 2, "page_size": 5})

    _, select_params = cursor.queries[-1]
    assert select_params[-2:] == (5, 5)  # LIMIT 5 OFFSET 5


def test_query_filters_sorts_and_is_parameterized(monkeypatch):
    cursor = FakeCursor(count_result=0, rows=[])
    conn = FakeConnection(cursor)

    invoke(monkeypatch, conn, {"page": 1, "page_size": 5})

    count_query, count_params = cursor.queries[0]
    select_query, select_params = cursor.queries[1]

    assert "JOIN" in count_query and "application_status = ANY(%s)" in count_query
    assert count_params == (helpers.REVIEW_STATUSES,)

    assert "ORDER BY va.last_updated_at DESC" in select_query
    assert "LIMIT %s OFFSET %s" in select_query
    assert select_params == (helpers.REVIEW_STATUSES, 5, 0)


@pytest.mark.parametrize("body", [{"page": 0, "page_size": 5}, {"page": "x", "page_size": 5}])
def test_invalid_page_returns_400(monkeypatch, body):
    resp = invoke(monkeypatch, FakeConnection(FakeCursor(0, [])), body)
    assert resp["statusCode"] == 400


@pytest.mark.parametrize("body", [{"page": 1, "page_size": 0}, {"page": 1, "page_size": 1000}])
def test_invalid_page_size_returns_400(monkeypatch, body):
    resp = invoke(monkeypatch, FakeConnection(FakeCursor(0, [])), body)
    assert resp["statusCode"] == 400


def test_invalid_json_body_returns_400():
    resp = api.lambda_handler({"body": "{not valid json"}, None)
    assert resp["statusCode"] == 400


def test_database_error_returns_safe_response_without_leaking_details(monkeypatch):
    monkeypatch.setattr(helpers, "get_db_connection", lambda: RaisingConnection())

    resp = api.lambda_handler({"body": json.dumps({"page": 1, "page_size": 5})}, None)

    assert resp["statusCode"] == 500
    assert json.loads(resp["body"]) == {"error": "Internal server error"}
    assert "10.0.0.5" not in resp["body"]
    assert "connection refused" not in resp["body"]
