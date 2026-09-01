"""
Unit tests for steward_volunteer_review_api.py (issue #273).

The users / volunteer_applications tables aren't reachable in CI, so these
mock the DB layer with a fake cursor and connection - the same pattern used
by data-engineering/tests/test_organization_analytics.py. Run with:

    pytest data-analytics/lambda_functions/tests/test_steward_volunteer_review_api.py

Test names map onto the issue's acceptance criteria: correct user id, correct
updated time, review-only filtering, descending order, pagination, empty
results, and safe handling of database errors.
"""
import datetime
import json
import os
import sys
from unittest.mock import patch

import pytest

# Works whether this file sits in tests/ or beside the module.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (_HERE, os.path.join(_HERE, "..")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import steward_volunteer_review_api as api


class FakeCursor:
    """
    Stand-in for a psycopg2 RealDictCursor. Records every query and its
    params so tests can assert the SQL stayed parameterized, and serves
    canned fetchone/fetchall results in call order.
    """

    def __init__(self, fetchone_results=None, fetchall_results=None):
        self._fetchone_results = list(fetchone_results or [])
        self._fetchall_results = list(fetchall_results or [])
        self.queries = []
        self.closed = False

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return self._fetchone_results.pop(0) if self._fetchone_results else None

    def fetchall(self):
        return self._fetchall_results.pop(0) if self._fetchall_results else []

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


def make_row(user_id, updated_time):
    return {"user_id": user_id, "updated_time": updated_time}


# --- parse_event_body -------------------------------------------------

def test_parse_event_body_handles_api_gateway_json_string():
    event = {"body": json.dumps({"page": 2, "page_size": 5})}
    assert api.parse_event_body(event) == {"page": 2, "page_size": 5}


def test_parse_event_body_handles_direct_invocation_dict():
    event = {"page": 3, "page_size": 20}
    assert api.parse_event_body(event) == event


def test_parse_event_body_handles_malformed_json():
    assert api.parse_event_body({"body": "{not valid json"}) == {}


def test_parse_event_body_handles_non_object_json_body():
    # Valid JSON, wrong shape - must not blow up downstream .get() calls.
    assert api.parse_event_body({"body": "[1, 2, 3]"}) == {}


def test_parse_event_body_handles_empty_event():
    assert api.parse_event_body({}) == {}
    assert api.parse_event_body(None) == {}


# --- get_pagination_params --------------------------------------------

def test_pagination_defaults_when_missing():
    assert api.get_pagination_params({}) == (api.DEFAULT_PAGE, api.DEFAULT_PAGE_SIZE)


def test_pagination_uses_provided_values():
    assert api.get_pagination_params({"page": 3, "page_size": 25}) == (3, 25)


def test_pagination_rejects_non_positive_page():
    assert api.get_pagination_params({"page": 0})[0] == api.DEFAULT_PAGE
    assert api.get_pagination_params({"page": -5})[0] == api.DEFAULT_PAGE


def test_pagination_rejects_non_positive_page_size():
    assert api.get_pagination_params({"page_size": 0})[1] == api.DEFAULT_PAGE_SIZE


def test_pagination_clamps_page_size_to_max():
    assert api.get_pagination_params({"page_size": 9999})[1] == api.MAX_PAGE_SIZE


def test_pagination_falls_back_on_non_numeric_values():
    result = api.get_pagination_params({"page": "abc", "page_size": "xyz"})
    assert result == (api.DEFAULT_PAGE, api.DEFAULT_PAGE_SIZE)


# --- timestamp formatting ---------------------------------------------

def test_naive_timestamp_is_rendered_as_utc_iso8601():
    value = datetime.datetime(2026, 5, 12, 7, 15, 0)
    assert api._to_iso_utc(value) == "2026-05-12T07:15:00Z"


def test_aware_timestamp_is_converted_to_utc():
    tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    value = datetime.datetime(2026, 5, 12, 12, 45, 0, tzinfo=tz)
    assert api._to_iso_utc(value) == "2026-05-12T07:15:00Z"


def test_microseconds_are_dropped_to_match_the_contract():
    value = datetime.datetime(2026, 5, 12, 7, 15, 0, 123456)
    assert api._to_iso_utc(value) == "2026-05-12T07:15:00Z"


