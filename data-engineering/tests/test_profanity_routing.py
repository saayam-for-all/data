"""Tests for Profanity API integration and severity routing (issue #422).

The Profanity API is not reachable locally, so every HTTP call is replaced with
a fake ``post`` function, as CONTRIBUTING.md asks for external calls.
"""
import json

import pytest
import requests

from src.utils.profanity_routing import (
    MANUAL_REVIEW_ROUTE,
    ProfanityApiError,
    call_profanity_api,
    evaluate_help_request,
    extract_severity_scores,
    get_profanity_api_url,
    get_severity_scores,
    resolve_severity,
    route_for_score,
)

API_URL = "https://example.test/profanity"


class FakeResponse:
    def __init__(self, payload=None, status_code=200, invalid_json=False):
        self._payload = payload
        self.status_code = status_code
        self._invalid_json = invalid_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._invalid_json:
            raise ValueError("not json")
        return self._payload


def fake_post(payload=None, **kwargs):
    calls = []

    def _post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(payload, **kwargs)

    _post.calls = calls
    return _post


def flags(profanity=False, depressive=False, suicidal=False, threatening=False):
    return {
        "contains_profanity": profanity,
        "contains_depressive_content": depressive,
        "contains_suicidal_content": suicidal,
        "contains_threatening_content": threatening,
    }


def flagged_scores(scores):
    return [s["score"] for s in scores if s["flagged"]]


# ---------- API call ----------

def test_call_sends_subject_and_description():
    post = fake_post(flags())
    call_profanity_api("Need groceries", "Please help", api_url=API_URL, post=post)
    assert post.calls[0]["url"] == API_URL
    assert post.calls[0]["json"] == {"subject": "Need groceries", "description": "Please help"}
    assert post.calls[0]["timeout"] is not None


def test_call_unwraps_lambda_proxy_body():
    proxy = {"statusCode": 200, "body": json.dumps(flags(profanity=True))}
    data = call_profanity_api("s", "d", api_url=API_URL, post=fake_post(proxy))
    assert data["contains_profanity"] is True


@pytest.mark.parametrize(
    "post",
    [
        fake_post({}, status_code=500),
        fake_post(invalid_json=True),
        fake_post(["not", "a", "dict"]),
        fake_post({"statusCode": 200, "body": "not json"}),
    ],
)
def test_call_raises_on_bad_response(post):
    with pytest.raises(ProfanityApiError):
        call_profanity_api("s", "d", api_url=API_URL, post=post)


def test_call_raises_on_network_error():
    def broken_post(*args, **kwargs):
        raise requests.ConnectionError("down")

    with pytest.raises(ProfanityApiError):
        call_profanity_api("s", "d", api_url=API_URL, post=broken_post)


def test_api_url_read_from_env(monkeypatch):
    monkeypatch.setenv("PROFANITY_API_URL", API_URL)
    assert get_profanity_api_url() == API_URL
    monkeypatch.delenv("PROFANITY_API_URL")
    with pytest.raises(ProfanityApiError):
        get_profanity_api_url()


# ---------- Severity scores ----------

def test_scores_cover_0_to_3_with_categories():
    scores = extract_severity_scores(flags())
    assert [(s["score"], s["category"]) for s in scores] == [
        (0, "normal"),
        (1, "profanity"),
        (2, "depressive_suicidal"),
        (3, "threatening"),
    ]


@pytest.mark.parametrize(
    "response,expected",
    [
        (flags(), [0]),
        (flags(profanity=True), [1]),
        (flags(depressive=True), [2]),
        (flags(suicidal=True), [2]),
        (flags(threatening=True), [3]),
        (flags(profanity=True, threatening=True), [1, 3]),
    ],
)
def test_scores_from_flags(response, expected):
    assert flagged_scores(extract_severity_scores(response)) == expected


def test_scores_from_severity_scores_list():
    response = {
        "severity_scores": [
            {"score": 0, "category": "normal", "flagged": False},
            {"score": 1, "category": "profanity", "flagged": True},
            {"score": 2, "category": "depressive_suicidal", "flagged": True},
            {"score": 3, "category": "threatening", "flagged": False},
        ]
    }
    assert flagged_scores(extract_severity_scores(response)) == [1, 2]


@pytest.mark.parametrize("key", ["severity_score", "score"])
@pytest.mark.parametrize("value", [0, 1, 2, 3, "2"])
def test_scores_from_single_score(key, value):
    assert flagged_scores(extract_severity_scores({key: value})) == [int(value)]


@pytest.mark.parametrize("value", [4, -1, "high", True])
def test_invalid_single_score_raises(value):
    with pytest.raises(ProfanityApiError):
        extract_severity_scores({"severity_score": value})


def test_get_severity_scores_calls_api():
    scores = get_severity_scores("s", "d", api_url=API_URL, post=fake_post(flags(depressive=True)))
    assert flagged_scores(scores) == [2]


@pytest.mark.parametrize(
    "response,expected",
    [
        (flags(), 0),
        (flags(profanity=True), 1),
        (flags(profanity=True, suicidal=True), 2),
        (flags(profanity=True, depressive=True, threatening=True), 3),
    ],
)
def test_resolve_severity_uses_highest_flagged(response, expected):
    assert resolve_severity(extract_severity_scores(response)) == expected


# ---------- Routing ----------

@pytest.mark.parametrize(
    "score,route,table,enters_matching",
    [
        (0, "matching_workflow", "request", True),
        (1, "profanity_review", "flagged_help_requests", False),
        (2, "wellbeing_support", "flagged_help_requests", False),
        (3, "blocked_threat", "flagged_help_requests", False),
    ],
)
def test_route_for_score(score, route, table, enters_matching):
    result = route_for_score(score)
    assert result.route == route
    assert result.destination_table == table
    assert result.enters_matching is enters_matching


@pytest.mark.parametrize("score", [-1, 4, None])
def test_route_for_invalid_score_raises(score):
    with pytest.raises(ValueError):
        route_for_score(score)


@pytest.mark.parametrize(
    "response,score,route",
    [
        (flags(), 0, "matching_workflow"),
        (flags(profanity=True), 1, "profanity_review"),
        (flags(suicidal=True), 2, "wellbeing_support"),
        (flags(threatening=True), 3, "blocked_threat"),
    ],
)
def test_evaluate_help_request_routes_by_score(response, score, route):
    result = evaluate_help_request("s", "d", api_url=API_URL, post=fake_post(response))
    assert result["severity_score"] == score
    assert result["route"] == route
    assert result["enters_matching"] is (score == 0)
    assert result["api_error"] is None
    assert len(result["severity_scores"]) == 4


def test_evaluate_help_request_fails_closed_when_api_down():
    result = evaluate_help_request("s", "d", api_url=API_URL, post=fake_post({}, status_code=503))
    assert result["severity_score"] is None
    assert result["route"] == MANUAL_REVIEW_ROUTE.route
    assert result["enters_matching"] is False
    assert result["api_error"]
