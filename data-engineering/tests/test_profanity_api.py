import json
from unittest.mock import Mock

import pytest
import requests

from src.utils.profanity_api import (
    ProfanityAPIError, evaluate_help_request, severity_score,
)


def flags(**overrides):
    return dict.fromkeys((
        "contains_profanity", "contains_depressive_content",
        "contains_suicidal_content", "contains_threatening_content",
    ), False) | overrides


@pytest.mark.parametrize("score", range(4))
def test_explicit_scores(score):
    assert severity_score({"severity_score": score}) == score


@pytest.mark.parametrize("payload,expected", [
    (flags(), 0),
    (flags(contains_profanity=True), 1),
    (flags(contains_depressive_content=True), 2),
    (flags(contains_suicidal_content=True), 2),
    (flags(contains_profanity=True, contains_suicidal_content=True,
           contains_threatening_content=True), 3),
])
def test_legacy_categories(payload, expected):
    assert severity_score(payload) == expected


def test_lambda_response():
    assert severity_score({"statusCode": 200, "body": json.dumps(
        flags(contains_threatening_content=True))}) == 3


@pytest.mark.parametrize("payload", [
    {}, [], {"severity_score": True}, {"severity_score": "0"},
    {"severity_score": 4}, flags(contains_profanity="false"),
    {"statusCode": 500, "body": {"severity_score": 0}},
    {"statusCode": 200, "body": flags() | {"status_code": 500}},
    {"statusCode": 200, "body": "not json"},
    flags() | {"Error": "model failed"},
])
def test_invalid_results_cannot_pass_moderation(payload):
    with pytest.raises(ProfanityAPIError):
        severity_score(payload)


def test_api_request(monkeypatch):
    monkeypatch.setenv("PROFANITY_API_URL", "https://moderation.example/check")
    monkeypatch.setenv("PROFANITY_API_KEY", "test-key")
    post = Mock(return_value=Mock(status_code=200, json=lambda: flags()))
    monkeypatch.setattr("src.utils.profanity_api.requests.post", post)
    assert evaluate_help_request("Food", "Need groceries") == 0
    post.assert_called_once_with(
        "https://moderation.example/check",
        json={"subject": "Food", "description": "Need groceries"},
        headers={"Accept": "application/json", "x-api-key": "test-key"},
        timeout=(3.05, 15), allow_redirects=False,
    )


@pytest.mark.parametrize("status", [302, 400, 500])
def test_http_failure(monkeypatch, status):
    monkeypatch.setenv("PROFANITY_API_URL", "https://moderation.example/check")
    monkeypatch.setattr("src.utils.profanity_api.requests.post", Mock(
        return_value=Mock(status_code=status, json=lambda: flags())))
    with pytest.raises(ProfanityAPIError):
        evaluate_help_request("Food", "Need groceries")


def test_timeout(monkeypatch):
    monkeypatch.setenv("PROFANITY_API_URL", "https://moderation.example/check")
    monkeypatch.setattr("src.utils.profanity_api.requests.post",
                        Mock(side_effect=requests.Timeout))
    with pytest.raises(ProfanityAPIError):
        evaluate_help_request("Food", "Need groceries")


def test_missing_configuration(monkeypatch):
    monkeypatch.delenv("PROFANITY_API_URL", raising=False)
    with pytest.raises(ProfanityAPIError):
        evaluate_help_request("Food", "Need groceries")


@pytest.mark.parametrize("subject,description", [("", "help"), ("help", None)])
def test_invalid_input(subject, description):
    with pytest.raises(ValueError):
        evaluate_help_request(subject, description)


def test_conflicting_score_and_flags():
    with pytest.raises(ProfanityAPIError):
        severity_score({"severity_score": 0,
                        **flags(contains_threatening_content=True)})


@pytest.mark.parametrize("score", range(4))
def test_consistent_score_and_flags(score):
    payload = flags(
        contains_profanity=score == 1,
        contains_suicidal_content=score == 2,
        contains_threatening_content=score == 3,
    )
    assert severity_score({"severity_score": score, **payload}) == score


def test_partial_flags_with_score():
    with pytest.raises(ProfanityAPIError):
        severity_score({"severity_score": 0, "contains_profanity": False})


def test_deeply_nested_envelopes():
    payload = {"severity_score": 0}
    for _ in range(1100):
        payload = {"statusCode": 200, "body": payload}
    with pytest.raises(ProfanityAPIError):
        severity_score(payload)


def test_invalid_json_response(monkeypatch):
    monkeypatch.setenv("PROFANITY_API_URL", "https://moderation.example/check")
    response = Mock(status_code=200)
    response.json.side_effect = ValueError("invalid JSON")
    monkeypatch.setattr("src.utils.profanity_api.requests.post",
                        Mock(return_value=response))
    with pytest.raises(ProfanityAPIError):
        evaluate_help_request("Food", "Need groceries")