def test_null_timestamp_stays_null():
    assert api._to_iso_utc(None) is None


# --- SQL construction -------------------------------------------------

def test_schema_name_is_validated_before_interpolation():
    with patch.object(api, "SCHEMA_NAME", "public; DROP TABLE users; --"):
        with pytest.raises(ValueError):
            api._review_source_sql()


def test_source_sql_joins_both_tables_and_filters_by_status():
    sql = api._review_source_sql()
    assert "users u" in sql
    assert "volunteer_applications va" in sql
    assert "ON u.user_id = va.user_id" in sql
    assert "application_status" in sql
    # Status values are bound, never written into the string.
    assert "UNDER_REVIEW" not in sql


def test_count_and_page_queries_share_the_same_filter():
    """
    Guards against the two queries drifting apart, which would report a
    total that doesn't match the rows actually returned.
    """
    cursor = FakeCursor(fetchone_results=[{"total": 3}], fetchall_results=[[]])
    api.get_total_review_count(cursor)
    api.get_volunteer_reviews(cursor, page=1, page_size=10)

    fragment = api._review_source_sql()
    count_query, count_params = cursor.queries[0]
    page_query, page_params = cursor.queries[1]

    assert fragment in count_query
    assert fragment in page_query
    assert count_params[0] == page_params[0] == list(api.REVIEW_STATUSES)


# --- get_total_review_count -------------------------------------------

def test_total_count_returns_zero_when_no_rows():
    assert api.get_total_review_count(FakeCursor(fetchone_results=[{"total": 0}])) == 0


def test_total_count_returns_int_count():
    assert api.get_total_review_count(FakeCursor(fetchone_results=[{"total": 42}])) == 42


def test_total_count_handles_missing_row():
    assert api.get_total_review_count(FakeCursor()) == 0


# --- get_volunteer_reviews --------------------------------------------

def test_reviews_bind_limit_and_offset_as_parameters():
    cursor = FakeCursor(fetchall_results=[[]])
    api.get_volunteer_reviews(cursor, page=3, page_size=10)

    query, params = cursor.queries[0]
    assert "LIMIT %s OFFSET %s" in query
    assert params[1:] == (10, 20)  # page_size, offset for page 3
    assert "LIMIT 10" not in query


def test_reviews_are_ordered_newest_first_with_a_stable_tiebreaker():
    cursor = FakeCursor(fetchall_results=[[]])
    api.get_volunteer_reviews(cursor, page=1, page_size=10)

    query, _ = cursor.queries[0]
    assert "ORDER BY va.last_updated_at DESC NULLS LAST, va.user_id DESC" in query


def test_reviews_map_to_the_three_contract_fields():
    row = make_row("SID-00-000-000-001", datetime.datetime(2026, 5, 12, 7, 15, 0))
    cursor = FakeCursor(fetchall_results=[[row]])

    assert api.get_volunteer_reviews(cursor, page=1, page_size=5) == [
        {
            "user_id": "SID-00-000-000-001",
            "updated_time": "2026-05-12T07:15:00Z",
            "volunteer_review": "Review",
        }
    ]


def test_volunteer_review_is_a_constant_action_label():
    rows = [make_row("SID-1", datetime.datetime(2026, 1, 1)),
            make_row("SID-2", datetime.datetime(2026, 1, 2))]
    cursor = FakeCursor(fetchall_results=[rows])

    result = api.get_volunteer_reviews(cursor, page=1, page_size=5)
    assert {r["volunteer_review"] for r in result} == {api.VOLUNTEER_REVIEW_ACTION}


def test_reviews_handle_null_timestamp():
    cursor = FakeCursor(fetchall_results=[[make_row("SID-2", None)]])
    assert api.get_volunteer_reviews(cursor, 1, 10)[0]["updated_time"] is None


def test_reviews_return_empty_list_when_no_rows():
    assert api.get_volunteer_reviews(FakeCursor(fetchall_results=[[]]), 1, 10) == []


# --- lambda_handler ---------------------------------------------------

