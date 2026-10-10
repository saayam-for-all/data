
import unittest
import json
import os
from unittest.mock import Mock, patch

from src.profanity import get_routing_decision
from src.profanity import (
    get_routing_decision,
    call_profanity_api,
    parse_profanity_response,
    ProfanityAPIError,
)

class TestRoutingDecision(unittest.TestCase):

    def test_normal_request_goes_to_matching(self):
        result = get_routing_decision(0)

        self.assertEqual(result["destination"], "active_matching")
        self.assertEqual(result["reason"], "Good Request")

    def test_nonzero_scores_go_to_fraud_requests(self):
        for score in (1, 2, 3):
            with self.subTest(score=score):
                result = get_routing_decision(score)

                self.assertEqual(result["destination"], "fraud_requests")
                self.assertEqual(result["severity_score"], score)

    def test_invalid_scores_are_rejected(self):
        for score in (-1, 4, True, "1", None):
            with self.subTest(score=score):
                with self.assertRaises(ValueError):
                    get_routing_decision(score)

    def test_each_severity_has_the_expected_reason(self):
        expected_reasons = {
            0: "Good Request",
            1: "Foul Language",
            2: "Depressive or Suicidal Content",
            3: "Threatening Content",
        }

        for score, expected_reason in expected_reasons.items():
            with self.subTest(score=score):
                result = get_routing_decision(score)
                self.assertEqual(result["reason"], expected_reason)

    def test_result_contains_expected_fields(self):
        result = get_routing_decision(2)

        self.assertEqual(
            set(result.keys()),
            {"severity_score", "destination", "reason"},
        )


class TestProfanityResponse(unittest.TestCase):

    def test_clean_response_is_not_flagged(self):
        payload = {
            "severity_scores": [
                {"score": 0, "category": "normal", "flagged": True},
                {"score": 1, "category": "profanity", "flagged": False},
            ]
        }

        result = parse_profanity_response(payload)

        self.assertEqual(result["severity_score"], 0)
        self.assertFalse(result["is_flagged"])

    def test_highest_flagged_severity_is_selected(self):
        payload = {
            "severity_scores": [
                {"score": 1, "category": "profanity", "flagged": True},
                {"score": 3, "category": "threatening", "flagged": True},
            ]
        }

        result = parse_profanity_response(payload)

        self.assertEqual(result["severity_score"], 3)
        self.assertTrue(result["is_flagged"])

    def test_invalid_response_is_rejected(self):
        with self.assertRaises(ProfanityAPIError):
            parse_profanity_response({"unexpected": "data"})

    def test_invalid_score_is_rejected(self):
        payload = {
            "severity_scores": [
                {"score": 4, "category": "unknown", "flagged": True}
            ]
        }

        with self.assertRaises(ProfanityAPIError):
            parse_profanity_response(payload)
    def test_single_severity_score_response(self):
        result = parse_profanity_response({"severity_score": 2})

        self.assertEqual(result["severity_score"], 2)
        self.assertTrue(result["is_flagged"])

    def test_single_score_response(self):
        result = parse_profanity_response({"score": 0})

        self.assertEqual(result["severity_score"], 0)
        self.assertFalse(result["is_flagged"])

    def test_nested_result_score_response(self):
        result = parse_profanity_response({
            "result": {"classification_score": 3}
        })

        self.assertEqual(result["severity_score"], 3)
        self.assertTrue(result["is_flagged"])

class TestProfanityAPI(unittest.TestCase):

    def setUp(self):
        self.endpoint = (
            "https://example.test/requests/v0.0.1/checkProfanity"
        )
        self.payload = {
            "severity_scores": [
                {
                    "score": 0,
                    "category": "normal",
                    "flagged": False,
                }
            ]
        }
        self.response = Mock()
        self.response.status = 200
        self.response.read.return_value = json.dumps(
            self.payload
        ).encode("utf-8")

    def test_api_key_is_sent_when_configured(self):
        opener = Mock(return_value=self.response)

        with patch.dict(
            os.environ,
            {
                "PROFANITY_API_URL": self.endpoint,
                "PROFANITY_API_KEY": "test-key",
            },
        ):
            call_profanity_api(
                "Need groceries",
                "I need help getting groceries.",
                opener=opener,
            )

        request = opener.call_args.args[0]

        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer test-key",
        )
    def test_successful_api_request(self):
        opener = Mock(return_value=self.response)

        with patch.dict(
            os.environ,
            {"PROFANITY_API_URL": self.endpoint},
        ):
            result = call_profanity_api(
                "Need groceries",
                "I need help getting groceries.",
                opener=opener,
            )

        self.assertEqual(result, self.payload)
        opener.assert_called_once()
        request = opener.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {
                "text": "Need groceries I need help getting groceries.",
            },
        )
        self.assertEqual(
            request.get_header("Content-type"),
            "application/json",
        )
        self.response.close.assert_called_once()

    def test_missing_endpoint_is_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProfanityAPIError):
                call_profanity_api(
                    "Need groceries",
                    "I need help getting groceries.",
                    opener=Mock(),
                )

    def test_non_https_endpoint_is_rejected(self):
        with patch.dict(
            os.environ,
            {"PROFANITY_API_URL": "http://example.test/classifier"},
        ):
            with self.assertRaises(ProfanityAPIError):
                call_profanity_api(
                    "Need groceries",
                    "I need help getting groceries.",
                    opener=Mock(),
                )

    def test_invalid_json_response_is_rejected(self):
        self.response.read.return_value = b"not valid JSON"
        opener = Mock(return_value=self.response)

        with patch.dict(
            os.environ,
            {"PROFANITY_API_URL": self.endpoint},
        ):
            with self.assertRaises(ProfanityAPIError):
                call_profanity_api(
                    "Need groceries",
                    "I need help getting groceries.",
                    opener=opener,
                )

    def test_connection_failure_is_reported(self):
        opener = Mock(side_effect=OSError("simulated connection failure"))

        with patch.dict(
            os.environ,
            {"PROFANITY_API_URL": self.endpoint},
        ):
            with self.assertRaises(ProfanityAPIError):
                call_profanity_api(
                    "Need groceries",
                    "I need help getting groceries.",
                    opener=opener,
                )

    def test_empty_subject_is_rejected(self):
        with patch.dict(
            os.environ,
            {"PROFANITY_API_URL": self.endpoint},
        ):
            with self.assertRaises(ValueError):
                call_profanity_api(
                    " ",
                    "I need help getting groceries.",
                    opener=Mock(),
                )

if __name__ == "__main__":
    unittest.main()