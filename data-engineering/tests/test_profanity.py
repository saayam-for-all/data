import json
import os
import unittest
from unittest.mock import Mock, patch

from src.profanity import (
    ProfanityAPIError,
    call_profanity_api,
    get_routing_decision,
    parse_profanity_response,
)


class TestRoutingDecision(unittest.TestCase):

    def test_score_zero_routes_to_matching(self):
        result = get_routing_decision(0)

        self.assertEqual(
            result["destination"],
            "active_matching",
        )
        self.assertEqual(result["severity_score"], 0)

    def test_scores_one_to_three_route_to_flagged_table(self):
        for score in (1, 2, 3):

            with self.subTest(score=score):
                result = get_routing_decision(score)

                self.assertEqual(
                    result["destination"],
                    "fraud_requests",
                )

    def test_invalid_scores_are_rejected(self):
        for value in (-1, 4, True, "1", None):

            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    get_routing_decision(value)


class TestResponseParsing(unittest.TestCase):

    def test_clean_request(self):
        result = parse_profanity_response({
            "severity_score": 0
        })

        self.assertEqual(result["severity_score"], 0)
        self.assertFalse(result["is_flagged"])

    def test_flagged_request(self):
        result = parse_profanity_response({
            "severity_score": 2
        })

        self.assertEqual(result["severity_score"], 2)
        self.assertTrue(result["is_flagged"])

    def test_highest_flagged_score_is_used(self):
        result = parse_profanity_response({
            "severity_scores": [
                {
                    "score": 1,
                    "category": "profanity",
                    "flagged": True,
                },
                {
                    "score": 3,
                    "category": "threat",
                    "flagged": True,
                },
            ]
        })

        self.assertEqual(result["severity_score"], 3)
        self.assertTrue(result["is_flagged"])

    def test_invalid_score_is_rejected(self):
        with self.assertRaises(ProfanityAPIError):
            parse_profanity_response({
                "severity_score": 4
            })

    def test_missing_score_is_rejected(self):
        with self.assertRaises(ProfanityAPIError):
            parse_profanity_response({
                "unexpected": "value"
            })


class TestProfanityAPI(unittest.TestCase):

    def setUp(self):
        self.endpoint = "https://example.test/checkProfanity"

        self.response = Mock()
        self.response.status = 200
        self.response.read.return_value = json.dumps({
            "severity_score": 0
        }).encode("utf-8")

    def test_api_request(self):
        opener = Mock(return_value=self.response)

        with patch.dict(
            os.environ,
            {"PROFANITY_API_URL": self.endpoint},
        ):
            result = call_profanity_api(
                "Need groceries",
                "Need assistance with groceries.",
                opener=opener,
            )

        self.assertEqual(result["severity_score"], 0)

        request_object = opener.call_args.args[0]

        self.assertEqual(
            request_object.get_method(),
            "POST",
        )

    def test_missing_api_url(self):
        with patch.dict(os.environ, {}, clear=True):

            with self.assertRaises(ProfanityAPIError):
                call_profanity_api(
                    "Need groceries",
                    "Need assistance.",
                    opener=Mock(),
                )

    def test_invalid_json(self):
        self.response.read.return_value = b"invalid-json"

        with patch.dict(
            os.environ,
            {"PROFANITY_API_URL": self.endpoint},
        ):
            with self.assertRaises(ProfanityAPIError):
                call_profanity_api(
                    "Need groceries",
                    "Need assistance.",
                    opener=Mock(
                        return_value=self.response
                    ),
                )


if __name__ == "__main__":
    unittest.main()
