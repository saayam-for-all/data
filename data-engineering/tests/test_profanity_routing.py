import pytest
import requests

from src.profanity_routing import (
    InvalidProfanityScoreError,
    ProfanityApiError,
    build_help_request_text,
    call_profanity_api,
    evaluate_help_request_profanity,
    extract_severity_score,
    route_for_score,
)


class FakeResponse:
    def __init__(self, payload=None, status_error=None, json_error=None):
        self.payload = payload
        self.status_error = status_error
        self.json_error = json_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

        pass

    def json(self):
        if self.json_error:
            raise self.json_error

        return self.payload


def test_build_help_request_text_combines_supported_fields():
    payload = {
        "subject": "Need a ride",
        "description": "I need help getting to a clinic.",
        "unrelated": "ignored",
    }

    assert build_help_request_text(payload) == "I need help getting to a clinic. Need a ride"


def test_build_help_request_text_requires_content():
    with pytest.raises(ValueError):
        build_help_request_text({"unrelated": "ignored"})


def test_build_help_request_text_rejects_whitespace_only_content():
    with pytest.raises(ValueError):
        build_help_request_text({"subject": "   ", "description": "  "})


def test_build_help_request_text_rejects_non_object_payload():
    with pytest.raises(ValueError):
        build_help_request_text(["Need help"])


@pytest.mark.parametrize(
    "api_response",
    [
        {"severity_score": 2},
        {"severityScore": "2"},
        {"classification_score": 2},
        {"result": {"score": 2}},
        {"data": {"classification": {"severityScore": 2}}},
    ],
)
def test_extract_severity_score_supports_common_response_shapes(api_response):
    assert extract_severity_score(api_response) == 2


@pytest.mark.parametrize(
    "api_response",
    [{"score": 4}, {"score": "high"}, {"result": {}}, {"score": True}, {"score": 2.7}],
)
def test_extract_severity_score_rejects_unusable_values(api_response):
    with pytest.raises(InvalidProfanityScoreError):
        extract_severity_score(api_response)


def test_route_for_score_accepts_clean_requests_for_matching():
    assert route_for_score(0) == {
        "severity_score": 0,
        "action": "accept_request",
        "workflow": "active_matching",
        "database_table": "proposed_saayam.request",
        "allow_active_matching": True,
    }


@pytest.mark.parametrize(
    ("score", "action", "workflow"),
    [
        (1, "send_to_initial_review", "content_review"),
        (2, "send_to_moderation", "moderation_review"),
    ],
)
def test_route_for_score_holds_review_requests_in_request_table(score, action, workflow):
    assert route_for_score(score) == {
        "severity_score": score,
        "action": action,
        "workflow": workflow,
        "database_table": "proposed_saayam.request",
        "allow_active_matching": False,
    }


def test_route_for_score_blocks_highest_severity_requests():
    assert route_for_score(3) == {
        "severity_score": 3,
        "action": "reject_request",
        "workflow": "blocked_request",
        "database_table": "proposed_saayam.fraud_requests",
        "allow_active_matching": False,
    }


def test_evaluate_help_request_profanity_calls_client_and_returns_route():
    seen_text = None

    def fake_client(text):
        nonlocal seen_text
        seen_text = text
        return {"score": 1}

    result = evaluate_help_request_profanity(
        {"title": "Food pickup", "request_content": "Need help this weekend."},
        profanity_client=fake_client,
    )

    assert seen_text == "Need help this weekend. Food pickup"
    assert result["severity_score"] == 1
    assert result["route"]["workflow"] == "content_review"


def test_call_profanity_api_requires_url(monkeypatch):
    monkeypatch.delenv("PROFANITY_API_URL", raising=False)

    with pytest.raises(ProfanityApiError):
        call_profanity_api("hello")


def test_call_profanity_api_sends_text_and_auth(monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured.update(json=json, headers=headers)
        return FakeResponse({"score": 0})

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setenv("PROFANITY_API_KEY", "test-key")

    assert call_profanity_api("hello", api_url="http://api.test") == {"score": 0}
    assert captured["json"] == {"text": "hello"}
    assert captured["headers"] == {"Authorization": "Bearer test-key"}


def test_call_profanity_api_wraps_connection_errors(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(ProfanityApiError):
        call_profanity_api("hello", api_url="http://api.test")


def test_call_profanity_api_wraps_http_status_errors(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: FakeResponse(status_error=requests.HTTPError("bad status")),
    )

    with pytest.raises(ProfanityApiError):
        call_profanity_api("hello", api_url="http://api.test")


def test_call_profanity_api_wraps_invalid_json(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: FakeResponse(json_error=ValueError("invalid json")),
    )

    with pytest.raises(ProfanityApiError):
        call_profanity_api("hello", api_url="http://api.test")


def test_call_profanity_api_rejects_non_object_json(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse([1, 2]))

    with pytest.raises(ProfanityApiError):
        call_profanity_api("hello", api_url="http://api.test")
