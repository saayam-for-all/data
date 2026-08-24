import json
import unittest
from unittest.mock import MagicMock, patch

from organization_analytics import lambda_handler


class TestOrganizationAnalytics(unittest.TestCase):

    @patch("organization_analytics.get_db_connection")
    def test_organization_analytics_success(self, mock_get_db):
        """Test single response payload containing all 7 dashboard components."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock query return values in exact sequence of execution inside fetch_organization_analytics
        mock_cursor.fetchone.side_effect = [
            # 1. Summary KPIs
            {
                "total_organizations": 126,
                "total_collaborators": 42,
                "total_contributors": 84,
                "average_org_rating": 4.2,
            }
        ]

        mock_cursor.fetchall.side_effect = [
            # 2. Growth Trend
            [
                {
                    "period": "2026-01",
                    "total_organizations": 100,
                    "total_collaborators": 34,
                }
            ],
            # 3. Location Breakdown
            [
                {
                    "state_id": "CA",
                    "state_name": "California",
                    "organization_count": 32,
                    "percentage": 25.4,
                }
            ],
            # 4. Size Breakdown
            [{"org_size": "small", "organization_count": 50}],
            # 5. Collaborator vs Contributor
            [
                {
                    "type": "collaborator",
                    "organization_count": 42,
                    "percentage": 33.3,
                },
                {
                    "type": "contributor",
                    "organization_count": 84,
                    "percentage": 66.7,
                },
            ],
            # 6. Rating Distribution
            [{"rating": 1, "organization_count": 1}],
            # 7. Type Distribution Over Time
            [
                {
                    "period": "2026-01",
                    "for_profit": 41,
                    "non_profit": 68,
                    "total": 109,
                }
            ],
        ]

        event = {
            "time_filter": "30D",
            "group_by": "daily",
            "region": "ALL",
            "organization_type": "ALL",
        }

        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])

        # Validate presence of top-level response keys
        self.assertIn("summary", body)
        self.assertIn("growth_trend", body)
        self.assertIn("organizations_by_location", body)
        self.assertIn("organizations_by_size", body)
        self.assertIn("collaborator_vs_contributor", body)
        self.assertIn("rating_distribution", body)
        self.assertIn("organization_type_distribution", body)

        # Validate summary data values
        self.assertEqual(body["summary"]["total_organizations"], 126)
        self.assertEqual(body["summary"]["average_org_rating"], 4.2)

    @patch("organization_analytics.get_db_connection")
    def test_custom_date_range_and_filters(self, mock_get_db):
        """Test API behavior with CUSTOM date range, region, and org type filters."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {
            "total_organizations": 10,
            "total_collaborators": 5,
            "total_contributors": 5,
            "average_org_rating": 4.5,
        }
        mock_cursor.fetchall.return_value = []

        event = {
            "time_filter": "CUSTOM",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "group_by": "monthly",
            "region": "California",
            "organization_type": "non_profit",
        }

        response = lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)

    @patch("organization_analytics.get_db_connection")
    def test_database_exception_handling(self, mock_get_db):
        """Test database exception triggers DE 1001 failure."""
        mock_get_db.side_effect = Exception("Database error")

        event = {"time_filter": "30D"}
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 500)
        body = json.loads(response["body"])
        self.assertEqual(body["error_code"], "DE 1000")


if __name__ == "__main__":
    unittest.main()