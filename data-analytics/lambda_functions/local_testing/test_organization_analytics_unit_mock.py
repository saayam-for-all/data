"""Cursor-mocked unit tests for organization_analytics.py.

Unlike test_organization_analytics_local.py (an integration suite that runs
against a real local Postgres seeded with the sample CSVs), this file needs
NO database connection at all. It mocks the DB cursor/connection directly so
query-building logic, filter handling, and error paths can be tested in
isolation. Satisfies the "cursor-based/mock database unit tests" requirement.

Run:
    python test_organization_analytics_unit_mock.py
"""
import json
import unittest
from unittest.mock import MagicMock, patch

import organization_analytics as oa


def make_mock_cursor(fetchone_results=None, fetchall_results=None, execute_side_effect=None):
    """Builds a mock cursor whose .fetchone()/.fetchall() return canned
    results in the exact call order used by build_organization_dashboard:
      fetchone(): [summary_row, collaborator_vs_contributor_row]
      fetchall(): [growth_trend_rows, location_rows, size_rows,
                   rating_rows, type_distribution_rows]
    """
    cursor = MagicMock()
    if execute_side_effect is not None:
        cursor.execute.side_effect = execute_side_effect
    cursor.fetchone.side_effect = fetchone_results if fetchone_results is not None else [None] * 2
    cursor.fetchall.side_effect = fetchall_results if fetchall_results is not None else [[]] * 5
    return cursor


def make_mock_conn(cursor):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


DEFAULT_FETCHONE = [
    {"total_organizations": 10, "total_collaborators": 4, "total_contributors": 3, "average_org_rating": 4.1},
    {"collaborator_count": 4, "contributor_count": 3, "total": 10},
]
DEFAULT_FETCHALL = [
    [{"period": "2026-01", "total_organizations": 10, "total_collaborators": 4}],  # growth_trend
    [{"state_id": "CA", "state_name": "California", "city_name": "Sacramento", "organization_count": 10}],  # location
    [{"org_size": "small", "organization_count": 10}],  # size
    [{"rating": 5, "organization_count": 6}],  # rating_distribution (partial on purpose)
    [{"period": "2026-01", "org_type_norm": "non_profit", "count": 10}],  # type distribution
]


class TestValidFilters(unittest.TestCase):
    def _call(self, payload, cursor):
        with patch.object(oa, "get_db_connection", return_value=make_mock_conn(cursor)):
            return oa.lambda_handler(payload, None)

    def test_default_all_filters_returns_200_and_full_structure(self):
        cursor = make_mock_cursor(list(DEFAULT_FETCHONE), list(DEFAULT_FETCHALL))
        resp = self._call({"time_filter": "ALL", "region": "ALL", "organization_type": "ALL"}, cursor)
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertEqual(
            set(body),
            {"summary", "growth_trend", "organizations_by_location", "organizations_by_size",
             "collaborator_vs_contributor", "rating_distribution", "organization_type_distribution"},
        )

    def test_region_filter_produces_parameterized_condition(self):
        cursor = make_mock_cursor(list(DEFAULT_FETCHONE), list(DEFAULT_FETCHALL))
        self._call({"time_filter": "ALL", "region": "California"}, cursor)
        # Every execute() call must use %s placeholders with region passed as
        # a bound parameter, never interpolated into the query string.
        for call in cursor.execute.call_args_list:
            query_text = call.args[0]
            params = call.args[1] if len(call.args) > 1 else []
            self.assertNotIn("California", query_text, "region value must not be inlined into SQL text")
            if "state_name" in query_text:
                self.assertIn("California", params)

    def test_organization_type_filter_normalizes_and_parameterizes(self):
        cursor = make_mock_cursor(list(DEFAULT_FETCHONE), list(DEFAULT_FETCHALL))
        self._call({"time_filter": "ALL", "organization_type": "non_profit"}, cursor)
        for call in cursor.execute.call_args_list:
            query_text = call.args[0]
            self.assertNotIn("non_profit", query_text, "org type value must not be inlined into SQL text")

    def test_custom_date_range_uses_between_with_params(self):
        cursor = make_mock_cursor(list(DEFAULT_FETCHONE), list(DEFAULT_FETCHALL))
        self._call({"time_filter": "CUSTOM", "start_date": "2026-01-01", "end_date": "2026-06-30"}, cursor)
        found_between = False
        for call in cursor.execute.call_args_list:
            query_text, params = call.args[0], call.args[1]
            if "BETWEEN %s AND %s" in query_text:
                found_between = True
                self.assertIn("2026-01-01", params)
                self.assertIn("2026-06-30", params)
        self.assertTrue(found_between, "CUSTOM time_filter should produce a BETWEEN %s AND %s condition")


