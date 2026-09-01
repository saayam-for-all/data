import json
import unittest
from unittest.mock import MagicMock, patch

from available_volunteers_api import lambda_handler


class TestAvailableVolunteersAPI(unittest.TestCase):

    def test_missing_request_id(self):
        """Test API returns 400 when request_id is missing."""
        event = {}
        response = lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 400)
        body = json.loads(response["body"])
        self.assertEqual(body["error"], "request_id is required")

    @patch("available_volunteers_api.get_db_connection")
    def test_request_not_found(self, mock_get_db):
        """Test API returns 404 when request_id does not exist."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = None

        event = {"request_id": "REQ-INVALID"}
        response = lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 404)
        body = json.loads(response["body"])
        self.assertEqual(body["error"], "Request not found")

    @patch("available_volunteers_api.get_db_connection")
    def test_success_matching_volunteers(self, mock_get_db):
        """Test successful retrieval of eligible available volunteers."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock request lookup (non-in-person request)
        mock_cursor.fetchone.return_value = {
            "req_id": "REQ-00-000-000-001",
            "req_cat_id": 10,
            "req_type_id": 1,
            "type_name": "remote",
            "req_loc": "Online",
            "req_lat": None,
            "req_lon": None,
        }

        # Mock candidate volunteers lookup
        mock_cursor.fetchall.return_value = [
            {
                "user_id": "VOL-001",
                "name": "Jane Doe",
                "status": "Active",
                "skills": ["Food Assistance"],
                "vol_lat": None,
                "vol_lon": None,
            }
        ]

        event = {"request_id": "REQ-00-000-000-001"}
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["requestId"], "REQ-00-000-000-001")
        self.assertEqual(len(body["availableVolunteers"]), 1)
        self.assertEqual(body["availableVolunteers"][0]["volunteerId"], "VOL-001")
        self.assertEqual(body["availableVolunteers"][0]["skills"], ["Food Assistance"])

    @patch("available_volunteers_api.get_db_connection")
    def test_in_person_proximity_filtering(self, mock_get_db):
        """Test that in-person requests filter out volunteers outside proximity radius."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Request at (37.7749, -122.4194) - San Francisco
        mock_cursor.fetchone.return_value = {
            "req_id": "REQ-002",
            "req_cat_id": 5,
            "req_type_id": 2,
            "type_name": "in person",
            "req_loc": "San Francisco",
            "req_lat": 37.7749,
            "req_lon": -122.4194,
        }

        # Candidate 1: Nearby (~5 km away), Candidate 2: Far away (~500 km away)
        mock_cursor.fetchall.return_value = [
            {
                "user_id": "VOL-NEAR",
                "name": "Nearby Vol",
                "status": "Active",
                "skills": ["Medical"],
                "vol_lat": 37.8044,
                "vol_lon": -122.2712,
            },
            {
                "user_id": "VOL-FAR",
                "name": "Far Vol",
                "status": "Active",
                "skills": ["Medical"],
                "vol_lat": 34.0522,
                "vol_lon": -118.2437,
            },
        ]

        event = {"request_id": "REQ-002"}
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(len(body["availableVolunteers"]), 1)
        self.assertEqual(body["availableVolunteers"][0]["volunteerId"], "VOL-NEAR")

    @patch("available_volunteers_api.get_db_connection")
    def test_database_exception_handling(self, mock_get_db):
        """Test safe error response when database query fails."""
        mock_get_db.side_effect = Exception("DB Connection Failed")

        event = {"request_id": "REQ-001"}
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 500)
        body = json.loads(response["body"])
        self.assertEqual(body["error_code"], "DE 1000")


if __name__ == "__main__":
    unittest.main()