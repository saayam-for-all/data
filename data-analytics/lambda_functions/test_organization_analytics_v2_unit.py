import unittest
from unittest.mock import patch, MagicMock
import psycopg2

import organization_analytics_v2 as oa


class TestValidateFilters(unittest.TestCase):

    def test_valid_default_filters(self):
        self.assertIsNone(oa.validate_filters({}))

    def test_valid_time_filter(self):
        self.assertIsNone(oa.validate_filters({"time_filter": "30D"}))

    def test_invalid_time_filter(self):
        err = oa.validate_filters({"time_filter": "3W"})
        self.assertIsNotNone(err)
        self.assertIn("Invalid time_filter", err)

    def test_custom_requires_dates(self):
        err = oa.validate_filters({"time_filter": "CUSTOM"})
        self.assertIsNotNone(err)
        self.assertIn("CUSTOM", err)

    def test_custom_with_dates_is_valid(self):
        err = oa.validate_filters({
            "time_filter": "CUSTOM",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
        })
        self.assertIsNone(err)

    def test_invalid_group_by(self):
        err = oa.validate_filters({"group_by": "hourly"})
        self.assertIsNotNone(err)
        self.assertIn("Invalid group_by", err)


class TestBuildFilterClauses(unittest.TestCase):

    def test_no_filters_when_all(self):
        clauses, params = oa.build_filter_clauses("ALL", "ALL")
        self.assertEqual(clauses, [])
        self.assertEqual(params, [])

    def test_region_filter(self):
        clauses, params = oa.build_filter_clauses("California", "ALL")
        self.assertEqual(len(clauses), 1)
        self.assertIn("state_name", clauses[0])
        self.assertEqual(params, ["California"])

    def test_organization_type_filter(self):
        clauses, params = oa.build_filter_clauses("ALL", "non_profit")
        self.assertEqual(len(clauses), 1)
        self.assertIn("org_type", clauses[0])
        self.assertEqual(params, ["non_profit"])

    def test_both_filters(self):
        clauses, params = oa.build_filter_clauses("Texas", "for_profit")
        self.assertEqual(len(clauses), 2)
        self.assertEqual(params, ["Texas", "for_profit"])


class TestSafeMath(unittest.TestCase):

    def test_safe_round_none(self):
        self.assertEqual(oa.safe_round(None), 0.0)

    def test_safe_round_value(self):
        self.assertEqual(oa.safe_round(4.234, 1), 4.2)

    def test_safe_pct_zero_total(self):
        self.assertEqual(oa.safe_pct(5, 0), 0.0)

    def test_safe_pct_normal(self):
        self.assertEqual(oa.safe_pct(1, 4), 25.0)

class TestLambdaHandlerWithMockedDB(unittest.TestCase):

    def _make_mock_cursor(self, summary_return=None, fetchall_return=None):
        mock_cursor = MagicMock()
        summary = summary_return or {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": None,
        }
        collab_vs_contrib = {"collaborator_count": 0, "contributor_count": 0}
        mock_cursor.fetchone.side_effect = [summary, collab_vs_contrib]
        mock_cursor.fetchall.return_value = fetchall_return or []
        return mock_cursor

    @patch("organization_analytics_v2.get_db_connection")
    def test_invalid_time_filter_returns_400_without_touching_db(self, mock_get_conn):
        result = oa.lambda_handler({"time_filter": "BAD"}, None)
        self.assertEqual(result["statusCode"], 400)
        mock_get_conn.assert_not_called()

    @patch("organization_analytics_v2.get_db_connection")
    def test_custom_without_dates_returns_400(self, mock_get_conn):
        result = oa.lambda_handler({"time_filter": "CUSTOM"}, None)
        self.assertEqual(result["statusCode"], 400)
        mock_get_conn.assert_not_called()

    @patch("organization_analytics_v2.get_db_connection")
    def test_db_exception_returns_500(self, mock_get_conn):
        mock_get_conn.side_effect = psycopg2.OperationalError("could not connect to server")
        result = oa.lambda_handler({"time_filter": "ALL"}, None)
        self.assertEqual(result["statusCode"], 500)
        self.assertIn("error", result["body"])

    @patch("organization_analytics_v2.get_db_connection")
    def test_query_exception_returns_500(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = psycopg2.errors.UndefinedColumn("column does not exist")
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn
        result = oa.lambda_handler({"time_filter": "ALL"}, None)
        self.assertEqual(result["statusCode"], 500)

    @patch("organization_analytics_v2.get_db_connection")
    def test_empty_result_set_does_not_crash(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = self._make_mock_cursor()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        result = oa.lambda_handler({"time_filter": "ALL"}, None)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["body"]["summary"]["total_organizations"], 0)
        self.assertEqual(result["body"]["rating_distribution"], [
            {"rating": i, "organization_count": 0} for i in range(1, 6)
        ])

    @patch("organization_analytics_v2.get_db_connection")
    def test_valid_filters_calls_db_and_returns_200(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = self._make_mock_cursor(
            summary_return={
                "total_organizations": 40,
                "total_collaborators": 21,
                "total_contributors": 19,
                "average_org_rating": 3.23,
            }
        )
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        result = oa.lambda_handler({
            "time_filter": "1Y", "group_by": "monthly",
            "region": "ALL", "organization_type": "non_profit"
        }, None)

        self.assertEqual(result["statusCode"], 200)
        mock_get_conn.assert_called_once()

    @patch("organization_analytics_v2.get_db_connection")
    def test_api_gateway_style_event_with_json_body(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = self._make_mock_cursor()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        event = {"body": '{"time_filter": "ALL", "group_by": "yearly"}'}
        result = oa.lambda_handler(event, None)
        self.assertEqual(result["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()