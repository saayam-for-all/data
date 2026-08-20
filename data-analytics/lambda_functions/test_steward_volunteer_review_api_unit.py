"""Mocked unit tests for steward_volunteer_review_api.py.

No database required -- these patch the module's own get_db_connection and hand the handler
a fake cursor. Run from inside this directory, which is how the module import resolves:

    cd data-analytics/lambda_functions
    python -m unittest test_steward_volunteer_review_api_unit -v

WHY WE PATCH get_db_connection AND NOT psycopg2.connect
Patching our own seam keeps the tests honest about the boundary we actually own. If the
connection helper is later changed (say the real `volunteers` table arrives and it needs a
different DSN), these tests keep working because they never assert on psycopg2 internals.

Tests assert against the module's VOLUNTEER SOURCE BINDING constants rather than hardcoding
"volunteer_applications" / "last_updated_at", so they survive the swap to the real
`volunteers` table when it lands.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import steward_volunteer_review_api as api


def make_rows(count, total_records, start=1):
    """Builds RealDictCursor-shaped rows. COUNT(*) OVER() rides along on every row."""
    return [
        {
            "user_id": f"SID-00-000-000-{start + i:03d}",
            "updated_time": f"2026-05-{28 - i:02d}T07:15:00Z",
            "total_records": total_records,
        }
        for i in range(count)
    ]


def make_mock_connection(rows=None, execute_side_effect=None):
    cursor = MagicMock()
    if execute_side_effect is not None:
        cursor.execute.side_effect = execute_side_effect
    cursor.fetchall.return_value = rows if rows is not None else []
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def invoke(event):
    """Calls the handler and returns (statusCode, decoded body)."""
    result = api.lambda_handler(event, None)
    return result["statusCode"], json.loads(result["body"])


class TestNormalizePagination(unittest.TestCase):
    """Pure function, no mocks needed."""

    def test_defaults_when_absent(self):
        self.assertEqual(api.normalize_pagination({}), (1, 5))

    def test_explicit_values_pass_through(self):
        self.assertEqual(api.normalize_pagination({"page": 3, "page_size": 10}), (3, 10))

    def test_numeric_strings_are_coerced(self):
        # API Gateway payloads routinely arrive with numbers as strings.
        self.assertEqual(api.normalize_pagination({"page": "4", "page_size": "20"}), (4, 20))

    def test_zero_and_negative_clamp_to_defaults(self):
        self.assertEqual(api.normalize_pagination({"page": 0, "page_size": 0}), (1, 5))
        self.assertEqual(api.normalize_pagination({"page": -5, "page_size": -1}), (1, 5))

    def test_garbage_falls_back_to_defaults(self):
        self.assertEqual(api.normalize_pagination({"page": "abc", "page_size": None}), (1, 5))
        self.assertEqual(api.normalize_pagination({"page": {}, "page_size": []}), (1, 5))

    def test_page_size_capped_at_max(self):
        # Stops a caller from pulling the whole table in one request.
        _, page_size = api.normalize_pagination({"page_size": 9999})
        self.assertEqual(page_size, api.MAX_PAGE_SIZE)


class TestEventParsing(unittest.TestCase):
    """The handler must accept both API Gateway and direct-invoke shapes."""

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_api_gateway_json_string_body(self, mock_conn):
        mock_conn.return_value = make_mock_connection(make_rows(2, 2))[0]
        status, body = invoke({"body": json.dumps({"page": 1, "page_size": 2})})
        self.assertEqual(status, 200)
        self.assertEqual(body["pagination"]["page_size"], 2)

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_direct_invoke_dict_event(self, mock_conn):
        mock_conn.return_value = make_mock_connection(make_rows(2, 2))[0]
        status, body = invoke({"page": 1, "page_size": 2})
        self.assertEqual(status, 200)
        self.assertEqual(body["pagination"]["page_size"], 2)

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_malformed_json_body_falls_back_to_defaults(self, mock_conn):
        mock_conn.return_value = make_mock_connection(make_rows(5, 5))[0]
        status, body = invoke({"body": "{not valid json"})
        self.assertEqual(status, 200)
        self.assertEqual(body["pagination"]["current_page"], 1)
        self.assertEqual(body["pagination"]["page_size"], 5)


class TestResponseShape(unittest.TestCase):
    """AC: correct user id, correct updated time, and a usable Review action."""

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_standard_payload_returns_expected_shape(self, mock_conn):
        mock_conn.return_value = make_mock_connection(make_rows(5, 20))[0]
        status, body = invoke({"page": 1, "page_size": 5})

        self.assertEqual(status, 200)
        self.assertEqual(set(body.keys()), {"data", "pagination"})
        self.assertEqual(
            set(body["pagination"].keys()),
            {"current_page", "page_size", "total_records", "total_pages"},
        )
        self.assertEqual(len(body["data"]), 5)
        for row in body["data"]:
            self.assertEqual(set(row.keys()), {"user_id", "updated_time", "volunteer_review"})

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_every_row_carries_the_review_action(self, mock_conn):
        # AC: the frontend uses user_id for the Review action.
        mock_conn.return_value = make_mock_connection(make_rows(3, 3))[0]
        _, body = invoke({})
        for row in body["data"]:
            self.assertEqual(row["volunteer_review"], "Review")
            self.assertTrue(row["user_id"])

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_internal_columns_are_not_leaked(self, mock_conn):
        # total_records rides along on every row from COUNT(*) OVER(); it belongs in
        # pagination, not in the per-row payload.
        mock_conn.return_value = make_mock_connection(make_rows(3, 3))[0]
        _, body = invoke({})
        for row in body["data"]:
            self.assertNotIn("total_records", row)

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_body_is_a_json_string_not_a_dict(self, mock_conn):
        # API Gateway proxy integration requires this.
        mock_conn.return_value = make_mock_connection(make_rows(1, 1))[0]
        result = api.lambda_handler({}, None)
        self.assertIsInstance(result["body"], str)
        self.assertIn("Content-Type", result["headers"])


class TestPaginationMath(unittest.TestCase):

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_offset_is_computed_from_page(self, mock_conn):
        conn, cursor = make_mock_connection(make_rows(10, 80))
        mock_conn.return_value = conn
        invoke({"page": 3, "page_size": 10})

        _, params = cursor.execute.call_args[0]
        limit, offset = params[1], params[2]
        self.assertEqual(limit, 10)
        self.assertEqual(offset, 20)  # (3 - 1) * 10

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_first_page_offset_is_zero(self, mock_conn):
        conn, cursor = make_mock_connection(make_rows(5, 80))
        mock_conn.return_value = conn
        invoke({"page": 1, "page_size": 5})

        _, params = cursor.execute.call_args[0]
        self.assertEqual(params[2], 0)

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_total_pages_rounds_up_on_partial_final_page(self, mock_conn):
        # 80 records at 5/page is exactly 16; 81 must round up to 17, not truncate to 16.
        mock_conn.return_value = make_mock_connection(make_rows(5, 81))[0]
        _, body = invoke({"page": 1, "page_size": 5})
        self.assertEqual(body["pagination"]["total_records"], 81)
        self.assertEqual(body["pagination"]["total_pages"], 17)

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_total_pages_exact_multiple(self, mock_conn):
        mock_conn.return_value = make_mock_connection(make_rows(5, 80))[0]
        _, body = invoke({"page": 1, "page_size": 5})
        self.assertEqual(body["pagination"]["total_pages"], 16)

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_requested_page_is_echoed_back(self, mock_conn):
        mock_conn.return_value = make_mock_connection(make_rows(5, 80))[0]
        _, body = invoke({"page": 4, "page_size": 5})
        self.assertEqual(body["pagination"]["current_page"], 4)
        self.assertEqual(body["pagination"]["page_size"], 5)


class TestEmptyResults(unittest.TestCase):
    """AC: empty results return a successful response with an empty array."""

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_no_matching_records_returns_200_and_empty_list(self, mock_conn):
        mock_conn.return_value = make_mock_connection([])[0]
        status, body = invoke({"page": 1, "page_size": 5})

        self.assertEqual(status, 200)
        self.assertEqual(body["data"], [])
        self.assertEqual(body["pagination"]["total_records"], 0)
        self.assertEqual(body["pagination"]["total_pages"], 0)

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_page_past_the_end_returns_200_and_empty_list(self, mock_conn):
        mock_conn.return_value = make_mock_connection([])[0]
        status, body = invoke({"page": 999, "page_size": 5})

        self.assertEqual(status, 200)
        self.assertEqual(body["data"], [])
        self.assertEqual(body["pagination"]["current_page"], 999)


class TestSqlContract(unittest.TestCase):
    """Guards the parts of the query the acceptance criteria depend on."""

    def _executed_sql(self, mock_conn):
        conn, cursor = make_mock_connection(make_rows(5, 80))
        mock_conn.return_value = conn
        invoke({"page": 1, "page_size": 5})
        sql, params = cursor.execute.call_args[0]
        return " ".join(sql.split()), params

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_sorted_by_updated_time_descending(self, mock_conn):
        # AC: records are displayed in descending updated-time order.
        sql, _ = self._executed_sql(mock_conn)
        self.assertIn(f"ORDER BY v.{api.VOLUNTEER_UPDATED_COLUMN} DESC", sql)

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_order_by_has_a_unique_tiebreaker(self, mock_conn):
        # Without this, rows sharing a timestamp can reshuffle between pages, so the same
        # record shows up twice while another is never shown at all.
        sql, _ = self._executed_sql(mock_conn)
        self.assertIn("u.user_id DESC", sql.split("ORDER BY")[1])

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_joins_users_to_the_volunteer_source(self, mock_conn):
        # AC: the API retrieves data from the users and volunteer tables.
        sql, _ = self._executed_sql(mock_conn)
        self.assertIn(api.USERS, sql)
        self.assertIn(api.VOLUNTEER_TABLE, sql)
        self.assertIn(f"JOIN {api.USERS} u ON u.user_id = v.{api.VOLUNTEER_JOIN_COLUMN}", sql)

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_filters_to_review_statuses_via_parameter(self, mock_conn):
        # AC: only volunteer requests requiring review are returned -- and the status list
        # must travel as a bound parameter, not baked into the SQL text.
        sql, params = self._executed_sql(mock_conn)
        self.assertIn("= ANY(%s)", sql)
        self.assertEqual(params[0], list(api.REVIEW_STATUSES))
        for status in api.REVIEW_STATUSES:
            self.assertNotIn(status, sql)

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_pagination_values_are_parameterized(self, mock_conn):
        # The whole point of parameterized SQL: user input never becomes SQL text.
        conn, cursor = make_mock_connection(make_rows(5, 80))
        mock_conn.return_value = conn
        invoke({"page": 7, "page_size": 13})

        sql, params = cursor.execute.call_args[0]
        self.assertIn("LIMIT %s OFFSET %s", " ".join(sql.split()))
        self.assertEqual(params[1:], [13, 78])
        self.assertNotIn("13", sql)
        self.assertNotIn("78", sql)

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_sql_injection_attempt_never_reaches_the_query(self, mock_conn):
        conn, cursor = make_mock_connection([])
        mock_conn.return_value = conn
        status, _ = invoke({"page": "1; DROP TABLE users;--", "page_size": 5})

        sql, params = cursor.execute.call_args[0]
        self.assertEqual(status, 200)
        self.assertNotIn("DROP", sql.upper())
        self.assertEqual(params[2], 0)  # unparseable page fell back to page 1

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_enum_status_column_is_cast_to_text(self, mock_conn):
        # A Postgres enum cannot be compared to a text parameter without an explicit cast.
        sql, _ = self._executed_sql(mock_conn)
        if api.VOLUNTEER_STATUS_IS_ENUM:
            self.assertIn(f"v.{api.VOLUNTEER_STATUS_COLUMN}::text", sql)


class TestDatabaseErrors(unittest.TestCase):
    """AC: database errors return a safe error response."""

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_connection_failure_returns_500_with_safe_shape(self, mock_conn):
        mock_conn.side_effect = Exception("could not connect to server")
        status, body = invoke({"page": 2, "page_size": 5})

        self.assertEqual(status, 500)
        self.assertEqual(body["data"], [])
        self.assertEqual(body["pagination"]["total_records"], 0)
        self.assertEqual(body["pagination"]["total_pages"], 0)
        # The requested paging is still echoed so the frontend can render its controls.
        self.assertEqual(body["pagination"]["current_page"], 2)

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_query_failure_returns_500_with_safe_shape(self, mock_conn):
        conn, _ = make_mock_connection(
            execute_side_effect=Exception('relation "volunteers" does not exist')
        )
        mock_conn.return_value = conn
        status, body = invoke({})

        self.assertEqual(status, 500)
        self.assertEqual(body["data"], [])

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_error_body_leaks_no_internals(self, mock_conn):
        # Exception text can carry host names, credentials and driver internals. It belongs
        # in the log, never in an HTTP response.
        mock_conn.side_effect = Exception("FATAL: password authentication failed for user 'postgres' at 10.0.0.7")
        result = api.lambda_handler({}, None)

        self.assertEqual(result["statusCode"], 500)
        for leak in ("password", "postgres", "10.0.0.7", "FATAL"):
            self.assertNotIn(leak, result["body"])

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_connection_is_closed_even_when_the_query_fails(self, mock_conn):
        conn, cursor = make_mock_connection(execute_side_effect=Exception("boom"))
        mock_conn.return_value = conn
        api.lambda_handler({}, None)

        cursor.close.assert_called_once()
        conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
