"""Tests for profanity severity scoring and routing (issue #422).

The Profanity API and the database are mocked; no live API, AWS or
database calls are made. LIVE_SHAPED_RESPONSE mirrors the response of the
inappropriate content filter and should be replaced with a captured sample
from the deployed API once one is available.
"""
import json

import pytest
import requests
from flask import Flask

from src.profanity_severity import client, routes, routing, scoring
from src.profanity_severity.routes import profanity_bp
from src.profanity_severity.scoring import ScoringError, extract_severity

# Shape returned by the content filter (flags + word lists).
LIVE_SHAPED_RESPONSE = {
    "contains_profanity": False,
    "1. profanity": [],
    "contains_depressive_content": False,
    "contains_suicidal_content": False,
    "2. Depressive/Suicidal Content": [],
    "contains_threatening_content": False,
    "3. Threatening Content": [],
}


def flags(**overrides):
    """A valid response with the given flags switched on."""
    return {**LIVE_SHAPED_RESPONSE, **overrides}


# ---------------------------------------------------------------- scoring


def test_clean_response_scores_zero():
    result = extract_severity(flags())
    assert result.score == 0
    assert result.categories == ()


@pytest.mark.parametrize(
    "flag, score, category",
    [
        ("contains_profanity", 1, "profanity"),
        ("contains_depressive_content", 2, "depressive_suicidal"),
        ("contains_suicidal_content", 2, "depressive_suicidal"),
        ("contains_threatening_content", 3, "threatening"),
    ],
)
def test_each_flag_maps_to_its_score(flag, score, category):
    result = extract_severity(flags(**{flag: True}))
    assert result.score == score
    assert result.categories == (category,)


def test_multiple_categories_use_highest_score_and_list_all():
    result = extract_severity(
        flags(contains_profanity=True, contains_threatening_content=True)
    )
    assert result.score == 3
    assert result.categories == ("profanity", "threatening")


def test_lambda_proxy_envelope_is_unwrapped():
    envelope = {"statusCode": 200, "body": json.dumps(flags(contains_profanity=True))}
    assert extract_severity(envelope).score == 1


def test_lambda_proxy_envelope_with_non_2xx_is_rejected():
    envelope = {"statusCode": 500, "body": json.dumps(flags())}
    with pytest.raises(ScoringError) as exc:
        extract_severity(envelope)
    assert exc.value.error_code == "upstream_error"


@pytest.mark.parametrize(
    "payload, code",
    [
        (None, "invalid_response"),
        ([], "invalid_response"),
        ("clean", "invalid_response"),
        ({}, "invalid_response"),
        # The filter's own failure shape: HTTP 200, "Error" field, zeroed flags.
        (
            flags(status_code=500, Error="Invalid API key or issue with the model"),
            "upstream_error",
        ),
        (flags(error="boom"), "upstream_error"),
        (flags(status_code=500), "upstream_error"),
        (flags(status_code="200"), "upstream_error"),
        ({"statusCode": 200, "body": "not json"}, "invalid_response"),
    ],
)
def test_bad_payloads_are_rejected(payload, code):
    with pytest.raises(ScoringError) as exc:
        extract_severity(payload)
    assert exc.value.error_code == code


@pytest.mark.parametrize("missing", scoring.REQUIRED_FLAGS)
def test_missing_flag_is_an_error_not_false(missing):
    payload = flags()
    del payload[missing]
    with pytest.raises(ScoringError) as exc:
        extract_severity(payload)
    assert exc.value.error_code == "invalid_response"


@pytest.mark.parametrize("bad", ["true", 1, 0, None, [], {}])
def test_non_boolean_flag_is_rejected(bad):
    with pytest.raises(ScoringError):
        extract_severity(flags(contains_threatening_content=bad))


# ---------------------------------------------------------------- routing


def test_routing_table_covers_every_score():
    assert set(routing.ROUTING) == {0, 1, 2, 3}
    assert routing.route_for(0) is routing.Destination.ACTIVE_MATCHING
    for score in (1, 2, 3):
        assert routing.route_for(score) is routing.Destination.FRAUD_REQUESTS


def test_reason_names_score_and_categories_and_fits_column():
    result = scoring.SeverityResult(3, ("profanity", "threatening"))
    reason = routing.build_reason(result)
    assert reason == "profanity_severity_3:profanity,threatening"
    assert len(reason) <= 255


# ----------------------------------------------------------------- client


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=False):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("bad json")
        return self._payload


@pytest.fixture
def api_env(monkeypatch):
    monkeypatch.setenv("PROFANITY_API_URL", "https://profanity.example/check")
    monkeypatch.delenv("PROFANITY_API_KEY", raising=False)
    monkeypatch.delenv("PROFANITY_API_TIMEOUT", raising=False)


def test_client_requires_https_url(monkeypatch):
    for url in ("", "http://insecure.example"):
        monkeypatch.setenv("PROFANITY_API_URL", url)
        with pytest.raises(ScoringError) as exc:
            client.call_profanity_api("s", "d")
        assert exc.value.error_code == "not_configured"


