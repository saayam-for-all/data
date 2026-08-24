import json
import unittest
from unittest.mock import MagicMock, patch

from steward_volunteer_review_api import lambda_handler


class TestStewardVolunteerReviewAPI(unittest.TestCase):

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_fetch_reviews_success(self, mock_get_db):
        """Test successful pagination and retrieval of volunteer review requests."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock count query and paginated data query
        mock_cursor.fetchone.return_value = {"total_records": 20}
        mock_cursor.fetchall.return_value = [
            {
                "user_id": "SID-00-000-000-001",
                "updated_time": "2026-05-12T07:15:00Z",
                "volunteer_review": "Review",
            }
        ]

        event = {"page": 1, "page_size": 5}
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        body = response["body"]

        self.assertIn("data", body)
        self.assertIn("pagination", body)
        self.assertEqual(body["pagination"]["total_records"], 20)
        self.assertEqual(body["pagination"]["total_pages"], 4)
        self.assertEqual(body["pagination"]["current_page"], 1)
        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["data"][0]["user_id"], "SID-00-000-000-001")

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_empty_results_handling(self, mock_get_db):
        """Test API returns successful status 200 with empty array when no records exist."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {"total_records": 0}
        mock_cursor.fetchall.return_value = []

        event = {"page": 1, "page_size": 5}
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        body = response["body"]
        self.assertEqual(body["data"], [])
        self.assertEqual(body["pagination"]["total_records"], 0)
        self.assertEqual(body["pagination"]["total_pages"], 0)

    @patch("steward_volunteer_review_api.get_db_connection")
    def test_database_exception(self, mock_get_db):
        """Test safe error response when database connection fails."""
        mock_get_db.side_effect = Exception("Database error")

        event = {"page": 1, "page_size": 5}
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(response["body"]["error_code"], "DE 1000")


if __name__ == "__main__":
    unittest.main()