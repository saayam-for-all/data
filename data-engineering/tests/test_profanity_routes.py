import unittest
from unittest.mock import patch

from flask import Flask

from src.profanity import ProfanityAPIError
from src.profanity_routes import profanity_bp


class TestProfanityRoutes(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(profanity_bp)

        self.client = self.app.test_client()

        self.payload = {
            "user_id": "user-123",
            "subject": "Need groceries",
            "description": "Need assistance getting groceries.",
        }

    @patch("src.profanity_routes.db.session.commit")
    @patch("src.profanity_routes.db.session.add")
    @patch("src.profanity_routes.call_profanity_api")
    def test_score_zero_routes_to_matching(
        self,
        mock_api,
        mock_add,
        mock_commit,
    ):
        mock_api.return_value = {
            "severity_score": 0
        }

        response = self.client.post(
            "/api/check_profanity",
            json=self.payload,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json["severity_score"],
            0,
        )
        self.assertEqual(
            response.json["destination"],
            "active_matching",
        )

        mock_add.assert_not_called()
        mock_commit.assert_not_called()

    @patch("src.profanity_routes.db.session.commit")
    @patch("src.profanity_routes.db.session.add")
    @patch("src.profanity_routes.call_profanity_api")
    def test_nonzero_score_routes_to_fraud_requests(
        self,
        mock_api,
        mock_add,
        mock_commit,
    ):
        mock_api.return_value = {
            "severity_score": 1
        }

        response = self.client.post(
            "/api/check_profanity",
            json=self.payload,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json["severity_score"],
            1,
        )
        self.assertEqual(
            response.json["destination"],
            "fraud_requests",
        )

        mock_add.assert_called_once()
        mock_commit.assert_called_once()

    def test_missing_subject_returns_400(self):
        payload = dict(self.payload)
        payload.pop("subject")

        response = self.client.post(
            "/api/check_profanity",
            json=payload,
        )

        self.assertEqual(response.status_code, 400)

    @patch("src.profanity_routes.call_profanity_api")
    def test_classifier_failure_returns_502(
        self,
        mock_api,
    ):
        mock_api.side_effect = ProfanityAPIError(
            "classifier unavailable"
        )

        response = self.client.post(
            "/api/check_profanity",
            json=self.payload,
        )

        self.assertEqual(response.status_code, 502)

    @patch("src.profanity_routes.db.session.rollback")
    @patch("src.profanity_routes.db.session.commit")
    @patch("src.profanity_routes.db.session.add")
    @patch("src.profanity_routes.call_profanity_api")
    def test_database_failure_rolls_back(
        self,
        mock_api,
        mock_add,
        mock_commit,
        mock_rollback,
    ):
        mock_api.return_value = {
            "severity_score": 3
        }

        mock_commit.side_effect = RuntimeError(
            "database unavailable"
        )

        response = self.client.post(
            "/api/check_profanity",
            json=self.payload,
        )

        self.assertEqual(response.status_code, 500)
        mock_add.assert_called_once()
        mock_rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
