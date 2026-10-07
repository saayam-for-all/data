import pytest

from src.profanity_routing import (
    InvalidProfanityScoreError,
    build_help_request_text,
    evaluate_help_request_profanity,
    extract_severity_score,
    route_for_score,
)


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


@pytest.mark.parametrize("api_response", [{"score": 4}, {"score": "high"}, {"result": {}}])
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


def test_route_for_score_blocks_highest_severity_requests():
    assert route_for_score(3) == {
        "severity_score": 3,
        "action": "reject_request",
        "workflow": "blocked_request",
        "database_table": "proposed_saayam.rejected_requests",
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