def test_client_posts_text_without_following_redirects(api_env, monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return FakeResponse(payload=flags())

    monkeypatch.setattr(client.requests, "post", fake_post)
    monkeypatch.setenv("PROFANITY_API_KEY", "k")
    monkeypatch.setenv("PROFANITY_API_TIMEOUT", "3")

    assert client.call_profanity_api("subj", "desc") == flags()
    assert seen["url"] == "https://profanity.example/check"
    assert seen["json"] == {"subject": "subj", "description": "desc"}
    assert seen["allow_redirects"] is False
    assert seen["timeout"] == 3.0
    assert seen["headers"]["x-api-key"] == "k"
    assert "Authorization" not in seen["headers"]


@pytest.mark.parametrize(
    "outcome, code",
    [
        (requests.Timeout(), "upstream_timeout"),
        (requests.ConnectionError(), "upstream_unreachable"),
        (FakeResponse(status_code=500), "upstream_error"),
        (FakeResponse(status_code=302), "upstream_error"),
        (FakeResponse(json_error=True), "invalid_response"),
    ],
)
def test_client_failures_become_scoring_errors(api_env, monkeypatch, outcome, code):
    def fake_post(url, **kwargs):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(client.requests, "post", fake_post)
    with pytest.raises(ScoringError) as exc:
        client.call_profanity_api("s", "d")
    assert exc.value.error_code == code


# ------------------------------------------------------------------ route


@pytest.fixture
def http(monkeypatch):
    """Test client with the API and the database both mocked."""
    app = Flask(__name__)
    app.register_blueprint(profanity_bp)

    state = {"payload": flags(), "api_error": None, "db_error": None, "rows": [], "calls": 0}

    def fake_api(subject, description):
        state["calls"] += 1
        if state["api_error"]:
            raise state["api_error"]
        return state["payload"]

    def fake_record(user_id, reason):
        if state["db_error"]:
            raise state["db_error"]
        state["rows"].append((user_id, reason))

    monkeypatch.setattr(routes.client, "call_profanity_api", fake_api)
    monkeypatch.setattr(routes.store, "record_flagged_request", fake_record)
    return app.test_client(), state


GOOD = {"user_id": "u1", "subject": "Need help", "description": "Groceries please"}


def test_score_zero_passes_and_writes_nothing(http):
    test_client, state = http
    resp = test_client.post("/api/check_profanity", json=GOOD)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["severity_score"] == 0
    assert body["route"] == "active_matching"
    assert body["proceed_to_matching"] is True
    assert state["rows"] == []


@pytest.mark.parametrize(
    "flag, score",
    [
        ("contains_profanity", 1),
        ("contains_suicidal_content", 2),
        ("contains_threatening_content", 3),
    ],
)
def test_flagged_requests_are_recorded_and_held(http, flag, score):
    test_client, state = http
    state["payload"] = flags(**{flag: True})
    resp = test_client.post("/api/check_profanity", json=GOOD)
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["severity_score"] == score
    assert body["route"] == "fraud_requests"
    assert body["proceed_to_matching"] is False
    assert body["recorded"] is True
    assert state["rows"] == [("u1", f"profanity_severity_{score}:{body['flagged_categories'][0]}")]


def test_unscorable_response_is_503_and_never_proceeds(http):
    test_client, state = http
    # The filter's degraded payload: HTTP 200 body with an Error and zeroed flags.
    state["payload"] = flags(status_code=500, Error="Invalid API key")
    resp = test_client.post("/api/check_profanity", json=GOOD)
    body = resp.get_json()
    assert resp.status_code == 503
    assert body["severity_score"] is None
    assert body["proceed_to_matching"] is False
    assert body["error_code"] == "upstream_error"
    assert state["rows"] == []


def test_upstream_failure_is_503(http):
    test_client, state = http
    state["api_error"] = ScoringError("upstream_timeout")
    resp = test_client.post("/api/check_profanity", json=GOOD)
    assert resp.status_code == 503
    assert resp.get_json()["severity_score"] is None
    assert resp.get_json()["proceed_to_matching"] is False


def test_database_failure_is_500_but_keeps_the_score(http):
    test_client, state = http
    state["payload"] = flags(contains_threatening_content=True)
    state["db_error"] = RuntimeError("db down")
    resp = test_client.post("/api/check_profanity", json=GOOD)
    body = resp.get_json()
    assert resp.status_code == 500
    assert body["severity_score"] == 3
    assert body["recorded"] is False
    assert body["proceed_to_matching"] is False
    assert body["error_code"] == "db_error"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"subject": "s", "description": "d"},
        {"user_id": "", "subject": "s"},
        {"user_id": 5, "subject": "s"},
        {"user_id": "u1", "subject": 5, "description": "d"},
        {"user_id": "u1", "subject": "  ", "description": ""},
    ],
)
def test_invalid_input_is_400_and_skips_the_api(http, payload):
    test_client, state = http
    resp = test_client.post("/api/check_profanity", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["proceed_to_matching"] is False
    assert state["calls"] == 0
