"""Tests for src/profanity.py (issue #422 - severity scoring and routing).

These cover the actual scope of #422: turning a profanity API response into a
severity score and deciding where the help request is routed. They run
standalone (no Flask, no database, no network) by mocking `requests` and by
passing a stand-in `profanity_client` into `evaluate_help_request`.

The Flask route (`/api/check_profanity` in src/app.py) that wires this into a
database write is exercised separately against a real Postgres instance, not
here - see the PR description. Importing src.app requires a live database at
module-import time (it calls db.create_all() eagerly) even before this
change, so it's outside what this repo's test suite can run standalone;
every route already in app.py has the same limitation, which is why none of
them have a committed test today either.
"""

import pytest

from src.profanity import (
    InvalidSeverityScoreError,
    ProfanityApiError,
    SENTIMENT_LABELS,
    call_profanity_api,
    evaluate_help_request,
    extract_help_request_text,
    extract_severity_score,
)


# --- extract_help_request_text --------------------------------------------------------
def test_extracts_req_desc():
    assert extract_help_request_text({"req_desc": "need groceries"}) == "need groceries"


def test_combines_subject_and_description_subject_first():
    text = extract_help_request_text({"req_subj": "Urgent", "req_desc": "need help"})
    assert text == "Urgent need help"


def test_field_order_is_independent_of_payload_key_order():
    # req_desc appears first in the dict, but req_subj must still come first in the
    # combined text, since TEXT_FIELDS order (not payload order) decides the order.
    text = extract_help_request_text({"req_desc": "need help", "req_subj": "Urgent"})
    assert text == "Urgent need help"


@pytest.mark.parametrize("key", ["req_desc", "description", "request_description",
                                  "content", "request_content", "req_subj", "subject", "title"])
def test_accepts_any_recognized_field_name(key):
    assert extract_help_request_text({key: "some text"}) == "some text"


def test_deduplicates_identical_fields():
    # req_desc and description both point at the same text in some payload shapes
    text = extract_help_request_text({"req_desc": "need help", "description": "need help"})
    assert text == "need help"


def test_strips_whitespace():
    assert extract_help_request_text({"req_desc": "  need help  "}) == "need help"


@pytest.mark.parametrize("payload", [{}, {"req_desc": ""}, {"req_desc": None}, {"user_id": "u1"}])
def test_missing_text_raises_value_error(payload):
    with pytest.raises(ValueError, match="content is required"):
        extract_help_request_text(payload)


# --- call_profanity_api ----------------------------------------------------------------
class _FakeResponse:
    def __init__(self, json_body=None, status=200, json_error=False):
        self._json_body = json_body
        self.status_code = status
        self._json_error = json_error

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._json_body


def test_call_profanity_api_requires_a_configured_url(monkeypatch):
    monkeypatch.delenv("PROFANITY_API_URL", raising=False)
    with pytest.raises(ProfanityApiError, match="PROFANITY_API_URL"):
        call_profanity_api("some text")


