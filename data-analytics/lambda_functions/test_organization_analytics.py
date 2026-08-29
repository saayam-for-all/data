import json
import os
import sys
import unittest
from datetime import date
from unittest.mock import MagicMock, patch


sys.path.insert(0, os.path.dirname(__file__))
import organization_analytics as analytics  # noqa: E402


class FilterValidationTests(unittest.TestCase):
    def test_defaults(self):
        filters = analytics.validate_filters({})
        self.assertEqual(filters["dashboard_type"], "overview")
        self.assertEqual(filters["time_filter"], "30D")
        self.assertEqual(filters["group_by"], "daily")

    def test_custom_dates_are_parsed(self):
        filters = analytics.validate_filters({
            "time_filter": "CUSTOM", "start_date": "2025-01-01", "end_date": "2025-01-31"
        })
        self.assertEqual(filters["start_date"], date(2025, 1, 1))

    def test_custom_requires_dates(self):
        with self.assertRaisesRegex(analytics.RequestValidationError, "requires"):
            analytics.validate_filters({"time_filter": "CUSTOM"})

    def test_boolean_filter_is_strict(self):
        with self.assertRaisesRegex(analytics.RequestValidationError, "true, false"):
            analytics.validate_filters({"is_collaborator": "true"})

    def test_invalid_schema_is_rejected(self):
        with patch.dict(os.environ, {"DB_SCHEMA": "public; DROP TABLE organizations"}):
            with self.assertRaises(ValueError):
                analytics.get_schema_name()


class QueryBuilderTests(unittest.TestCase):
    def test_all_common_filters_are_parameterized(self):
        filters = analytics.validate_filters({
            "time_filter": "ALL", "org_type": "Non-Profit", "org_size": "Small",
            "state_id": "VA", "city_name": "Richmond", "org_rating": 5,
            "is_collaborator": True, "is_contributor": False,
        })
        where_sql, params = analytics.build_where_clause(filters, True)
        self.assertIn("o.org_rating = %(org_rating)s", where_sql)
        self.assertIn("o.is_contributor = %(is_contributor)s", where_sql)
        self.assertEqual(params["city_name"], "Richmond")

    def test_missing_contributor_column_true_filter_returns_no_rows(self):
        filters = analytics.validate_filters({"is_contributor": True})
        where_sql, params = analytics.build_where_clause(filters, False)
        self.assertIn("FALSE", where_sql)
        self.assertNotIn("is_contributor", params)

    def test_missing_contributor_column_false_filter_treats_all_as_noncontributors(self):
        filters = analytics.validate_filters({"is_contributor": False})
        where_sql, _ = analytics.build_where_clause(filters, False)
        self.assertNotIn("FALSE", where_sql)

    def test_custom_date_filter_is_inclusive_and_index_friendly(self):
        filters = analytics.validate_filters({
            "time_filter": "CUSTOM",
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
        })
        where_sql, params = analytics.build_where_clause(filters, True)
        self.assertNotIn("created_at::date", where_sql)
        self.assertEqual(params["end_exclusive"], date(2025, 2, 1))

    def test_extra_condition_works_with_and_without_where(self):
        self.assertEqual(analytics._with_condition("", "o.org_rating IS NOT NULL"), "WHERE o.org_rating IS NOT NULL")
        self.assertEqual(analytics._with_condition("WHERE FALSE", "o.org_rating IS NOT NULL"), "WHERE FALSE AND o.org_rating IS NOT NULL")


class HandlerTests(unittest.TestCase):
    @patch("organization_analytics.get_db_connection")
    def test_overview_response_and_cleanup(self, get_connection):
        connection = MagicMock()
        cursor = MagicMock()
        get_connection.return_value = connection
        connection.cursor.return_value = cursor
        cursor.fetchone.side_effect = [
            {"exists": False},
            {"total_organizations": 2, "non_profit_organizations": 1,
             "for_profit_organizations": 1, "collaborator_organizations": 1,
             "non_collaborator_organizations": 1, "contributor_organizations": 0,
             "non_contributor_organizations": 2},
        ]
        cursor.fetchall.side_effect = [[], [], [], []]

        response = analytics.lambda_handler({"body": json.dumps({"dashboard_type": "overview", "time_filter": "ALL"})}, None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["organization_overview"]["summary"]["total_organizations"], 2)
        dashboard_queries = " ".join(
            call.args[0] for call in cursor.execute.call_args_list[1:]
        )
        self.assertNotIn("o.is_contributor", dashboard_queries)
        self.assertEqual(cursor.execute.call_count, 6)
        cursor.close.assert_called_once()
        connection.close.assert_called_once()

    @patch("organization_analytics.get_db_connection")
    def test_performance_returns_complete_rating_scale(self, get_connection):
        connection = MagicMock()
        cursor = MagicMock()
        get_connection.return_value = connection
        connection.cursor.return_value = cursor
        cursor.fetchone.side_effect = [
            {"exists": True},
            {"average_rating": 5, "rated_organizations": 2, "unrated_organizations": 0, "five_star_organizations": 2},
        ]
        cursor.fetchall.side_effect = [
            [{"rating": 5, "count": 2}], [], [], [], [], []
        ]

        response = analytics.lambda_handler({"dashboard_type": "performance", "time_filter": "ALL"}, None)

        self.assertEqual(response["statusCode"], 200)
        distribution = json.loads(response["body"])["organization_performance"]["rating_distribution"]
        self.assertEqual(distribution, [
            {"rating": 1, "count": 0}, {"rating": 2, "count": 0},
            {"rating": 3, "count": 0}, {"rating": 4, "count": 0},
            {"rating": 5, "count": 2},
        ])

    def test_bad_dashboard_returns_400_without_database_call(self):
        with patch("organization_analytics.get_db_connection") as get_connection:
            response = analytics.lambda_handler({"dashboard_type": "unknown"}, None)
        self.assertEqual(response["statusCode"], 400)
        get_connection.assert_not_called()

    def test_options_request(self):
        response = analytics.lambda_handler({"httpMethod": "OPTIONS"}, None)
        self.assertEqual(response["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