@patch.object(api, "get_db_connection")
def test_handler_returns_the_issue_contract_shape(mock_get_conn):
    rows = [make_row("SID-00-000-000-001", datetime.datetime(2026, 5, 12, 7, 15, 0))]
    cursor = FakeCursor(fetchone_results=[{"total": 20}], fetchall_results=[rows])
    mock_get_conn.return_value = FakeConnection(cursor)

    response = api.lambda_handler({"page": 1, "page_size": 5}, None)
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["data"] == [
        {
            "user_id": "SID-00-000-000-001",
            "updated_time": "2026-05-12T07:15:00Z",
            "volunteer_review": "Review",
        }
    ]
    assert body["pagination"] == {
        "current_page": 1,
        "page_size": 5,
        "total_records": 20,
        "total_pages": 4,
    }


@patch.object(api, "get_db_connection")
def test_handler_accepts_an_api_gateway_string_body(mock_get_conn):
    cursor = FakeCursor(fetchone_results=[{"total": 0}])
    mock_get_conn.return_value = FakeConnection(cursor)

    response = api.lambda_handler({"body": json.dumps({"page": 2, "page_size": 5})}, None)
    body = json.loads(response["body"])

    assert body["pagination"]["current_page"] == 2
    assert body["pagination"]["page_size"] == 5


@patch.object(api, "get_db_connection")
def test_handler_returns_empty_array_when_no_records(mock_get_conn):
    cursor = FakeCursor(fetchone_results=[{"total": 0}])
    mock_get_conn.return_value = FakeConnection(cursor)

    response = api.lambda_handler({}, None)
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["data"] == []
    assert body["pagination"]["total_records"] == 0
    assert body["pagination"]["total_pages"] == 0


@patch.object(api, "get_db_connection")
def test_handler_computes_total_pages_correctly(mock_get_conn):
    cursor = FakeCursor(fetchone_results=[{"total": 25}], fetchall_results=[[]])
    mock_get_conn.return_value = FakeConnection(cursor)

    response = api.lambda_handler({"page": 1, "page_size": 10}, None)
    assert json.loads(response["body"])["pagination"]["total_pages"] == 3


@patch.object(api, "get_db_connection")
def test_handler_returns_empty_page_past_the_last_page(mock_get_conn):
    cursor = FakeCursor(fetchone_results=[{"total": 20}], fetchall_results=[[]])
    mock_get_conn.return_value = FakeConnection(cursor)

    response = api.lambda_handler({"page": 99, "page_size": 5}, None)
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["data"] == []
    assert body["pagination"]["total_records"] == 20
    assert body["pagination"]["current_page"] == 99


@patch.object(api, "get_db_connection")
def test_handler_returns_safe_response_on_db_error(mock_get_conn):
    mock_get_conn.side_effect = Exception("FATAL: password authentication failed")

    response = api.lambda_handler({"page": 1, "page_size": 10}, None)
    body = json.loads(response["body"])

    assert response["statusCode"] == 500
    assert body["data"] == []
    assert body["pagination"]["total_records"] == 0
    # The database message must not reach the client.
    assert "password" not in response["body"]


@patch.object(api, "get_db_connection")
def test_handler_returns_safe_response_on_bad_schema_config(mock_get_conn):
    cursor = FakeCursor(fetchone_results=[{"total": 5}])
    mock_get_conn.return_value = FakeConnection(cursor)

    with patch.object(api, "SCHEMA_NAME", "bad-schema-name"):
        response = api.lambda_handler({}, None)

    assert response["statusCode"] == 500
    assert json.loads(response["body"])["data"] == []


@patch.object(api, "get_db_connection")
def test_handler_closes_cursor_and_connection(mock_get_conn):
    cursor = FakeCursor(fetchone_results=[{"total": 0}])
    conn = FakeConnection(cursor)
    mock_get_conn.return_value = conn

    api.lambda_handler({}, None)

    assert cursor.closed is True
    assert conn.closed is True


@patch.object(api, "get_db_connection")
def test_handler_closes_connection_even_when_the_query_fails(mock_get_conn):
    cursor = FakeCursor()
    cursor.execute = lambda *a, **kw: (_ for _ in ()).throw(Exception("query blew up"))
    conn = FakeConnection(cursor)
    mock_get_conn.return_value = conn

    response = api.lambda_handler({}, None)

    assert response["statusCode"] == 500
    assert cursor.closed is True
    assert conn.closed is True