def test_call_profanity_api_posts_text_and_returns_json(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return _FakeResponse({"severity_score": 2})

    monkeypatch.setattr("requests.post", fake_post)
    result = call_profanity_api("bad text", api_url="https://example.com/profanity")
    assert result == {"severity_score": 2}
    assert captured["url"] == "https://example.com/profanity"
    assert captured["json"] == {"text": "bad text"}


def test_call_profanity_api_sends_api_key_when_configured(monkeypatch):
    monkeypatch.setenv("PROFANITY_API_KEY", "secret-key")
    captured = {}
    monkeypatch.setattr("requests.post", lambda url, **kw: (captured.update(kw), _FakeResponse({}))[1])
    call_profanity_api("text", api_url="https://example.com")
    assert captured["headers"] == {"Authorization": "Bearer secret-key"}


def test_call_profanity_api_wraps_connection_failures(monkeypatch):
    def fake_post(*a, **kw):
        import requests
        raise requests.ConnectionError("boom")

    monkeypatch.setattr("requests.post", fake_post)
    with pytest.raises(ProfanityApiError, match="request failed"):
        call_profanity_api("text", api_url="https://example.com")


def test_call_profanity_api_rejects_http_error_status(monkeypatch):
    # the body is a valid-looking dict even on a 500, as many APIs return an error
    # payload - it's the status check, not the JSON shape, that must catch this.
    monkeypatch.setattr("requests.post", lambda *a, **kw: _FakeResponse({"error": "server error"}, status=500))
    with pytest.raises(ProfanityApiError, match="request failed"):
        call_profanity_api("text", api_url="https://example.com")


def test_call_profanity_api_rejects_invalid_json(monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **kw: _FakeResponse(json_error=True))
    with pytest.raises(ProfanityApiError, match="invalid JSON"):
        call_profanity_api("text", api_url="https://example.com")


def test_call_profanity_api_rejects_non_object_json(monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **kw: _FakeResponse([1, 2, 3]))
    with pytest.raises(ProfanityApiError, match="JSON object"):
        call_profanity_api("text", api_url="https://example.com")


# --- extract_severity_score -------------------------------------------------------------
@pytest.mark.parametrize("key", ["severity_score", "severityScore", "classification_score",
                                  "classificationScore", "score"])
def test_extracts_score_from_any_recognized_key(key):
    assert extract_severity_score({key: 3}) == 3


def test_extracts_score_from_nested_response():
    assert extract_severity_score({"result": {"score": 1}}) == 1
    assert extract_severity_score({"data": {"classification": {"score": 2}}}) == 2


@pytest.mark.parametrize("score", [0, 1, 2, 3])
def test_accepts_every_valid_score(score):
    assert extract_severity_score({"score": score}) == score


def test_accepts_string_digit_score():
    assert extract_severity_score({"score": "2"}) == 2


def test_missing_score_raises():
    with pytest.raises(InvalidSeverityScoreError, match="did not include"):
        extract_severity_score({"unrelated": "field"})


@pytest.mark.parametrize("bad_score", [4, -1, 10, "high", None, 1.5, True, False])
def test_out_of_range_or_non_integer_score_raises(bad_score):
    # True/False are rejected even though bool is a Python int subtype (True == 1)
    # and a non-whole float like 1.5 is rejected rather than silently truncated.
    with pytest.raises(InvalidSeverityScoreError):
        extract_severity_score({"score": bad_score})


def test_whole_valued_float_score_is_accepted():
    assert extract_severity_score({"score": 2.0}) == 2


# --- evaluate_help_request (the actual scoring + routing decision) --------------------
def test_score_zero_is_not_flagged():
    result = evaluate_help_request({"req_desc": "need groceries"},
                                   profanity_client=lambda text: {"score": 0})
    assert result == {"severity_score": 0, "reason": "Good Request", "is_flagged": False}


@pytest.mark.parametrize("score, label", [
    (1, "Foul Language"),
    (2, "Depressive or Suicidal"),
    (3, "Threatening"),
])
def test_nonzero_scores_are_flagged_with_the_right_label(score, label):
    result = evaluate_help_request({"req_desc": "text"}, profanity_client=lambda text: {"score": score})
    assert result == {"severity_score": score, "reason": label, "is_flagged": True}


def test_labels_match_the_sentiment_codes_lookup_table():
    # mirrors the sentiment_codes seed data (saayam-for-all/database wiki)
    assert SENTIMENT_LABELS == {
        0: "Good Request",
        1: "Foul Language",
        2: "Depressive or Suicidal",
        3: "Threatening",
    }


def test_passes_the_extracted_text_to_the_client_not_the_raw_payload():
    seen = {}
    evaluate_help_request({"req_subj": "Urgent", "req_desc": "need help"},
                          profanity_client=lambda text: (seen.update(text=text), {"score": 0})[1])
    assert seen["text"] == "Urgent need help"  # req_subj before req_desc


def test_missing_text_is_rejected_before_calling_the_client():
    called = []
    with pytest.raises(ValueError):
        evaluate_help_request({}, profanity_client=lambda text: called.append(text) or {"score": 0})
    assert called == []  # never reached the API for an empty request


def test_invalid_api_response_propagates_as_invalid_severity_score_error():
    with pytest.raises(InvalidSeverityScoreError):
        evaluate_help_request({"req_desc": "text"}, profanity_client=lambda text: {"score": 9})


def test_default_client_is_the_real_profanity_api(monkeypatch):
    monkeypatch.setenv("PROFANITY_API_URL", "https://example.com")
    monkeypatch.setattr("requests.post", lambda *a, **kw: _FakeResponse({"score": 1}))
    result = evaluate_help_request({"req_desc": "text"})  # no profanity_client passed
    assert result["severity_score"] == 1
