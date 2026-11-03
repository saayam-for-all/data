"""Contract and transport tests for complete and failed API responses."""

import json
from unittest.mock import Mock

import pytest
import requests

from profanity_routing.client import ProfanityClient, parse_classification
from profanity_routing.domain import HelpRequest, WorkflowError
from profanity_routing.local_tools import legacy_flags


@pytest.mark.parametrize("score", range(4))
def test_explicit_and_legacy_contracts(score):
    """Both supported primary representations give the same severity."""
    flags = legacy_flags((score,))
    assert parse_classification({"severity_score": score}).score == score
    assert parse_classification(flags).score == score
    assert parse_classification({"statusCode": 200, "body": json.dumps(flags)}).score == score
    assert parse_classification({"statusCode": 200, "body": flags}).score == score


def test_mixed_categories_and_suicidal_flag():
    """Multiple findings preserve all categories and use the highest score."""
    result = parse_classification(legacy_flags((1, 2, 3)))
    assert result.score == 3
    assert result.categories == ("profanity", "depressive_or_suicidal", "threatening")
    assert parse_classification({**legacy_flags(()), "contains_suicidal_content": True}).score == 2


@pytest.mark.parametrize("score", range(4))
def test_severity_list_contract(score):
    """Support the fully enumerated numeric response without dropping flags."""
    payload = {"severity_scores": [{"score": n, "flagged": n == score} for n in range(4)]}
    assert parse_classification(payload).score == score


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"score": 0},
        {"severity_score": True},
        {"severity_score": 1.0},
        {"severity_score": "0"},
        {"severity_score": None},
        {"severity_score": -1},
        {"severity_score": 4},
        {"contains_profanity": False},
        {**legacy_flags(()), "contains_suicidal_content": "false"},
        {**legacy_flags((3,)), "severity_score": 0},
        {"severity_score": 0, "classification_status": "degraded"},
        {"severity_score": 0, "severity_partial": True},
        {"severity_score": 0, "severity_partial": "false"},
        {"severity_score": 0, "llm_error": "failed"},
        {"severity_score": 0, "status_code": 500},
        {"severity_score": 0, "statusCode": "200"},
        {"statusCode": 200, "body": "not JSON"},
        {"statusCode": 200, "body": "null"},
        {"statusCode": 503, "body": {"severity_score": 0}},
        {
            "statusCode": 200,
            "body": {**legacy_flags(()), "Error": "model failed", "status_code": 500},
        },
        {"body": {"severity_score": 0}},
        {"statusCode": 200, "severity_score": 3, "body": {"severity_score": 0}},
        {"severity_scores": []},
        {"severity_scores": [{"score": 0, "flagged": True}] * 4},
        {"severity_scores": [{"score": n, "flagged": True} for n in range(4)]},
        {"severity_scores": [{"score": n, "flagged": False} for n in range(4)]},
    ],
)
def test_reject_invalid_or_unverified_scores(payload):
    """An incomplete or failed check must never be interpreted as clean."""
    with pytest.raises(WorkflowError, match="complete score"):
        parse_classification(payload)


def test_conflicting_category_lists_are_rejected():
    """Agreement on the highest score alone cannot hide conflicting findings."""
    payload = {
        **legacy_flags((1, 3)),
        "severity_scores": [{"score": n, "flagged": n == 3} for n in range(4)],
    }
    with pytest.raises(WorkflowError):
        parse_classification(payload)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://example.com/api",
        "file:///tmp/api",
        "https://user:secret@example.com",
        "https://example.com:bad",
        "https://example.com/#fragment",
    ],
)
def test_reject_unsafe_or_invalid_urls(url):
    """Configuration must use HTTPS, without URL credentials or fragments."""
    with pytest.raises(ValueError):
        ProfanityClient(url)


@pytest.mark.parametrize("timeout", [0, -1, 61, float("nan"), float("inf")])
def test_reject_unbounded_timeout(timeout):
    """The client always has a finite deadline."""
    with pytest.raises(ValueError):
        ProfanityClient("https://example.com", timeout=timeout)


def test_loopback_http_requires_explicit_opt_in():
    """HTTP allowance is limited to explicitly configured local fixtures."""
    with pytest.raises(ValueError):
        ProfanityClient("http://127.0.0.1:5011")
    with pytest.raises(ValueError):
        ProfanityClient("http://example.com", allow_local_http=True)
    ProfanityClient("http://127.0.0.1:5011", allow_local_http=True)


@pytest.mark.parametrize("status", [301, 302, 401, 429, 500, 503])
def test_http_errors_and_redirects_are_rejected(monkeypatch, submission, status):
    """No redirect or upstream error can become an approval."""
    response = Mock(status_code=status)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    post = Mock(return_value=response)
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(WorkflowError):
        ProfanityClient("https://example.com", api_key="local-test-key").classify(
            HelpRequest.from_payload(submission)
        )
    assert post.call_args.kwargs["allow_redirects"] is False
    response.json.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        requests.Timeout("private upstream detail"),
        requests.ConnectionError("private upstream detail"),
        ValueError("private upstream detail"),
    ],
)
def test_transport_failures_are_sanitized(monkeypatch, submission, failure):
    """Timeouts, connection failures and bad JSON have a stable public error."""
    monkeypatch.setattr(requests, "post", Mock(side_effect=failure))
    with pytest.raises(WorkflowError) as error:
        ProfanityClient("https://example.com").classify(HelpRequest.from_payload(submission))
    assert "private" not in str(error.value)


def test_request_contract_and_api_key(monkeypatch, submission):
    """Send only the existing API's two content fields and configured API key."""
    response = Mock(status_code=200)
    response.json.return_value = {"severity_score": 0}
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    post = Mock(return_value=response)
    monkeypatch.setattr(requests, "post", post)
    client = ProfanityClient("https://example.com/api", api_key="test-key", timeout=3)
    assert client.classify(HelpRequest.from_payload(submission)).score == 0
    assert post.call_args.kwargs == {
        "json": {"subject": submission["subject"], "description": submission["description"]},
        "headers": {"Accept": "application/json", "x-api-key": "test-key"},
        "timeout": 3,
        "allow_redirects": False,
    }
