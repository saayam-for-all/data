"""
Cursor-based/mock database unit tests for organization_analytics.py, per the
ticket's explicit testing requirement. No real Postgres connection here --
get_db_connection() is mocked out entirely, and the mock cursor's
fetchone()/fetchall() are fed canned rows via side_effect, in the exact order
lambda_handler calls them:

    1. get_summary                    -> fetchone
    2. get_growth_trend               -> fetchall
    3. get_organizations_by_location  -> fetchall (state query)
    4. get_organizations_by_location  -> fetchall (city query)
    5. get_organizations_by_size      -> fetchall
    6. get_collaborator_vs_contributor -> fetchone
    7. get_rating_distribution        -> fetchall
    8. get_organization_type_distribution -> fetchall

If lambda_handler's internal call order ever changes, these side_effect lists
need to be reordered to match.

For live-DB / integration-style testing against real sample data, see
test_organization_analytics.py instead.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import organization_analytics as api


def make_mock_cursor(fetchone_results=None, fetchall_results=None, execute_side_effect=None):
    cursor = MagicMock()
    if execute_side_effect is not None:
        cursor.execute.side_effect = execute_side_effect
    if fetchone_results is not None:
        cursor.fetchone.side_effect = fetchone_results
    if fetchall_results is not None:
        cursor.fetchall.side_effect = fetchall_results
    return cursor


def make_mock_connection(cursor):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


HAPPY_PATH_FETCHONE = [
    {  # get_summary
        "total_organizations": 40,
        "total_collaborators": 20,
        "total_contributors": 20,
        "average_org_rating": 3.1,
    },
    {  # get_collaborator_vs_contributor
        "total": 40,
        "collaborators": 20,
        "contributors": 20,
    },
]

HAPPY_PATH_FETCHALL = [
    [{"period": "2026-01", "total_organizations": 40, "total_collaborators": 20}],  # growth_trend
    [{"state_id": "CA", "state_name": "California", "organization_count": 5, "percentage": 12.5}],  # location (state)
    [{"state_id": "CA", "city_name": "San Jose", "organization_count": 5}],  # location (city)
    [{"org_size": "small", "organization_count": 15}],  # by_size
    [{"rating": 5, "organization_count": 8}],  # rating_distribution
    [{"period": "2026-01", "for_profit": 18, "non_profit": 22, "total": 40}],  # organization_type_distribution
]


class TestBuildTimeFilter(unittest.TestCase):
    """Pure-function tests, no mocking needed."""

    def test_custom_range_with_both_dates(self):
        clause, params = api.build_time_filter("CUSTOM", "2026-01-01", "2026-06-30")
        self.assertEqual(clause, "o.created_at BETWEEN %s AND %s")
        self.assertEqual(params, ("2026-01-01", "2026-06-30"))

    def test_custom_range_missing_both_dates(self):
        clause, params = api.build_time_filter("CUSTOM", None, None)
        self.assertEqual(clause, "")
        self.assertEqual(params, ())

    def test_invalid_time_filter_raises(self):
        with self.assertRaises(ValueError):
            api.build_time_filter("NEXT_WEEK")


class TestNormalizeOrgType(unittest.TestCase):
    def test_hyphenated_mixed_case(self):
        self.assertEqual(api.normalize_org_type("Non-Profit"), "non_profit")
        self.assertEqual(api.normalize_org_type("For-profit"), "for_profit")


class TestLambdaHandlerValidFilters(unittest.TestCase):
    """Ticket's 'Standard Test' sample payload, full happy-path round trip."""

    @patch("organization_analytics.get_db_connection")
    def test_standard_payload_returns_200_with_expected_shape(self, mock_get_conn):
        cursor = make_mock_cursor(fetchone_results=list(HAPPY_PATH_FETCHONE), fetchall_results=list(HAPPY_PATH_FETCHALL))
        mock_get_conn.return_value = make_mock_connection(cursor)

        event = {"body": json.dumps({
            "time_filter": "30D", "start_date": None, "end_date": None,
            "group_by": "daily", "region": "ALL", "organization_type": "ALL",
        })}
        result = api.lambda_handler(event, None)

        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])

        # Response-structure validation against the ticket's suggested shape.
        self.assertEqual(
            set(body.keys()),
            {"summary", "growth_trend", "organizations_by_location", "organizations_by_size",
             "collaborator_vs_contributor", "rating_distribution", "organization_type_distribution"},
        )
        self.assertEqual(
            set(body["summary"].keys()),
            {"total_organizations", "total_collaborators", "total_contributors", "average_org_rating"},
        )
        self.assertEqual(body["summary"]["total_organizations"], 40)
        self.assertEqual(body["organizations_by_location"][0]["cities"][0]["city_name"], "San Jose")