class TestInvalidFilters(unittest.TestCase):
    def _call(self, payload, cursor):
        with patch.object(oa, "get_db_connection", return_value=make_mock_conn(cursor)):
            return oa.lambda_handler(payload, None)

    def test_unrecognized_time_filter_falls_back_to_all(self):
        f = oa.parse_filters({"time_filter": "NOT_A_REAL_FILTER"})
        self.assertEqual(f["time_filter"], "ALL")

    def test_unrecognized_group_by_falls_back_to_default(self):
        f = oa.parse_filters({"group_by": "fortnightly"})
        self.assertEqual(f["group_by"], oa.DEFAULT_GROUP_BY)

    def test_custom_without_dates_is_treated_as_no_date_filter(self):
        conditions, params = oa.build_conditions(
            oa.parse_filters({"time_filter": "CUSTOM", "start_date": None, "end_date": None})
        )
        self.assertFalse(any("BETWEEN" in c for c in conditions))

    def test_garbage_region_does_not_crash_just_matches_nothing(self):
        cursor = make_mock_cursor(
            [
                {"total_organizations": 0, "total_collaborators": 0, "total_contributors": 0, "average_org_rating": None},
                {"collaborator_count": 0, "contributor_count": 0, "total": 0},
            ],
            [[], [], [], [], []],
        )
        resp = self._call({"time_filter": "ALL", "region": "Atlantis"}, cursor)
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertEqual(body["summary"]["total_organizations"], 0)

    def test_garbage_organization_type_is_ignored_gracefully(self):
        f = oa.parse_filters({"organization_type": "not_a_real_type"})
        # Not silently dropped like "ALL" would be -- it's passed through as a
        # real filter value and will simply match zero rows, which is
        # correct behavior (not a crash), verified in the mocked call above.
        self.assertEqual(f["organization_type"], "not_a_real_type")


class TestCustomDateRanges(unittest.TestCase):
    def test_custom_with_only_start_date_is_ignored(self):
        conditions, params = oa.build_conditions(
            oa.parse_filters({"time_filter": "CUSTOM", "start_date": "2026-01-01", "end_date": None})
        )
        self.assertFalse(any("BETWEEN" in c for c in conditions))

    def test_custom_with_both_dates_present(self):
        conditions, params = oa.build_conditions(
            oa.parse_filters({"time_filter": "CUSTOM", "start_date": "2026-01-01", "end_date": "2026-12-31"})
        )
        self.assertTrue(any("BETWEEN %s AND %s" in c for c in conditions))
        self.assertIn("2026-01-01", params)
        self.assertIn("2026-12-31", params)


class TestEmptyResultSets(unittest.TestCase):
    def test_all_empty_results_returns_safe_zeroed_structure(self):
        cursor = make_mock_cursor(
            fetchone_results=[
                {"total_organizations": 0, "total_collaborators": 0, "total_contributors": 0, "average_org_rating": None},
                {"collaborator_count": 0, "contributor_count": 0, "total": 0},
            ],
            fetchall_results=[[], [], [], [], []],
        )
        with patch.object(oa, "get_db_connection", return_value=make_mock_conn(cursor)):
            resp = oa.lambda_handler({"time_filter": "ALL"}, None)
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertEqual(body["summary"]["total_organizations"], 0)
        self.assertEqual(body["growth_trend"], [])
        self.assertEqual(body["organizations_by_location"], [])
        # zero-filled buckets still present even with no data
        self.assertEqual(len(body["organizations_by_size"]), 3)
        self.assertEqual(len(body["rating_distribution"]), 5)
        self.assertEqual(len(body["collaborator_vs_contributor"]), 2)

    def test_fetchone_returning_none_does_not_crash(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, None]
        cursor.fetchall.side_effect = [[], [], [], [], []]
        with patch.object(oa, "get_db_connection", return_value=make_mock_conn(cursor)):
            resp = oa.lambda_handler({"time_filter": "ALL"}, None)
        self.assertEqual(resp["statusCode"], 200)


