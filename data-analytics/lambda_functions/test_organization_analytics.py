"""Unit and local PostgreSQL tests for the Organization Analytics API."""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import organization_analytics as analytics


class OrganizationAnalyticsUnitTests(unittest.TestCase):
    """Validate request parsing and safe SQL filter construction without a DB."""

    def test_parses_api_gateway_body(self):
        payload = {"dashboard_type": "performance", "time_filter": "ALL"}
        self.assertEqual(
            analytics.parse_event_body({"body": json.dumps(payload)}), payload
        )

    def test_default_filters_match_api_contract(self):
        filters = analytics.parse_filters({})
        self.assertEqual(filters["time_filter"], "30D")
        self.assertEqual(filters["group_by"], "daily")

    def test_display_labels_are_normalized(self):
        filters = analytics.parse_filters(
            {"org_type": "Non-Profit", "org_size": "LARGE"}
        )
        self.assertEqual(filters["org_type"], "non_profit")
        self.assertEqual(filters["org_size"], "large")

    def test_string_booleans_are_supported(self):
        filters = analytics.parse_filters(
            {"is_collaborator": "false", "is_contributor": "true"}
        )
        self.assertIs(filters["is_collaborator"], False)
        self.assertIs(filters["is_contributor"], True)

    def test_custom_filter_is_inclusive_of_end_date(self):
        filters = analytics.parse_filters(
            {
                "time_filter": "CUSTOM",
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
            }
        )
        conditions, params = analytics.build_conditions(filters, True)
        self.assertIn("o.created_at >= %s::date", conditions)
        self.assertIn("o.created_at < %s::date + INTERVAL '1 day'", conditions)
        self.assertEqual(params[:2], ["2025-01-01", "2025-01-31"])

    def test_filter_values_are_parameterized(self):
        filters = analytics.parse_filters(
            {"city_name": "Richmond' OR TRUE --", "time_filter": "ALL"}
        )
        conditions, params = analytics.build_conditions(filters, True)
        self.assertNotIn("Richmond", " ".join(conditions))
        self.assertEqual(params, ["Richmond' OR TRUE --"])

    def test_contributor_filter_is_rejected_when_column_is_missing(self):
        filters = analytics.parse_filters(
            {"time_filter": "ALL", "is_contributor": True}
        )
        with self.assertRaises(analytics.RequestValidationError):
            analytics.build_conditions(filters, False)

    def test_invalid_filters_are_rejected(self):
        invalid_payloads = [
            {"time_filter": "90D"},
            {"group_by": "hourly"},
            {"org_rating": 6},
            {"is_collaborator": "sometimes"},
            {"org_type": "government"},
            {"org_size": "extra-large"},
            {"time_filter": "CUSTOM", "start_date": "2025-01-01"},
            {
                "time_filter": "CUSTOM",
                "start_date": "2025-02-01",
                "end_date": "2025-01-01",
            },
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(analytics.RequestValidationError):
                    analytics.parse_filters(payload)

    def test_handler_rejects_invalid_dashboard_before_database_access(self):
        response = analytics.lambda_handler({"dashboard_type": "unknown"}, None)
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("dashboard_type", json.loads(response["body"])["error"])

    def test_source_contains_no_parameter_store_path_or_client(self):
        source = Path(analytics.__file__).read_text(encoding="utf-8")
        self.assertNotIn("/dev/saayam/db", source)
        self.assertNotIn("boto3", source)
        self.assertNotIn("get_parameter", source)


@unittest.skipUnless(
    os.environ.get("ORG_ANALYTICS_RUN_INTEGRATION_TESTS", "").lower()
    in {"1", "true", "yes"},
    "Set ORG_ANALYTICS_RUN_INTEGRATION_TESTS=true for local PostgreSQL tests.",
)
class OrganizationAnalyticsPostgresTests(unittest.TestCase):
    """Exercise both dashboard handlers against the loaded source CSV data."""

    @staticmethod
    def request(payload):
        response = analytics.lambda_handler(payload, None)
        return response, json.loads(response["body"])

    def test_overview_all_metrics_match_source_extract(self):
        response, body = self.request(
            {
                "dashboard_type": "overview",
                "time_filter": "ALL",
                "group_by": "monthly",
            }
        )
        self.assertEqual(response["statusCode"], 200)
        overview = body["organization_overview"]
        self.assertEqual(
            overview["summary"],
            {
                "total_organizations": 40,
                "non_profit_organizations": 21,
                "for_profit_organizations": 19,
                "collaborator_organizations": 21,
                "non_collaborator_organizations": 19,
                "contributor_organizations": 19,
                "non_contributor_organizations": 21,
            },
        )
        self.assertTrue(overview["organization_activity_trend"])
        self.assertTrue(overview["organizations_by_location"]["by_state"])
        self.assertTrue(overview["organizations_by_location"]["by_city"])

    def test_overview_distributions_are_consistent(self):
        _, body = self.request(
            {"dashboard_type": "overview", "time_filter": "ALL"}
        )
        overview = body["organization_overview"]
        total = overview["summary"]["total_organizations"]
        self.assertEqual(
            sum(item["count"] for item in overview["organizations_by_type"]),
            total,
        )
        self.assertEqual(
            sum(item["count"] for item in overview["organizations_by_size"]),
            total,
        )
        self.assertEqual(
            sum(item["count"] for item in overview["collaborator_distribution"]),
            total,
        )
        self.assertEqual(
            sum(item["count"] for item in overview["contributor_distribution"]),
            total,
        )

    def test_performance_all_metrics_match_source_extract(self):
        response, body = self.request(
            {"dashboard_type": "performance", "time_filter": "ALL"}
        )
        self.assertEqual(response["statusCode"], 200)
        performance = body["organization_performance"]
        self.assertEqual(
            performance["summary"],
            {
                "average_rating": 3.23,
                "rated_organizations": 40,
                "unrated_organizations": 0,
                "five_star_organizations": 12,
            },
        )
        expected_distribution = {1: 5, 2: 9, 3: 10, 4: 4, 5: 12}
        self.assertEqual(
            {
                item["rating"]: item["count"]
                for item in performance["rating_distribution"]
            },
            expected_distribution,
        )
        self.assertLessEqual(len(performance["top_rated_organizations"]), 10)
        self.assertLessEqual(
            len(performance["top_collaborator_organizations"]), 10
        )
        self.assertLessEqual(
            len(performance["top_contributor_organizations"]), 10
        )

    def test_every_grouping_is_supported(self):
        for group_by in ("daily", "weekly", "monthly", "yearly"):
            with self.subTest(group_by=group_by):
                response, body = self.request(
                    {
                        "dashboard_type": "overview",
                        "time_filter": "ALL",
                        "group_by": group_by,
                    }
                )
                self.assertEqual(response["statusCode"], 200)
                self.assertTrue(
                    body["organization_overview"][
                        "organization_activity_trend"
                    ]
                )

    def test_all_dimension_filters(self):
        cases = [
            ("org_type", "Non-Profit"),
            ("org_size", "Large"),
            ("state_id", "CA"),
            ("city_name", "North Judithbury"),
            ("org_rating", 5),
            ("is_collaborator", True),
            ("is_contributor", True),
        ]
        for field, value in cases:
            with self.subTest(field=field):
                response, body = self.request(
                    {
                        "dashboard_type": "overview",
                        "time_filter": "ALL",
                        field: value,
                    }
                )
                self.assertEqual(response["statusCode"], 200)
                self.assertGreater(
                    body["organization_overview"]["summary"][
                        "total_organizations"
                    ],
                    0,
                )

    def test_custom_date_range_and_api_gateway_body(self):
        payload = {
            "dashboard_type": "performance",
            "time_filter": "CUSTOM",
            "start_date": "2020-01-01",
            "end_date": "2030-12-31",
        }
        response = analytics.lambda_handler({"body": json.dumps(payload)}, None)
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            body["organization_performance"]["summary"]["rated_organizations"],
            40,
        )

    def test_separate_endpoint_handlers(self):
        overview = analytics.overview_handler({"time_filter": "ALL"}, None)
        performance = analytics.performance_handler({"time_filter": "ALL"}, None)
        self.assertEqual(overview["statusCode"], 200)
        self.assertEqual(performance["statusCode"], 200)
        self.assertIn("organization_overview", json.loads(overview["body"]))
        self.assertIn("organization_performance", json.loads(performance["body"]))

    def test_missing_contributor_column_degrades_gracefully(self):
        with patch.object(analytics, "has_contributor_column", return_value=False):
            response, body = self.request(
                {"dashboard_type": "overview", "time_filter": "ALL"}
            )
        self.assertEqual(response["statusCode"], 200)
        overview = body["organization_overview"]
        self.assertIsNone(overview["summary"]["contributor_organizations"])
        self.assertEqual(overview["contributor_distribution"], [])
        self.assertIn("is_contributor", overview["schema_notes"])
        self.assertEqual(overview["summary"]["total_organizations"], 40)

    def test_missing_contributor_column_rejects_contributor_filter(self):
        with patch.object(analytics, "has_contributor_column", return_value=False):
            response, body = self.request(
                {
                    "dashboard_type": "overview",
                    "time_filter": "ALL",
                    "is_contributor": True,
                }
            )
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("is_contributor", body["error"])

    def test_one_metric_failure_does_not_blank_later_metrics(self):
        with patch.object(
            analytics,
            "fetch_group_distribution",
            side_effect=RuntimeError("forced metric failure"),
        ):
            response, body = self.request(
                {"dashboard_type": "overview", "time_filter": "ALL"}
            )
        overview = body["organization_overview"]
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(overview["organizations_by_type"], [])
        self.assertTrue(overview["organizations_by_location"]["by_state"])
        self.assertEqual(overview["summary"]["total_organizations"], 40)


if __name__ == "__main__":
    unittest.main(verbosity=2)
