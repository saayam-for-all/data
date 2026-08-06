import json
import unittest
from unittest.mock import MagicMock, patch

from organization_analytics import lambda_handler


class TestOrganizationAnalytics(unittest.TestCase):

    @patch("organization_analytics.get_db_connection")
    def test_overview_dashboard_success(self, mock_get_db):
        """Test overview dashboard returns correct structured data."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock database fetch responses for overview queries
        mock_cursor.fetchone.side_effect = [
            {
                "total_organizations": 120,
                "non_profit_organizations": 85,
                "for_profit_organizations": 35,
                "collaborator_organizations": 42,
                "non_collaborator_organizations": 78,
                "contributor_organizations": 65,
                "non_contributor_organizations": 55,
            }
        ]
        mock_cursor.fetchall.side_effect = [
            [{"period": "2026-07-01", "count": 10}],  # Trend
            [{"type": "Non-profit", "count": 85}],  # Types
            [{"size": "Medium", "count": 50}],  # Sizes
            [
                {"state": "California", "city": "Los Angeles", "count": 20}
            ],  # Locations
            [{"status": "collaborator", "count": 42}],  # Collab dist
            [{"status": "contributor", "count": 65}],  # Contrib dist
        ]

        event = {"dashboard_type": "overview", "time_filter": "30D"}
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertIn("organization_overview", body)
        self.assertEqual(
            body["organization_overview"]["summary"]["total_organizations"], 120
        )

    @patch("organization_analytics.get_db_connection")
    def test_performance_dashboard_success(self, mock_get_db):
        """Test performance dashboard returns correct structured data."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            {
                "average_rating": 4.2,
                "rated_organizations": 95,
                "unrated_organizations": 25,
                "five_star_organizations": 35,
            }
        ]
        mock_cursor.fetchall.side_effect = [
            [{"rating": 5, "count": 35}],  # Rating dist
            [{"id": 1, "name": "Org A", "rating": 5.0}],  # Top rated
            [{"id": 2, "name": "Collab B", "rating": 4.8}],  # Top collab
            [{"id": 3, "name": "Contrib C", "rating": 4.9}],  # Top contrib
            [{"type": "Non-profit", "average_rating": 4.5}],  # Type ratings
            [{"size": "Large", "average_rating": 4.6}],  # Size ratings
        ]

        event = {"dashboard_type": "performance", "time_filter": "1Y"}
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertIn("organization_performance", body)
        self.assertEqual(
            body["organization_performance"]["summary"]["average_rating"], 4.2
        )

    @patch("organization_analytics.get_db_connection")
    def test_invalid_dashboard_type(self, mock_get_db):
        """Test invalid dashboard type returns DE 1002 error."""
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn

        event = {"dashboard_type": "invalid_type"}
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 400)
        body = json.loads(response["body"])
        self.assertEqual(body["error_code"], "DE 1002")


if __name__ == "__main__":
    unittest.main()