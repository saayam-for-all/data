import json
import unittest
from unittest.mock import MagicMock, patch

import organization_analytics as org_api


class TestOrganizationAnalytics(unittest.TestCase):

    def test_validate_valid_request(self):
        payload = {
            "time_filter": "30D",
            "start_date": None,
            "end_date": None,
            "group_by": "daily",
            "region": "ALL",
            "organization_type": "ALL",
        }

        self.assertIsNone(org_api.validate_request(payload))

    def test_validate_invalid_time_filter(self):
        payload = {
            "time_filter": "10D",
            "group_by": "daily",
            "region": "ALL",
            "organization_type": "ALL",
        }

        error = org_api.validate_request(payload)

        self.assertIsNotNone(error)
        self.assertIn("Invalid time_filter", error)

    def test_validate_invalid_group_by(self):
        payload = {
            "time_filter": "30D",
            "group_by": "hourly",
            "region": "ALL",
            "organization_type": "ALL",
        }

        error = org_api.validate_request(payload)

        self.assertIsNotNone(error)
        self.assertIn("Invalid group_by", error)

    def test_validate_invalid_organization_type(self):
        payload = {
            "time_filter": "30D",
            "group_by": "daily",
            "region": "ALL",
            "organization_type": "government",
        }

        error = org_api.validate_request(payload)

        self.assertIsNotNone(error)
        self.assertIn("Invalid organization_type", error)

    def test_custom_date_requires_both_dates(self):
        payload = {
            "time_filter": "CUSTOM",
            "start_date": "2026-01-01",
            "end_date": None,
            "group_by": "monthly",
            "region": "ALL",
            "organization_type": "ALL",
        }

        error = org_api.validate_request(payload)

        self.assertIsNotNone(error)
        self.assertIn("both start_date and end_date", error)

    def test_custom_date_invalid_order(self):
        payload = {
            "time_filter": "CUSTOM",
            "start_date": "2026-06-30",
            "end_date": "2026-01-01",
            "group_by": "monthly",
            "region": "ALL",
            "organization_type": "ALL",
        }

        error = org_api.validate_request(payload)

        self.assertEqual(
            error,
            "start_date cannot be after end_date."
        )

    def test_fetch_summary(self):
        cursor = MagicMock()

        cursor.fetchone.return_value = {
            "total_organizations": 40,
            "total_collaborators": 21,
            "total_contributors": 19,
            "average_org_rating": 3.2,
        }

        result = org_api.fetch_summary(
            cursor,
            "ALL",
            "ALL",
            "ALL",
        )

        self.assertEqual(result["total_organizations"], 40)
        self.assertEqual(result["total_collaborators"], 21)
        self.assertEqual(result["total_contributors"], 19)
        self.assertEqual(result["average_org_rating"], 3.2)

        cursor.execute.assert_called_once()

    def test_fetch_summary_empty_result(self):
        cursor = MagicMock()

        cursor.fetchone.return_value = {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": None,
        }

        result = org_api.fetch_summary(
            cursor,
            "ALL",
            "ALL",
            "ALL",
        )

        self.assertEqual(
            result,
            {
                "total_organizations": 0,
                "total_collaborators": 0,
                "total_contributors": 0,
                "average_org_rating": 0.0,
            },
        )

    def test_rating_distribution_includes_all_ratings(self):
        cursor = MagicMock()

        cursor.fetchall.return_value = [
            {
                "rating": 2,
                "organization_count": 4,
            },
            {
                "rating": 5,
                "organization_count": 8,
            },
        ]

        result = org_api.fetch_rating_distribution(
            cursor,
            "ALL",
            "ALL",
            "ALL",
        )

        self.assertEqual(len(result), 5)

        self.assertEqual(
            result,
            [
                {
                    "rating": 1,
                    "organization_count": 0,
                },
                {
                    "rating": 2,
                    "organization_count": 4,
                },
                {
                    "rating": 3,
                    "organization_count": 0,
                },
                {
                    "rating": 4,
                    "organization_count": 0,
                },
                {
                    "rating": 5,
                    "organization_count": 8,
                },
            ],
        )

    def test_size_distribution_includes_all_sizes(self):
        cursor = MagicMock()

        cursor.fetchall.return_value = [
            {
                "org_size": "small",
                "organization_count": 10,
            }
        ]

        result = org_api.fetch_organizations_by_size(
            cursor,
            "ALL",
            "ALL",
            "ALL",
        )

        self.assertEqual(
            result,
            [
                {
                    "org_size": "small",
                    "organization_count": 10,
                },
                {
                    "org_size": "medium",
                    "organization_count": 0,
                },
                {
                    "org_size": "large",
                    "organization_count": 0,
                },
            ],
        )

    def test_collaborator_contributor_percentages(self):
        cursor = MagicMock()

        cursor.fetchone.return_value = {
            "total_organizations": 40,
            "collaborator_count": 21,
            "contributor_count": 19,
        }

        result = org_api.fetch_collaborator_vs_contributor(
            cursor,
            "ALL",
            "ALL",
            "ALL",
        )

        self.assertEqual(
            result[0]["percentage"],
            52.5,
        )

        self.assertEqual(
            result[1]["percentage"],
            47.5,
        )

    @patch.object(
        org_api,
        "get_db_connection",
    )
    def test_lambda_handler_success(
        self,
        mock_connection,
    ):
        conn = MagicMock()
        cursor = MagicMock()

        conn.cursor.return_value = cursor
        mock_connection.return_value = conn

        with patch.object(
            org_api,
            "fetch_summary",
            return_value={
                "total_organizations": 1,
                "total_collaborators": 1,
                "total_contributors": 0,
                "average_org_rating": 5.0,
            },
        ), patch.object(
            org_api,
            "fetch_growth_trend",
            return_value=[],
        ), patch.object(
            org_api,
            "fetch_organizations_by_location",
            return_value=[],
        ), patch.object(
            org_api,
            "fetch_organizations_by_size",
            return_value=[],
        ), patch.object(
            org_api,
            "fetch_collaborator_vs_contributor",
            return_value=[],
        ), patch.object(
            org_api,
            "fetch_rating_distribution",
            return_value=[],
        ), patch.object(
            org_api,
            "fetch_organization_type_distribution",
            return_value=[],
        ):

            result = org_api.lambda_handler(
                {
                    "time_filter": "30D",
                    "group_by": "daily",
                    "region": "ALL",
                    "organization_type": "ALL",
                },
                None,
            )

        self.assertEqual(
            result["statusCode"],
            200,
        )

        body = json.loads(
            result["body"]
        )

        self.assertIn(
            "summary",
            body,
        )

        self.assertIn(
            "growth_trend",
            body,
        )

        self.assertIn(
            "organizations_by_location",
            body,
        )

        self.assertIn(
            "organizations_by_size",
            body,
        )

        self.assertIn(
            "collaborator_vs_contributor",
            body,
        )

        self.assertIn(
            "rating_distribution",
            body,
        )

        self.assertIn(
            "organization_type_distribution",
            body,
        )

    @patch.object(
        org_api,
        "get_db_connection",
        side_effect=Exception("DB unavailable"),
    )
    def test_database_exception(
        self,
        mock_connection,
    ):
        result = org_api.lambda_handler(
            {
                "time_filter": "30D",
                "group_by": "daily",
                "region": "ALL",
                "organization_type": "ALL",
            },
            None,
        )

        self.assertEqual(
            result["statusCode"],
            500,
        )

        body = json.loads(
            result["body"]
        )

        self.assertIn(
            "error",
            body,
        )

    def test_invalid_request_returns_400(self):
        result = org_api.lambda_handler(
            {
                "time_filter": "INVALID",
                "group_by": "daily",
                "region": "ALL",
                "organization_type": "ALL",
            },
            None,
        )

        self.assertEqual(
            result["statusCode"],
            400,
        )


if __name__ == "__main__":
    unittest.main()