class TestLambdaHandlerInvalidFilters(unittest.TestCase):
    """An invalid time_filter/group_by should degrade gracefully, not crash the handler."""

    @patch("organization_analytics.get_db_connection")
    def test_invalid_time_filter_falls_back_to_defaults(self, mock_get_conn):
        # build_time_filter raises before any query runs, so the DB mock is never touched --
        # but get_db_connection() itself still needs to succeed for the handler to reach that point.
        cursor = make_mock_cursor()
        mock_get_conn.return_value = make_mock_connection(cursor)

        event = {"body": json.dumps({"time_filter": "NEXT_WEEK"})}
        result = api.lambda_handler(event, None)

        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertEqual(body["summary"]["total_organizations"], 0)
        self.assertEqual(body["growth_trend"], [])

    @patch("organization_analytics.get_db_connection")
    def test_invalid_group_by_only_breaks_trend_sections(self, mock_get_conn):
        # summary/location/size/collaborator_vs_contributor/rating_distribution don't use
        # group_by at all, so they should still succeed even though growth_trend and
        # organization_type_distribution (the two that call get_grouping) fall back.
        cursor = make_mock_cursor(
            fetchone_results=list(HAPPY_PATH_FETCHONE),
            fetchall_results=[
                HAPPY_PATH_FETCHALL[1],  # location (state)
                HAPPY_PATH_FETCHALL[2],  # location (city)
                HAPPY_PATH_FETCHALL[3],  # by_size
                HAPPY_PATH_FETCHALL[4],  # rating_distribution
            ],
        )
        mock_get_conn.return_value = make_mock_connection(cursor)

        event = {"body": json.dumps({"time_filter": "ALL", "group_by": "biweekly"})}
        result = api.lambda_handler(event, None)

        body = json.loads(result["body"])
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(body["growth_trend"], [])  # fell back
        self.assertEqual(body["organization_type_distribution"], [])  # fell back
        self.assertEqual(body["summary"]["total_organizations"], 40)  # unaffected
        self.assertEqual(body["organizations_by_size"][0]["org_size"], "small")  # unaffected


class TestLambdaHandlerEmptyResultSet(unittest.TestCase):
    @patch("organization_analytics.get_db_connection")
    def test_no_matching_rows_returns_valid_empty_shape(self, mock_get_conn):
        cursor = make_mock_cursor(
            fetchone_results=[
                {"total_organizations": 0, "total_collaborators": 0, "total_contributors": 0, "average_org_rating": None},
                {"total": 0, "collaborators": 0, "contributors": 0},
            ],
            fetchall_results=[[] for _ in range(6)],
        )
        mock_get_conn.return_value = make_mock_connection(cursor)

        event = {"body": json.dumps({"time_filter": "7D", "region": "Wyoming"})}
        result = api.lambda_handler(event, None)

        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertEqual(body["summary"]["total_organizations"], 0)
        self.assertEqual(body["summary"]["average_org_rating"], 0)
        self.assertEqual(body["growth_trend"], [])
        self.assertEqual(body["organizations_by_location"], [])
        # 0 collaborators / 0 total -> percentage must not divide by zero.
        self.assertEqual(body["collaborator_vs_contributor"][0]["percentage"], 0)


class TestLambdaHandlerDatabaseExceptions(unittest.TestCase):
    @patch("organization_analytics.get_db_connection")
    def test_connection_failure_returns_500_with_safe_defaults(self, mock_get_conn):
        mock_get_conn.side_effect = Exception("could not connect to server")

        result = api.lambda_handler({"body": "{}"}, None)

        self.assertEqual(result["statusCode"], 500)
        body = json.loads(result["body"])
        self.assertEqual(body["summary"]["total_organizations"], 0)

    @patch("organization_analytics.get_db_connection")
    def test_single_query_exception_only_degrades_that_section(self, mock_get_conn):
        # First execute() call (get_summary) blows up; everything after it should still run.
        cursor = make_mock_cursor(
            fetchone_results=[HAPPY_PATH_FETCHONE[1]],  # only collaborator_vs_contributor's fetchone gets reached
            fetchall_results=list(HAPPY_PATH_FETCHALL),
            execute_side_effect=[Exception("relation does not exist")] + [None] * 20,
        )
        mock_get_conn.return_value = make_mock_connection(cursor)

        result = api.lambda_handler({"body": "{}"}, None)
        body = json.loads(result["body"])

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(body["summary"]["total_organizations"], 0)  # degraded to default
        self.assertEqual(body["growth_trend"][0]["total_organizations"], 40)  # unaffected


if __name__ == "__main__":
    unittest.main()
