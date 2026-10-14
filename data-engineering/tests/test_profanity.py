"""Tests for Profanity API integration and Help Request routing (Issue #422)."""

import os
import unittest
from unittest.mock import MagicMock, Mock, patch

import requests

# Prevent real DB connection at import time
from src.extensions import db as _db

_db.create_all = lambda *args, **kwargs: None

from src.app import app  # noqa: E402
from src.profanity import (  # noqa: E402
    DEFAULT_TIMEOUT_SECONDS,
    PROFANITY_API_KEY_ENV,
    PROFANITY_API_URL_ENV,
    InvalidSeverityScoreError,
    ProfanityApiError,
    _coerce_score,
    call_profanity_api,
    evaluate_help_request,
    extract_help_request_text,
    get_routing_decision,
    parse_profanity_response,
)


class TestCoerceScore(unittest.TestCase):
    """Unit tests for _coerce_score."""

    def test_valid_integer_scores(self):
        for score in (0, 1, 2, 3):
            self.assertEqual(_coerce_score(score), score)

    def test_valid_numeric_string_scores(self):
        for score_str, expected in [("0", 0), ("1", 1), ("2", 2), ("3", 3)]:
            self.assertEqual(_coerce_score(score_str), expected)

    def test_valid_integer_float(self):
        self.assertEqual(_coerce_score(2.0), 2)

    def test_rejection_of_booleans(self):
        with self.assertRaises(InvalidSeverityScoreError):
            _coerce_score(True)
        with self.assertRaises(InvalidSeverityScoreError):
            _coerce_score(False)

    def test_rejection_of_non_integer_floats(self):
        with self.assertRaises(InvalidSeverityScoreError):
            _coerce_score(1.5)

    def test_rejection_of_out_of_range(self):
        for invalid in (-1, 4, 10, -99):
            with self.assertRaises(InvalidSeverityScoreError):
                _coerce_score(invalid)

    def test_rejection_of_invalid_types_and_strings(self):
        for invalid in ("invalid", None, [], {}, "4"):
            with self.assertRaises(InvalidSeverityScoreError):
                _coerce_score(invalid)


class TestExtractHelpRequestText(unittest.TestCase):
    """Unit tests for extract_help_request_text."""

    def test_subject_and_description(self):
        payload = {
            "subject": "Need groceries",
            "description": "I need help with buying groceries this week.",
        }
        text = extract_help_request_text(payload)
        self.assertEqual(text, "Need groceries I need help with buying groceries this week.")

    def test_req_subj_and_req_desc(self):
        payload = {
            "req_subj": "Urgent shelter",
            "req_desc": "Looking for temporary shelter.",
        }
        text = extract_help_request_text(payload)
        self.assertEqual(text, "Urgent shelter Looking for temporary shelter.")

    def test_content_field_only(self):
        payload = {"content": "Help with medicines"}
        self.assertEqual(extract_help_request_text(payload), "Help with medicines")

    def test_text_field_only(self):
        payload = {"text": "Assistance needed"}
        self.assertEqual(extract_help_request_text(payload), "Assistance needed")

    def test_deduplicates_identical_fields(self):
        payload = {
            "subject": "Same text",
            "title": "Same text",
            "description": "Different detail",
        }
        self.assertEqual(extract_help_request_text(payload), "Same text Different detail")

    def test_non_dict_payload_rejected(self):
        with self.assertRaises(ValueError):
            extract_help_request_text("not-a-dict")  # type: ignore

    def test_empty_payload_rejected(self):
        with self.assertRaises(ValueError):
            extract_help_request_text({})

    def test_whitespace_only_payload_rejected(self):
        with self.assertRaises(ValueError):
            extract_help_request_text({"subject": "   ", "description": "\t\n"})


