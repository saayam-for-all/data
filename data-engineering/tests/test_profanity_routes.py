
import unittest
from unittest.mock import Mock, patch

from flask import Flask

from src.profanity import ProfanityAPIError
from src.profanity_routes import profanity_bp


class TestProfanityRoutes(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(profanity_bp)
        self.client = self.app.test_client()

        self.request_data = {
            "user_id": "test-user-1",
            "subject": "Need groceries",
            "description": "I need help getting groceries.",
        }

    @patch("src.profanity_routes.db.session.commit")
    @patch("src.profanity_routes.db.session.add")
    @patch("src.profanity_routes.call_profanity_api")
    def test_clean_request_is_not_recorded(
        self, mock_api, mock_add, mock_commit
    ):
        mock_api.return_value = {
            "severity_scores": [
                {
                    "score": 0,
                    "category": "normal",
                    "flagged": False,
                }
            ]
        }

        response = self.client.post(
            "/api/check_profanity",
            json=self.request_data,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["is_flagged"])
        self.assertEqual(response.json["destination"], "active_matching")
        mock_add.assert_not_called()
        mock_commit.assert_not_called()

    @patch("src.profanity_routes.db.session.commit")
    @patch("src.profanity_routes.db.session.add")
    @patch("src.profanity_routes.call_profanity_api")
    def test_flagged_request_is_recorded(
        self, mock_api, mock_add, mock_commit
    ):
        mock_api.return_value = {
            "severity_scores": [
                {
                    "score": 2,
                    "category": "depressive_content",
                    "flagged": True,
                }
            ]
        }

        response = self.client.post(
            "/api/check_profanity",
            json=self.request_data,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["is_flagged"])
        self.assertEqual(response.json["severity_score"], 2)
        self.assertEqual(response.json["destination"], "fraud_requests")
        mock_add.assert_called_once()
        mock_commit.assert_called_once()

        recorded_object = mock_add.call_args.args[0]
        self.assertEqual(recorded_object.user_id, "test-user-1")
        self.assertEqual(
            recorded_object.reason,
            "Depressive or Suicidal Content",
        )

    def test_missing_request_body_is_rejected(self):
        response = self.client.post(
            "/api/check_profanity",
            data="not-json",
            content_type="text/plain",
        )

        self.assertEqual(response.status_code, 400)

    def test_missing_subject_is_rejected(self):
        data = dict(self.request_data)
        data.pop("subject")

        response = self.client.post(
            "/api/check_profanity",
            json=data,
        )

        self.assertEqual(response.status_code, 400)

    @patch("src.profanity_routes.call_profanity_api")
    def test_classifier_failure_returns_502(self, mock_api):
        mock_api.side_effect = ProfanityAPIError(
            "simulated classifier failure"
        )

        response = self.client.post(
            "/api/check_profanity",
            json=self.request_data,
        )

        self.assertEqual(response.status_code, 502)
        self.assertIn("error", response.json)

    @patch("src.profanity_routes.db.session.rollback")
    @patch("src.profanity_routes.db.session.commit")
    @patch("src.profanity_routes.db.session.add")
    @patch("src.profanity_routes.call_profanity_api")
    def test_database_failure_returns_500_and_rolls_back(
        self, mock_api, mock_add, mock_commit, mock_rollback
    ):
        mock_api.return_value = {
            "severity_scores": [
                {
                    "score": 1,
                    "category": "profanity",
                    "flagged": True,
                }
            ]
        }
        mock_commit.side_effect = RuntimeError(
            "simulated database failure"
        )

        response = self.client.post(
            "/api/check_profanity",
            json=self.request_data,
        )

        self.assertEqual(response.status_code, 500)
        mock_rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
