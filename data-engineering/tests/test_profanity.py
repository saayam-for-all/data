"""Tests for Profanity API parsing and Help Request routing."""

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


class ParseProfanityResponseTests(unittest.TestCase):

    def test_accepts_scores_zero_through_three(self):
        for score in range(4):
            with self.subTest(score=score):
                self.assertEqual(
                    parse_profanity_response(
                        {"severity_score": score}
                    ),
                    score,
                )

    def test_unwraps_api_gateway_response(self):
        payload = {
            "statusCode": 200,
            "body": json.dumps({"severity_score": 2}),
        }

        self.assertEqual(parse_profanity_response(payload), 2)

    def test_uses_highest_severity_category(self):
        payload = {
            "contains_profanity": True,
            "contains_depressive_content": True,
            "contains_suicidal_content": False,
            "contains_threatening_content": True,
        }

        self.assertEqual(parse_profanity_response(payload), 3)

    def test_uses_highest_flagged_severity_entry(self):
        payload = {
            "severity_scores": [
                {"score": 0, "flagged": False},
                {"score": 1, "flagged": True},
                {"score": 2, "flagged": True},
                {"score": 3, "flagged": False},
            ]
        }

        self.assertEqual(parse_profanity_response(payload), 2)

    def test_rejects_invalid_score(self):
        with self.assertRaises(ProfanityAPIError):
            parse_profanity_response({"severity_score": 4})

    def test_rejects_conflicting_score_and_flags(self):
        payload = {
            "severity_score": 1,
            "contains_profanity": False,
            "contains_depressive_content": False,
            "contains_suicidal_content": False,
            "contains_threatening_content": True,
        }

        with self.assertRaises(ProfanityAPIError):
            parse_profanity_response(payload)


class RoutingDecisionTests(unittest.TestCase):

    def test_routes_score_zero_to_active_matching(self):
        decision = get_routing_decision(0)

        self.assertEqual(decision["destination"], "active_matching")
        self.assertFalse(decision["is_flagged"])
        self.assertEqual(decision["reason"], "Good Request")

    def test_routes_flagged_scores_to_fraud_requests(self):
        expected_reasons = {
            1: "Foul Language",
            2: "Depressive or Suicidal Content",
            3: "Threatening Content",
        }

        for score, reason in expected_reasons.items():
            with self.subTest(score=score):
                decision = get_routing_decision(score)

                self.assertEqual(
                    decision["destination"],
                    "fraud_requests",
                )
                self.assertTrue(decision["is_flagged"])
                self.assertEqual(decision["reason"], reason)


class CallProfanityAPITests(unittest.TestCase):

    @patch.dict(
        os.environ,
        {
            "PROFANITY_API_URL": "https://example.com/check",
            "PROFANITY_API_KEY": "test-key",
        },
    )
    @patch("src.profanity.requests.post")
    def test_calls_api_and_returns_score(self, mock_post):
        response = Mock()
        response.json.return_value = {"severity_score": 1}
        mock_post.return_value = response

        score = call_profanity_api(
            " Need food ",
            " Please help me ",
        )

        self.assertEqual(score, 1)
        response.raise_for_status.assert_called_once_with()
        mock_post.assert_called_once_with(
            "https://example.com/check",
            json={
                "subject": "Need food",
                "description": "Please help me",
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "x-api-key": "test-key",
            },
            timeout=(3.05, 15),
        )

    def test_rejects_empty_help_request_fields(self):
        with self.assertRaises(ValueError):
            call_profanity_api("", "Description")

        with self.assertRaises(ValueError):
            call_profanity_api("Subject", "   ")


if __name__ == "__main__":
    unittest.main()