class TestCallProfanityApi(unittest.TestCase):
    """Unit tests for call_profanity_api."""

    @patch("requests.post")
    def test_successful_api_call(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"severity_score": 0}
        mock_post.return_value = mock_response

        with patch.dict(os.environ, {PROFANITY_API_URL_ENV: "https://api.example.com/check"}):
            result = call_profanity_api("Clean content", subject="Subj", description="Desc")

        self.assertEqual(result, {"severity_score": 0})
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.example.com/check")
        self.assertEqual(kwargs["json"]["text"], "Clean content")
        self.assertEqual(kwargs["json"]["subject"], "Subj")
        self.assertEqual(kwargs["json"]["description"], "Desc")
        self.assertEqual(kwargs["timeout"], DEFAULT_TIMEOUT_SECONDS)

    @patch("requests.post")
    def test_positional_subject_and_description_call(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"severity_score": 1}
        mock_post.return_value = mock_response

        with patch.dict(os.environ, {PROFANITY_API_URL_ENV: "https://api.example.com/check"}):
            result = call_profanity_api("Subject text", "Description text")

        self.assertEqual(result, {"severity_score": 1})
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["text"], "Subject text Description text")
        self.assertEqual(kwargs["json"]["subject"], "Subject text")
        self.assertEqual(kwargs["json"]["description"], "Description text")

    def test_aliases_present(self):
        from src.profanity import ProfanityAPIError, SEVERITY_LABELS, SEVERITY_REASONS
        self.assertIs(ProfanityAPIError, ProfanityApiError)
        self.assertIs(SEVERITY_REASONS, SEVERITY_LABELS)

    @patch("requests.post")
    def test_api_call_with_api_key(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"score": 1}
        mock_post.return_value = mock_response

        with patch.dict(os.environ, {
            PROFANITY_API_URL_ENV: "https://api.example.com/check",
            PROFANITY_API_KEY_ENV: "secret-key-123",
        }):
            call_profanity_api("Some text")

        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-key-123")

    def test_missing_api_url_raises_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProfanityApiError):
                call_profanity_api("Some text")

    def test_empty_text_raises_value_error(self):
        with self.assertRaises(ValueError):
            call_profanity_api("   ", api_url="https://api.example.com")

    @patch("requests.post")
    def test_network_failure_raises_profanity_api_error(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("Connection failed")
        with patch.dict(os.environ, {PROFANITY_API_URL_ENV: "https://api.example.com/check"}):
            with self.assertRaises(ProfanityApiError):
                call_profanity_api("Some text")

    @patch("requests.post")
    def test_http_error_status_raises_profanity_api_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        mock_post.return_value = mock_response
        with patch.dict(os.environ, {PROFANITY_API_URL_ENV: "https://api.example.com/check"}):
            with self.assertRaises(ProfanityApiError):
                call_profanity_api("Some text")

    @patch("requests.post")
    def test_invalid_json_response_raises_profanity_api_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_post.return_value = mock_response
        with patch.dict(os.environ, {PROFANITY_API_URL_ENV: "https://api.example.com/check"}):
            with self.assertRaises(ProfanityApiError):
                call_profanity_api("Some text")


class TestParseProfanityResponse(unittest.TestCase):
    """Unit tests for parse_profanity_response."""

    def test_single_score_0_good_request(self):
        result = parse_profanity_response({"severity_score": 0})
        self.assertEqual(result["severity_score"], 0)
        self.assertFalse(result["is_flagged"])
        self.assertEqual(result["reason"], "Good Request")
        self.assertEqual(result["flagged_categories"], [])

    def test_single_score_1_foul_language(self):
        result = parse_profanity_response({"score": 1})
        self.assertEqual(result["severity_score"], 1)
        self.assertTrue(result["is_flagged"])
        self.assertEqual(result["reason"], "Foul Language")
        self.assertEqual(len(result["flagged_categories"]), 1)

    def test_single_score_2_depressive_content(self):
        result = parse_profanity_response({"classification_score": 2})
        self.assertEqual(result["severity_score"], 2)
        self.assertTrue(result["is_flagged"])
        self.assertEqual(result["reason"], "Depressive or Suicidal Content")

    def test_single_score_3_threatening_content(self):
        result = parse_profanity_response({"classificationScore": 3})
        self.assertEqual(result["severity_score"], 3)
        self.assertTrue(result["is_flagged"])
        self.assertEqual(result["reason"], "Threatening Content")

    def test_alternative_score_keys(self):
        for key in ("severity_score", "severityScore", "classification_score", "classificationScore", "score"):
            result = parse_profanity_response({key: 1})
            self.assertEqual(result["severity_score"], 1)

    def test_nested_result_wrapper(self):
        result = parse_profanity_response({"result": {"severity_score": 2}})
        self.assertEqual(result["severity_score"], 2)
        self.assertEqual(result["reason"], "Depressive or Suicidal Content")

    def test_nested_data_wrapper(self):
        result = parse_profanity_response({"data": {"score": 3}})
        self.assertEqual(result["severity_score"], 3)

    def test_nested_classification_wrapper(self):
        result = parse_profanity_response({"classification": {"score": 0}})
        self.assertEqual(result["severity_score"], 0)

    def test_multi_category_response_single_flagged(self):
        payload = {
            "severity_scores": [
                {"score": 1, "category": "Foul Language", "flagged": True},
                {"score": 2, "category": "Depressive or Suicidal Content", "flagged": False},
            ]
        }
        result = parse_profanity_response(payload)
        self.assertEqual(result["severity_score"], 1)
        self.assertTrue(result["is_flagged"])
        self.assertEqual(len(result["flagged_categories"]), 1)

    def test_multi_category_response_multiple_flagged_picks_highest(self):
        payload = {
            "severity_scores": [
                {"score": 1, "category": "Foul Language", "flagged": True},
                {"score": 3, "category": "Threatening Content", "flagged": True},
            ]
        }
        result = parse_profanity_response(payload)
        self.assertEqual(result["severity_score"], 3)
        self.assertTrue(result["is_flagged"])
        self.assertEqual(result["reason"], "Threatening Content")
        self.assertEqual(len(result["flagged_categories"]), 2)

    def test_multi_category_response_none_flagged(self):
        payload = {
            "severity_scores": [
                {"score": 0, "category": "Normal", "flagged": False},
                {"score": 1, "category": "Profanity", "flagged": False},
            ]
        }
        result = parse_profanity_response(payload)
        self.assertEqual(result["severity_score"], 0)
        self.assertFalse(result["is_flagged"])
        self.assertEqual(result["reason"], "Good Request")
        self.assertEqual(result["flagged_categories"], [])

    def test_multi_category_invalid_structure(self):
        with self.assertRaises(ProfanityApiError):
            parse_profanity_response({"severity_scores": []})
        with self.assertRaises(ProfanityApiError):
            parse_profanity_response({"severity_scores": ["not-a-dict"]})
        with self.assertRaises(ProfanityApiError):
            parse_profanity_response({"severity_scores": [{"score": 1, "category": "", "flagged": True}]})
        with self.assertRaises(ProfanityApiError):
            parse_profanity_response({"severity_scores": [{"score": 1, "category": "cat", "flagged": "yes"}]})

    def test_invalid_score_type(self):
        with self.assertRaises(InvalidSeverityScoreError):
            parse_profanity_response({"severity_score": True})
        with self.assertRaises(InvalidSeverityScoreError):
            parse_profanity_response({"severity_score": 1.5})
        with self.assertRaises(InvalidSeverityScoreError):
            parse_profanity_response({"severity_score": 4})

    def test_missing_score_field_raises_error(self):
        with self.assertRaises(ProfanityApiError):
            parse_profanity_response({"status": "ok"})


class TestGetRoutingDecision(unittest.TestCase):
    """Unit tests for get_routing_decision."""

    def test_routing_score_0(self):
        decision = get_routing_decision(0)
        self.assertEqual(decision["severity_score"], 0)
        self.assertEqual(decision["destination"], "active_matching")
        self.assertEqual(decision["database_table"], "proposed_saayam.request")
        self.assertEqual(decision["action"], "accept_request")
        self.assertTrue(decision["allow_active_matching"])
        self.assertFalse(decision["is_flagged"])
        self.assertEqual(decision["reason"], "Good Request")

    def test_routing_score_1(self):
        decision = get_routing_decision(1)
        self.assertEqual(decision["severity_score"], 1)
        self.assertEqual(decision["destination"], "fraud_requests")
        self.assertEqual(decision["database_table"], "proposed_saayam.fraud_requests")
        self.assertEqual(decision["action"], "route_to_fraud_requests")
        self.assertFalse(decision["allow_active_matching"])
        self.assertTrue(decision["is_flagged"])
        self.assertEqual(decision["reason"], "Foul Language")

    def test_routing_score_2(self):
        decision = get_routing_decision(2)
        self.assertEqual(decision["severity_score"], 2)
        self.assertEqual(decision["destination"], "fraud_requests")
        self.assertEqual(decision["reason"], "Depressive or Suicidal Content")

    def test_routing_score_3(self):
        decision = get_routing_decision(3)
        self.assertEqual(decision["severity_score"], 3)
        self.assertEqual(decision["destination"], "fraud_requests")
        self.assertEqual(decision["reason"], "Threatening Content")

    def test_invalid_score_raises_error(self):
        with self.assertRaises(InvalidSeverityScoreError):
            get_routing_decision(5)


class TestEvaluateHelpRequest(unittest.TestCase):
    """Unit tests for evaluate_help_request."""

    @patch.dict(os.environ, {
        PROFANITY_API_URL_ENV: "https://classifier.example/test",
    })
    @patch("src.profanity.requests.post")
    def test_default_client_calls_http_api(self, mock_post):
        """Exercise evaluation and the real API client, mocking only HTTP."""
        mock_post.return_value.json.return_value = {"score": 0}

        result = evaluate_help_request({
            "subject": "Need groceries",
            "description": "Need food items",
        })

        self.assertEqual(result["severity_score"], 0)
        self.assertTrue(result["allow_active_matching"])
        mock_post.assert_called_once()
        self.assertEqual(
            mock_post.call_args.args[0], "https://classifier.example/test",
        )
        self.assertEqual(mock_post.call_args.kwargs["json"], {
            "text": "Need groceries Need food items",
            "content": "Need groceries Need food items",
            "subject": "Need groceries",
            "description": "Need food items",
        })

    def test_evaluation_clean_request(self):
        mock_client = Mock(return_value={"score": 0})
        payload = {"subject": "Need groceries", "description": "Need food items"}
        result = evaluate_help_request(payload, api_client=mock_client)

        self.assertEqual(result["severity_score"], 0)
        self.assertFalse(result["is_flagged"])
        self.assertEqual(result["destination"], "active_matching")
        self.assertEqual(result["database_table"], "proposed_saayam.request")
        self.assertEqual(result["reason"], "Good Request")
        mock_client.assert_called_once_with("Need groceries Need food items")

    def test_evaluation_flagged_request(self):
        mock_client = Mock(return_value={"score": 2})
        payload = {"subject": "Need support", "description": "Feeling severely depressed and suicidal"}
        result = evaluate_help_request(payload, api_client=mock_client)

        self.assertEqual(result["severity_score"], 2)
        self.assertTrue(result["is_flagged"])
        self.assertEqual(result["destination"], "fraud_requests")
        self.assertEqual(result["database_table"], "proposed_saayam.fraud_requests")
        self.assertEqual(result["reason"], "Depressive or Suicidal Content")


class TestCheckProfanityFlaskRoute(unittest.TestCase):
    """Integration tests for the Flask POST /api/check_profanity route."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    @patch("src.app.db.session.commit")
    @patch("src.app.db.session.add")
    @patch("src.app.evaluate_help_request")
    def test_score_0_routes_to_active_matching_and_does_not_save_fraud(
        self, mock_eval, mock_add, mock_commit
    ):
        mock_eval.return_value = {
            "is_flagged": False,
            "severity_score": 0,
            "reason": "Good Request",
            "destination": "active_matching",
            "database_table": "proposed_saayam.request",
            "action": "accept_request",
            "allow_active_matching": True,
            "flagged_categories": [],
        }

        response = self.client.post(
            "/api/check_profanity",
            json={
                "user_id": "user-123",
                "subject": "Need medical help",
                "description": "I need help with medicine delivery.",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertFalse(data["is_flagged"])
        self.assertEqual(data["severity_score"], 0)
        self.assertEqual(data["destination"], "active_matching")
        self.assertEqual(data["database_table"], "proposed_saayam.request")
        self.assertTrue(data["allow_active_matching"])
        mock_add.assert_not_called()
        mock_commit.assert_not_called()

    @patch("src.app.db.session.commit")
    @patch("src.app.db.session.add")
    @patch("src.app.evaluate_help_request")
    def test_score_1_routes_to_fraud_requests_and_records_row(
        self, mock_eval, mock_add, mock_commit
    ):
        mock_eval.return_value = {
            "is_flagged": True,
            "severity_score": 1,
            "reason": "Foul Language",
            "destination": "fraud_requests",
            "database_table": "proposed_saayam.fraud_requests",
            "action": "route_to_fraud_requests",
            "allow_active_matching": False,
            "flagged_categories": [{"score": 1, "category": "Foul Language"}],
        }

        response = self.client.post(
            "/api/check_profanity",
            json={
                "user_id": "user-456",
                "subject": "Bad word in title",
                "description": "Profane description content",
                "request_date": "2026-10-13 14:00:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["is_flagged"])
        self.assertEqual(data["severity_score"], 1)
        self.assertEqual(data["destination"], "fraud_requests")
        self.assertEqual(data["reason"], "Foul Language")
        self.assertFalse(data["allow_active_matching"])

        mock_add.assert_called_once()
        mock_commit.assert_called_once()
        saved_fraud = mock_add.call_args[0][0]
        self.assertEqual(saved_fraud.user_id, "user-456")
        self.assertEqual(saved_fraud.reason, "Foul Language")

    @patch("src.app.db.session.commit")
    @patch("src.app.db.session.add")
    @patch("src.app.evaluate_help_request")
    def test_score_2_and_3_recorded_appropriately(
        self, mock_eval, mock_add, mock_commit
    ):
        for score, reason in [(2, "Depressive or Suicidal Content"), (3, "Threatening Content")]:
            mock_eval.return_value = {
                "is_flagged": True,
                "severity_score": score,
                "reason": reason,
                "destination": "fraud_requests",
                "database_table": "proposed_saayam.fraud_requests",
                "action": "route_to_fraud_requests",
                "allow_active_matching": False,
                "flagged_categories": [{"score": score, "category": reason}],
            }

            response = self.client.post(
                "/api/check_profanity",
                json={
                    "user_id": f"user-{score}",
                    "content": f"Test content for score {score}",
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["severity_score"], score)
            self.assertEqual(data["destination"], "fraud_requests")

    def test_missing_json_body_returns_400(self):
        response = self.client.post(
            "/api/check_profanity",
            data="plain text",
            content_type="text/plain",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_missing_user_id_returns_400(self):
        response = self.client.post(
            "/api/check_profanity",
            json={"subject": "Need help", "description": "Details here"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "user_id is required")

    def test_empty_user_id_returns_400(self):
        response = self.client.post(
            "/api/check_profanity",
            json={"user_id": "   ", "subject": "Need help"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "user_id must not be empty")

    def test_boolean_user_id_returns_400(self):
        response = self.client.post(
            "/api/check_profanity",
            json={"user_id": True, "subject": "Need help"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "user_id must be a string or integer")

    @patch("src.app.evaluate_help_request")
    def test_missing_content_returns_400(self, mock_eval):
        mock_eval.side_effect = ValueError("Help request text (subject/description/content) is required")
        response = self.client.post(
            "/api/check_profanity",
            json={"user_id": "123", "subject": "", "description": ""},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    @patch("src.app.evaluate_help_request")
    def test_profanity_api_failure_returns_502(self, mock_eval):
        mock_eval.side_effect = ProfanityApiError("Upstream API unreachable")
        response = self.client.post(
            "/api/check_profanity",
            json={"user_id": "123", "subject": "Valid text", "description": "Valid desc"},
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.get_json()["error"],
            "Unable to classify the request at this time",
        )

    @patch("src.app.db.session.rollback")
    @patch("src.app.db.session.commit")
    @patch("src.app.db.session.add")
    @patch("src.app.evaluate_help_request")
    def test_database_failure_rolls_back_and_returns_500(
        self, mock_eval, mock_add, mock_commit, mock_rollback
    ):
        mock_eval.return_value = {
            "is_flagged": True,
            "severity_score": 1,
            "reason": "Foul Language",
            "destination": "fraud_requests",
            "database_table": "proposed_saayam.fraud_requests",
            "action": "route_to_fraud_requests",
            "allow_active_matching": False,
        }
        mock_commit.side_effect = RuntimeError("Database connection lost")

        response = self.client.post(
            "/api/check_profanity",
            json={"user_id": "123", "subject": "Valid text", "description": "Profane word"},
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json()["error"],
            "Unable to record the flagged request",
        )
        mock_rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
