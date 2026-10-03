"""
Unit tests for steward_volunteer_review_api.py (issue #273).

The users / volunteer_applications tables aren't reachable in CI, so these
mock the DB layer (get_db_connection) with a fake cursor/connection, the
same pattern used elsewhere in this repo for lambda + DB tests. Run with:

    pytest data-analytics/lambda_functions/tests/test_steward_volunteer_review_api.py
"""
import datetime
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import steward_volunteer_review_api as api


class FakeCursor:
    """
    Minimal stand-in for a psycopg2 RealDictCursor. Records every query
    and its params so tests can assert the SQL stayed parameterized, and
    serves canned results for fetchone/fetchall in call order.
    """

    def __init__(self, fetchone_results=None, fetchall_results=None):
        self._fetchone_results = list(fetchone_results or [])
        self._fetchall_results = list(fetchall_results or [])
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return self._fetchone_results.pop(0) if self._fetchone_results else None

    def fetchall(self):
        return self._fetchall_results.pop(0) if self._fetchall_results else []

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, cursor_factory=None):
        return self._cursor

    def close(self):
        pass


def make_row(user_id, last_updated_at, review_action):
    return {
        "user_id": user_id,
        "last_updated_at": last_updated_at,
        "review_action": review_action,
    }


# --- parse_event_body -------------------------------------------------

def test_parse_event_body_handles_api_gateway_json_string():
    event = {"body": json.dumps({"page": 2, "page_size": 5})}
    assert api.parse_event_body(event) == {"page": 2, "page_size": 5}


def test_parse_event_body_handles_direct_invocation_dict():
    event = {"page": 3, "page_size": 20}
    assert api.parse_event_body(event) == event


def test_parse_event_body_handles_malformed_json():
    event = {"body": "{not valid json"}
    assert api.parse_event_body(event) == {}


def test_parse_event_body_handles_empty_event():
    assert api.parse_event_body({}) == {}
    assert api.parse_event_body(None) == {}


# --- get_pagination_params --------------------------------------------

def test_pagination_defaults_when_missing():
    page, page_size = api.get_pagination_params({})
    assert (page, page_size) == (api.DEFAULT_PAGE, api.DEFAULT_PAGE_SIZE)


def test_pagination_uses_provided_values():
    page, page_size = api.get_pagination_params({"page": 3, "page_size": 25})
    assert (page, page_size) == (3, 25)


def test_pagination_rejects_non_positive_page():
    page, _ = api.get_pagination_params({"page": 0})
    assert page == api.DEFAULT_PAGE
    page, _ = api.get_pagination_params({"page": -5})
    assert page == api.DEFAULT_PAGE


def test_pagination_clamps_page_size_to_max():
    _, page_size = api.get_pagination_params({"page_size": 9999})
    assert page_size == api.MAX_PAGE_SIZE


def test_pagination_falls_back_on_non_numeric_values():
    page, page_size = api.get_pagination_params({"page": "abc", "page_size": "xyz"})
    assert (page, page_size) == (api.DEFAULT_PAGE, api.DEFAULT_PAGE_SIZE)


# --- get_total_review_count / get_volunteer_reviews --------------------

def test_get_total_review_count_returns_zero_when_no_rows():
    cursor = FakeCursor(fetchone_results=[{"total": 0}])
    assert api.get_total_review_count(cursor) == 0


def test_get_total_review_count_returns_int_count():
    cursor = FakeCursor(fetchone_results=[{"total": 42}])
    assert api.get_total_review_count(cursor) == 42


def test_get_volunteer_reviews_uses_parameterized_limit_offset():
    now = datetime.datetime(2026, 2, 22, 4, 23, 8)
    cursor = FakeCursor(fetchall_results=[[make_row("SID-1", now, "UNDER_REVIEW")]])

    result = api.get_volunteer_reviews(cursor, page=2, page_size=10)

    query, params = cursor.queries[0]
    assert params == (10, 10)  # page_size, offset for page 2
    assert "LIMIT %s OFFSET %s" in query
    assert "JOIN" in query and "volunteer_applications" in query
    assert result == [
        {"user_id": "SID-1", "last_updated_at": "2026-02-22T04:23:08", "review_action": "UNDER_REVIEW"}
    ]


def test_get_volunteer_reviews_handles_null_timestamp():
    cursor = FakeCursor(fetchall_results=[[make_row("SID-2", None, "SUBMITTED")]])
    result = api.get_volunteer_reviews(cursor, page=1, page_size=10)
    assert result[0]["last_updated_at"] is None


def test_get_volunteer_reviews_returns_empty_list_when_no_rows():
    cursor = FakeCursor(fetchall_results=[[]])
    result = api.get_volunteer_reviews(cursor, page=1, page_size=10)
    assert result == []


# --- lambda_handler (end to end with a fake DB layer) -------------------

@patch.object(api, "get_db_connection")
def test_lambda_handler_returns_paginated_data(mock_get_conn):
    now = datetime.datetime(2026, 2, 22, 4, 23, 8)
    cursor = FakeCursor(
        fetchone_results=[{"total": 1}],
        fetchall_results=[[make_row("SID-1", now, "APPROVED")]],
    )
    mock_get_conn.return_value = FakeConnection(cursor)

    response = api.lambda_handler({"page": 1, "page_size": 10}, None)
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["data"] == [
        {"user_id": "SID-1", "last_updated_at": "2026-02-22T04:23:08", "review_action": "APPROVED"}
    ]
    assert body["pagination"] == {
        "page": 1, "page_size": 10, "total_records": 1, "total_pages": 1
    }


@patch.object(api, "get_db_connection")
def test_lambda_handler_returns_empty_array_when_no_records(mock_get_conn):
    cursor = FakeCursor(fetchone_results=[{"total": 0}])
    mock_get_conn.return_value = FakeConnection(cursor)

    response = api.lambda_handler({}, None)
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["data"] == []
    assert body["pagination"]["total_records"] == 0
    assert body["pagination"]["total_pages"] == 0


@patch.object(api, "get_db_connection")
def test_lambda_handler_computes_total_pages_correctly(mock_get_conn):
    cursor = FakeCursor(
        fetchone_results=[{"total": 25}],
        fetchall_results=[[]],
    )
    mock_get_conn.return_value = FakeConnection(cursor)

    response = api.lambda_handler({"page": 1, "page_size": 10}, None)
    body = json.loads(response["body"])

    assert body["pagination"]["total_pages"] == 3  # ceil(25 / 10)


@patch.object(api, "get_db_connection")
def test_lambda_handler_returns_500_and_safe_response_on_db_error(mock_get_conn):
    mock_get_conn.side_effect = Exception("connection refused")

    response = api.lambda_handler({"page": 1, "page_size": 10}, None)
    body = json.loads(response["body"])

    assert response["statusCode"] == 500
    assert body["data"] == []
    assert body["pagination"]["total_records"] == 0


@patch.object(api, "get_db_connection")
def test_lambda_handler_closes_cursor_and_connection(mock_get_conn):
    cursor = FakeCursor(fetchone_results=[{"total": 0}])
    conn = FakeConnection(cursor)
    mock_get_conn.return_value = conn

    closed = {"cursor": False, "conn": False}
    cursor.close = lambda: closed.__setitem__("cursor", True)
    conn.close = lambda: closed.__setitem__("conn", True)

    api.lambda_handler({}, None)

    assert closed == {"cursor": True, "conn": True}