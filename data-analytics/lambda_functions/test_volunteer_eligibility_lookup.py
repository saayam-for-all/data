"""Unit tests for volunteer_eligibility_lookup.py (issue #289).

Mock-based, like the other lambda_functions tests in this directory: no
connection to AWS or a real database. This proves request-validation logic,
response shape, and the SQL structure the handler builds (parameterization,
conditional location filtering, status/assignment exclusion) -- it does not
execute the SQL against a real Postgres/PostGIS engine, since no such local
instance exists in this repo yet. Same limitation applies to the other open
PRs for #289 (#303, #306); flagged in the PR description.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

import volunteer_eligibility_lookup as api  # noqa: E402

REQUEST_ID = "REQ-00-000-000-001"


def make_cursor(fetchone_results=None, fetchall_result=None, execute_side_effect=None):
    """A MagicMock cursor with deterministic fetchone()/fetchall() sequencing."""
    cursor = MagicMock()
    if execute_side_effect is not None:
        cursor.execute.side_effect = execute_side_effect
    if fetchone_results is not None:
        cursor.fetchone.side_effect = list(fetchone_results)
    if fetchall_result is not None:
        cursor.fetchall.return_value = fetchall_result
    return cursor


def make_conn(cursor):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


# --- request_id validation ---


def test_missing_request_id_returns_400():
    response = api.lambda_handler({"body": "{}"}, None)
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == "request_id is required"


def test_blank_request_id_returns_400():
    response = api.lambda_handler({"body": json.dumps({"request_id": "   "})}, None)
    assert response["statusCode"] == 400


def test_parse_request_id_accepts_camelcase_alias():
    assert api.parse_request_id({"requestId": REQUEST_ID}) == REQUEST_ID


def test_string_encoded_body_parsed():
    with patch.object(api, "get_db_connection") as mock_get_conn:
        cursor = make_cursor(fetchone_results=[None])
        mock_get_conn.return_value = make_conn(cursor)
        response = api.lambda_handler({"body": json.dumps({"request_id": REQUEST_ID})}, None)
    assert response["statusCode"] == 404


# --- request lookup ---


def test_request_id_not_found_returns_404():
    with patch.object(api, "get_db_connection") as mock_get_conn:
        cursor = make_cursor(fetchone_results=[None])
        mock_get_conn.return_value = make_conn(cursor)
        response = api.lambda_handler({"request_id": REQUEST_ID}, None)
    assert response["statusCode"] == 404


# --- skill matching / result shape ---


def _remote_request_row():
    return {"req_id": REQUEST_ID, "req_user_id": "USR-1", "req_cat_id": "1.3", "req_type": "REMOTE"}


def test_skill_match_multiple_volunteers():
    rows = [
        {"user_id": "VOL-1", "full_name": "Alice", "skills": ["COOKING_HELP"]},
        {"user_id": "VOL-2", "full_name": "Bob", "skills": ["COOKING_HELP"]},
        {"user_id": "VOL-3", "full_name": None, "skills": []},
    ]
    with patch.object(api, "get_db_connection") as mock_get_conn:
        cursor = make_cursor(fetchone_results=[_remote_request_row()], fetchall_result=rows)
        mock_get_conn.return_value = make_conn(cursor)
        response = api.lambda_handler({"request_id": REQUEST_ID}, None)
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert len(body["availableVolunteers"]) == 3
    assert body["availableVolunteers"][2]["name"] == "VOL-3"  # falls back to id when full_name is NULL


def test_skill_match_single_volunteer():
    rows = [{"user_id": "VOL-1", "full_name": "Alice", "skills": ["COOKING_HELP"]}]
    with patch.object(api, "get_db_connection") as mock_get_conn:
        cursor = make_cursor(fetchone_results=[_remote_request_row()], fetchall_result=rows)
        mock_get_conn.return_value = make_conn(cursor)
        response = api.lambda_handler({"request_id": REQUEST_ID}, None)
    assert len(json.loads(response["body"])["availableVolunteers"]) == 1


def test_skill_match_zero_volunteers_returns_empty_200_not_error():
    with patch.object(api, "get_db_connection") as mock_get_conn:
        cursor = make_cursor(fetchone_results=[_remote_request_row()], fetchall_result=[])
        mock_get_conn.return_value = make_conn(cursor)
        response = api.lambda_handler({"request_id": REQUEST_ID}, None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"requestId": REQUEST_ID, "availableVolunteers": []}


# --- location matching (In person vs. Remote) ---


def _in_person_request_row():
    return {"req_id": REQUEST_ID, "req_user_id": "USR-1", "req_cat_id": "1.3", "req_type": "IN_PERSON"}


def test_in_person_request_checks_beneficiary_location_and_applies_st_dwithin():
    volunteer_rows = [{"user_id": "VOL-1", "full_name": "Alice", "skills": ["COOKING_HELP"]}]
    with patch.object(api, "get_db_connection") as mock_get_conn:
        cursor = make_cursor(
            fetchone_results=[_in_person_request_row(), {"has_location": True}],
            fetchall_result=volunteer_rows,
        )
        mock_get_conn.return_value = make_conn(cursor)
        response = api.lambda_handler({"request_id": REQUEST_ID}, None)

    assert response["statusCode"] == 200
    assert len(json.loads(response["body"])["availableVolunteers"]) == 1
    matching_call = cursor.execute.call_args_list[-1]
    sql, params = matching_call.args
    assert "ST_DWithin" in sql
    assert "volunteer_locations" in sql
    assert params["radius_meters"] == api.DEFAULT_MATCH_RADIUS_METERS


def test_in_person_request_missing_beneficiary_location_returns_empty_not_error():
    with patch.object(api, "get_db_connection") as mock_get_conn:
        cursor = make_cursor(fetchone_results=[_in_person_request_row(), {"has_location": False}])
        mock_get_conn.return_value = make_conn(cursor)
        response = api.lambda_handler({"request_id": REQUEST_ID}, None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["availableVolunteers"] == []
    # only the request lookup + beneficiary-location precheck ran; no matching query
    assert cursor.execute.call_count == 2


def test_in_person_request_volunteer_missing_geolocation_excluded_via_inner_join():
    sql = api.build_matching_sql(is_in_person=True)
    assert "JOIN " + api.VOLUNTEER_LOCATIONS_TABLE in sql
    assert "LEFT JOIN " + api.VOLUNTEER_LOCATIONS_TABLE not in sql


def test_remote_request_sql_excludes_location_filter_entirely():
    sql = api.build_matching_sql(is_in_person=False)
    assert "ST_DWithin" not in sql
    assert "volunteer_locations" not in sql


def test_remote_request_does_not_check_beneficiary_location():
    with patch.object(api, "get_db_connection") as mock_get_conn:
        cursor = make_cursor(fetchone_results=[_remote_request_row()], fetchall_result=[])
        mock_get_conn.return_value = make_conn(cursor)
        api.lambda_handler({"request_id": REQUEST_ID}, None)
    # only the request lookup + the matching query ran (no beneficiary-location precheck)
    assert cursor.execute.call_count == 2


# --- status filtering / already-assigned exclusion ---


def test_sql_filters_on_active_status():
    sql = api.build_matching_sql(is_in_person=False)
    assert "user_status" in sql
    assert "%(active_status)s" in sql


def test_sql_excludes_already_assigned_volunteers():
    sql = api.build_matching_sql(is_in_person=False)
    assert "volunteers_assigned" in sql
    assert "NOT EXISTS" in sql


# --- category hierarchy matching ---


def test_sql_uses_recursive_category_hierarchy_not_exact_match_only():
    sql = api.build_matching_sql(is_in_person=False)
    assert "WITH RECURSIVE" in sql
    assert "help_categories_map" in sql
    assert "%(req_cat_id)s" in sql


# --- no N+1 ---


def test_single_matching_query_regardless_of_result_size():
    rows = [{"user_id": f"VOL-{i}", "full_name": "X", "skills": []} for i in range(25)]
    with patch.object(api, "get_db_connection") as mock_get_conn:
        cursor = make_cursor(fetchone_results=[_remote_request_row()], fetchall_result=rows)
        mock_get_conn.return_value = make_conn(cursor)
        api.lambda_handler({"request_id": REQUEST_ID}, None)
    # one call for the request lookup + one for the matching query, independent of row count
    assert cursor.execute.call_count == 2


# --- failure handling ---


def test_db_connection_exception_returns_500():
    with patch.object(api, "get_db_connection", side_effect=RuntimeError("connection refused")):
        response = api.lambda_handler({"request_id": REQUEST_ID}, None)
    assert response["statusCode"] == 500


def test_db_query_exception_returns_500_and_closes_connections():
    with patch.object(api, "get_db_connection") as mock_get_conn:
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("syntax error")
        conn = make_conn(cursor)
        mock_get_conn.return_value = conn
        response = api.lambda_handler({"request_id": REQUEST_ID}, None)
    assert response["statusCode"] == 500
    cursor.close.assert_called_once()
    conn.close.assert_called_once()


# --- schema-name allowlisting (defense in depth against SQL-identifier injection) ---


def test_resolve_schema_name_allows_known_schema():
    assert api.resolve_schema_name("ireland_dev_saayam_rdbms") == "ireland_dev_saayam_rdbms"


def test_resolve_schema_name_falls_back_on_invalid_input():
    assert api.resolve_schema_name("virginia_dev; DROP TABLE users;--") == api.DEFAULT_SCHEMA_NAME
    assert api.resolve_schema_name("") == api.DEFAULT_SCHEMA_NAME


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