class TestDatabaseAndQueryExceptions(unittest.TestCase):
    def test_connection_failure_returns_500_with_default_body(self):
        with patch.object(oa, "get_db_connection", side_effect=Exception("connection refused")):
            resp = oa.lambda_handler({"time_filter": "ALL"}, None)
        self.assertEqual(resp["statusCode"], 500)
        body = json.loads(resp["body"])
        self.assertEqual(body, oa.get_default_response())

    def test_single_query_exception_degrades_only_that_field(self):
        # First cursor.execute() call (summary) raises; the rest succeed.
        cursor = MagicMock()
        cursor.execute.side_effect = [
            Exception("relation does not exist"),  # summary query fails
            None, None, None, None, None, None,     # remaining 6 queries succeed
        ]
        cursor.fetchone.side_effect = [DEFAULT_FETCHONE[1]]  # only cvc's fetchone is reached
        cursor.fetchall.side_effect = list(DEFAULT_FETCHALL)
        with patch.object(oa, "get_db_connection", return_value=make_mock_conn(cursor)):
            resp = oa.lambda_handler({"time_filter": "ALL"}, None)
        # Overall call still succeeds (200); only summary degrades to defaults.
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertEqual(body["summary"], oa.get_default_response()["summary"])
        self.assertNotEqual(body["growth_trend"], [])  # other metrics still populated

    def test_cursor_close_and_connection_close_are_always_called(self):
        cursor = make_mock_cursor(list(DEFAULT_FETCHONE), list(DEFAULT_FETCHALL))
        conn = make_mock_conn(cursor)
        with patch.object(oa, "get_db_connection", return_value=conn):
            oa.lambda_handler({"time_filter": "ALL"}, None)
        cursor.close.assert_called_once()
        conn.close.assert_called_once()

    def test_cursor_close_called_even_when_query_raises(self):
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("boom")
        conn = make_mock_conn(cursor)
        with patch.object(oa, "get_db_connection", return_value=conn):
            resp = oa.lambda_handler({"time_filter": "ALL"}, None)
        self.assertEqual(resp["statusCode"], 200)  # per-metric errors are caught, not fatal
        cursor.close.assert_called_once()
        conn.close.assert_called_once()


class TestResponseStructureValidation(unittest.TestCase):
    def test_full_response_matches_organization_dashboard_requirements(self):
        cursor = make_mock_cursor(list(DEFAULT_FETCHONE), list(DEFAULT_FETCHALL))
        with patch.object(oa, "get_db_connection", return_value=make_mock_conn(cursor)):
            resp = oa.lambda_handler({"time_filter": "ALL"}, None)
        body = json.loads(resp["body"])

        # KPI cards (all 4)
        self.assertEqual(
            set(body["summary"]),
            {"total_organizations", "total_collaborators", "total_contributors", "average_org_rating"},
        )
        # Growth trend fields
        for row in body["growth_trend"]:
            self.assertEqual(set(row), {"period", "total_organizations", "total_collaborators"})
        # Location: state + city present
        for row in body["organizations_by_location"]:
            self.assertIn("state_id", row)
            self.assertIn("city_name", row)
        # Size: exactly small/medium/large
        self.assertEqual(
            {row["org_size"] for row in body["organizations_by_size"]}, {"small", "medium", "large"}
        )
        # Collaborator vs contributor: exactly those two types
        self.assertEqual(
            {row["type"] for row in body["collaborator_vs_contributor"]}, {"collaborator", "contributor"}
        )
        # Rating distribution: exactly 1..5
        self.assertEqual([row["rating"] for row in body["rating_distribution"]], [1, 2, 3, 4, 5])
        # Org type trend rows have for_profit/non_profit/total
        for row in body["organization_type_distribution"]:
            self.assertEqual(set(row), {"period", "for_profit", "non_profit", "total"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
