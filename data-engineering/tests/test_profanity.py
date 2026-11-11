"""Tests for the profanity severity scoring/routing module and route (#422).

Two things make these tests special:

1. ``src/app.py`` runs ``db.create_all()`` at *import time* (right after
   ``db.init_app(app)``), targeting the Postgres URL hardcoded in
   ``src/config.py``. To import ``src.app`` here without ever touching a real
   database, we monkeypatch ``db.create_all`` to a no-op *before* importing
   it (see the block directly below the stdlib imports).
2. The Profanity API itself is external and its real contract is not
   documented anywhere in this repo (see ``src/profanity.py``'s module
   docstring). Every network call in this file therefore goes through a fake
   ``requests.post`` (or a mocked ``src.profanity`` function at the route
   layer) - no real HTTP call and no real DB connection is ever made.
"""

import json
from unittest.mock import Mock

import pytest
import requests

# --- Prevent any real DB connection at import time --------------------------
# src/app.py calls db.create_all() at module load, which would otherwise try
# to open a real Postgres connection. No-op it before importing src.app.
from src.extensions import db as _db

_db.create_all = lambda *args, **kwargs: None

import src.app as app_module  # noqa: E402  (must follow the create_all patch)
from src import profanity as profanity_module  # noqa: E402
from src.profanity import (  # noqa: E402
    SEVERITY_LABELS,
    ProfanityAPIError,
    call_profanity_api,
    get_routing_decision,
    parse_profanity_response,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    app_module.app.testing = True
    return app_module.app.test_client()


class FakeResponse:
    """Stand-in for ``requests.Response`` so no real HTTP call is ever made."""

    def __init__(self, json_data=None, status_code=200, raise_for_status_exc=None, json_exc=None):
        self._json_data = json_data
        self.status_code = status_code
        self._raise_for_status_exc = raise_for_status_exc
        self._json_exc = json_exc

    def raise_for_status(self):
        if self._raise_for_status_exc is not None:
            raise self._raise_for_status_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_data


@pytest.fixture(autouse=True)
def _clean_profanity_env(monkeypatch):
    """Keep PROFANITY_API_URL/PROFANITY_API_KEY isolated between tests."""
    monkeypatch.delenv("PROFANITY_API_URL", raising=False)
    monkeypatch.delenv("PROFANITY_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _block_real_network_calls(monkeypatch):
    """Safety net: fail loudly if any test ever reaches a real HTTP call."""

    def _guard(*_args, **_kwargs):
        pytest.fail("A real network call was attempted via requests.post")

    monkeypatch.setattr(profanity_module.requests, "post", _guard)


def _mock_profanity_pipeline(monkeypatch, severity_score, destination, reason, is_flagged, flagged_categories):
    """Mock all three profanity functions as seen from src.app's namespace."""
    monkeypatch.setattr(app_module, "call_profanity_api", lambda subject, description: {"stub": True})
    monkeypatch.setattr(
        app_module,
        "parse_profanity_response",
        lambda payload: {
            "severity_score": severity_score,
            "is_flagged": is_flagged,
            "flagged_categories": flagged_categories,
        },
    )
    monkeypatch.setattr(
        app_module,
        "get_routing_decision",
        lambda score: {
            "severity_score": severity_score,
            "destination": destination,
            "reason": reason,
        },
    )


# ---------------------------------------------------------------------------
# 1. Severity mapping
# ---------------------------------------------------------------------------


def test_severity_labels_mapping():
    assert SEVERITY_LABELS == {
        0: "Good Request",
        1: "Foul Language",
        2: "Depressive or Suicidal Content",
        3: "Threatening Content",
    }


# ---------------------------------------------------------------------------
# 2. get_routing_decision()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected_destination",
    [(0, "active_matching"), (1, "fraud_requests"), (2, "fraud_requests"), (3, "fraud_requests")],
)
def test_get_routing_decision_destinations(score, expected_destination):
    decision = get_routing_decision(score)
    assert decision == {
        "severity_score": score,
        "destination": expected_destination,
        "reason": SEVERITY_LABELS[score],
    }


@pytest.mark.parametrize("bad_score", [-1, 4, True, False, "1", 1.0, None])
def test_get_routing_decision_rejects_invalid_scores(bad_score):
    with pytest.raises(ValueError):
        get_routing_decision(bad_score)


# ---------------------------------------------------------------------------
# 3. parse_profanity_response() - single-score formats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field", ["severity_score", "severityScore", "classification_score", "classificationScore", "score"]
)
def test_parse_single_score_all_field_names(field):
    result = parse_profanity_response({field: 2})
    assert set(result.keys()) == {"severity_score", "is_flagged", "flagged_categories"}
    assert result["severity_score"] == 2
    assert result["is_flagged"] is True
    assert result["flagged_categories"] == [{"score": 2, "category": SEVERITY_LABELS[2]}]


def test_parse_single_score_clean_request_is_not_flagged():
    result = parse_profanity_response({"severity_score": 0})
    assert result == {"severity_score": 0, "is_flagged": False, "flagged_categories": []}


def test_parse_single_score_nested_under_result_key():
    result = parse_profanity_response({"result": {"severity_score": 2}})
    assert result["severity_score"] == 2
    assert result["is_flagged"] is True
    assert result["flagged_categories"] == [{"score": 2, "category": SEVERITY_LABELS[2]}]


def test_parse_multi_category_nested_under_result_key():
    result = parse_profanity_response({
        "result": {
            "severity_scores": [
                {"score": 3, "category": "Threatening Content", "flagged": True},
            ]
        }
    })
    assert result["severity_score"] == 3
    assert result["is_flagged"] is True


def test_parse_result_nesting_is_bounded_to_one_level():
    """Nesting deeper than one "result" level is unrecognized, not unwrapped further."""
    with pytest.raises(ProfanityAPIError):
        parse_profanity_response({"result": {"result": {"severity_score": 2}}})


def test_parse_deeply_nested_result_raises_profanity_error_not_recursion_error():
    """A pathological/adversarial payload must fail cleanly, not crash with RecursionError.

    If parse_profanity_response ever regresses to recursing through "result"
    wrappers without a depth bound, this raises an uncaught RecursionError
    instead of ProfanityAPIError - which would bypass the Flask route's
    error handling (see src/app.py: only ProfanityAPIError/ValueError are
    caught there) and could surface a raw traceback to the client.
    """
    payload = {"not_a_recognizable_field": True}
    for _ in range(3000):
        payload = {"result": payload}

    with pytest.raises(ProfanityAPIError):
        parse_profanity_response(payload)


# ---------------------------------------------------------------------------
# 4. parse_profanity_response() - multi-category format
# ---------------------------------------------------------------------------


def test_parse_multi_category_single_flagged_entry():
    payload = {
        "severity_scores": [
            {"score": 1, "category": "Foul Language", "flagged": True},
            {"score": 2, "category": "Depressive or Suicidal Content", "flagged": False},
        ]
    }
    result = parse_profanity_response(payload)
    assert result["severity_score"] == 1
    assert result["is_flagged"] is True
    assert result["flagged_categories"] == [{"score": 1, "category": "Foul Language"}]


def test_parse_multi_category_multiple_flags_highest_score_wins():
    payload = {
        "severity_scores": [
            {"score": 1, "category": "Foul Language", "flagged": True},
            {"score": 3, "category": "Threatening Content", "flagged": True},
        ]
    }
    result = parse_profanity_response(payload)
    assert result["severity_score"] == 3
    assert result["is_flagged"] is True
    assert result["flagged_categories"] == [
        {"score": 1, "category": "Foul Language"},
        {"score": 3, "category": "Threatening Content"},
    ]


def test_parse_multi_category_nothing_flagged_is_score_zero():
    payload = {
        "severity_scores": [
            {"score": 1, "category": "Foul Language", "flagged": False},
            {"score": 0, "category": "Good Request", "flagged": True},
        ]
    }
    result = parse_profanity_response(payload)
    assert result == {"severity_score": 0, "is_flagged": False, "flagged_categories": []}


# ---------------------------------------------------------------------------
# 5. parse_profanity_response() - invalid inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,payload",
    [
        ("non-dict payload", "not a dict"),
        ("empty dict", {}),
        ("bool score True", {"severity_score": True}),
        ("bool score False", {"severity_score": False}),
        ("score outside 0-3", {"severity_score": 9}),
        ("float score", {"severity_score": 1.5}),
        ("string score", {"severity_score": "2"}),
        ("empty severity_scores list", {"severity_scores": []}),
        ("severity_scores not a list", {"severity_scores": "nope"}),
        ("severity_scores item not a dict", {"severity_scores": ["nope"]}),
        ("missing score", {"severity_scores": [{"category": "Foul Language", "flagged": True}]}),
        ("missing category", {"severity_scores": [{"score": 1, "flagged": True}]}),
        ("empty category", {"severity_scores": [{"score": 1, "category": "   ", "flagged": True}]}),
        ("missing flagged", {"severity_scores": [{"score": 1, "category": "Foul Language"}]}),
        ("flagged not bool", {"severity_scores": [{"score": 1, "category": "Foul Language", "flagged": "yes"}]}),
    ],
)
def test_parse_profanity_response_invalid_inputs_raise(name, payload):
    with pytest.raises(ProfanityAPIError):
        parse_profanity_response(payload)


# ---------------------------------------------------------------------------
# 6. call_profanity_api() - input validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subject,description",
    [
        (None, "valid description"),
        ("", "valid description"),
        ("   ", "valid description"),
        ("valid subject", None),
        ("valid subject", ""),
        ("valid subject", "   "),
    ],
)
def test_call_profanity_api_rejects_blank_subject_or_description(subject, description, monkeypatch):
    monkeypatch.setenv("PROFANITY_API_URL", "https://profanity.example.com/classify")
    with pytest.raises(ValueError):
        call_profanity_api(subject, description)


def test_call_profanity_api_requires_configured_url(monkeypatch):
    monkeypatch.delenv("PROFANITY_API_URL", raising=False)
    with pytest.raises(ProfanityAPIError):
        call_profanity_api("valid subject", "valid description")


# ---------------------------------------------------------------------------
# 7. call_profanity_api() - successful HTTP behavior
# ---------------------------------------------------------------------------


def test_call_profanity_api_sends_expected_request_without_api_key(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return FakeResponse(json_data={"severity_score": 0})

    monkeypatch.setenv("PROFANITY_API_URL", "https://profanity.example.com/classify")
    monkeypatch.delenv("PROFANITY_API_KEY", raising=False)
    monkeypatch.setattr(profanity_module.requests, "post", fake_post)

    result = call_profanity_api("Need groceries", "My family has no food this week")

    assert captured["url"] == "https://profanity.example.com/classify"
    assert captured["timeout"] == profanity_module.DEFAULT_TIMEOUT_SECONDS
    assert captured["json"]["subject"] == "Need groceries"
    assert captured["json"]["description"] == "My family has no food this week"
    assert captured["json"]["content"] == "Need groceries My family has no food this week"
    assert "Authorization" not in captured["headers"]
    assert result == {"severity_score": 0}


def test_call_profanity_api_includes_bearer_token_when_api_key_set(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["headers"] = headers
        return FakeResponse(json_data={"severity_score": 0})

    monkeypatch.setenv("PROFANITY_API_URL", "https://profanity.example.com/classify")
    monkeypatch.setenv("PROFANITY_API_KEY", "super-secret-key")
    monkeypatch.setattr(profanity_module.requests, "post", fake_post)

    call_profanity_api("subject text", "description text")

    assert captured["headers"]["Authorization"] == "Bearer super-secret-key"


# ---------------------------------------------------------------------------
# 8. call_profanity_api() - failure behavior
# ---------------------------------------------------------------------------


def test_call_profanity_api_timeout_raises_profanity_error(monkeypatch):
    def fake_post(*_args, **_kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setenv("PROFANITY_API_URL", "https://profanity.example.com/classify")
    monkeypatch.setattr(profanity_module.requests, "post", fake_post)

    with pytest.raises(ProfanityAPIError):
        call_profanity_api("s", "d")


def test_call_profanity_api_connection_error_raises_profanity_error(monkeypatch):
    def fake_post(*_args, **_kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setenv("PROFANITY_API_URL", "https://profanity.example.com/classify")
    monkeypatch.setattr(profanity_module.requests, "post", fake_post)

    with pytest.raises(ProfanityAPIError):
        call_profanity_api("s", "d")


def test_call_profanity_api_non_2xx_status_raises_profanity_error(monkeypatch):
    def fake_post(*_args, **_kwargs):
        return FakeResponse(status_code=503, raise_for_status_exc=requests.HTTPError("503 Server Error"))

    monkeypatch.setenv("PROFANITY_API_URL", "https://profanity.example.com/classify")
    monkeypatch.setattr(profanity_module.requests, "post", fake_post)

    with pytest.raises(ProfanityAPIError):
        call_profanity_api("s", "d")


def test_call_profanity_api_invalid_json_raises_profanity_error(monkeypatch):
    def fake_post(*_args, **_kwargs):
        return FakeResponse(json_exc=ValueError("Expecting value: line 1 column 1"))

    monkeypatch.setenv("PROFANITY_API_URL", "https://profanity.example.com/classify")
    monkeypatch.setattr(profanity_module.requests, "post", fake_post)

    with pytest.raises(ProfanityAPIError):
        call_profanity_api("s", "d")


def test_call_profanity_api_errors_do_not_leak_sensitive_details(monkeypatch):
    def fake_post(*_args, **_kwargs):
        raise requests.ConnectionError("Failed to establish a new connection to profanity.example.com")

    monkeypatch.setenv("PROFANITY_API_URL", "https://profanity.example.com/classify")
    monkeypatch.setenv("PROFANITY_API_KEY", "super-secret-key")
    monkeypatch.setattr(profanity_module.requests, "post", fake_post)

    with pytest.raises(ProfanityAPIError) as exc_info:
        call_profanity_api("s", "d")

    message = str(exc_info.value)
    assert "super-secret-key" not in message
    assert "profanity.example.com" not in message
    assert "Bearer" not in message


# ---------------------------------------------------------------------------
# 9. Flask route /api/check_profanity - success
# ---------------------------------------------------------------------------


def test_route_score_0_returns_active_matching_without_db_write(client, monkeypatch):
    _mock_profanity_pipeline(monkeypatch, 0, "active_matching", "Good Request", False, [])
    add_mock = Mock()
    commit_mock = Mock()
    monkeypatch.setattr(app_module.db.session, "add", add_mock)
    monkeypatch.setattr(app_module.db.session, "commit", commit_mock)

    resp = client.post(
        "/api/check_profanity",
        json={"user_id": "U1", "subject": "Need food", "description": "My family needs groceries"},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {
        "is_flagged": False,
        "severity_score": 0,
        "reason": "Good Request",
        "destination": "active_matching",
        "flagged_categories": [],
    }
    add_mock.assert_not_called()
    commit_mock.assert_not_called()


@pytest.mark.parametrize("score,reason", [(1, "Foul Language"), (2, "Depressive or Suicidal Content"), (3, "Threatening Content")])
def test_route_flagged_scores_write_exactly_one_fraud_request(client, monkeypatch, score, reason):
    flagged_categories = [{"score": score, "category": reason}]
    _mock_profanity_pipeline(monkeypatch, score, "fraud_requests", reason, True, flagged_categories)
    add_mock = Mock()
    commit_mock = Mock()
    monkeypatch.setattr(app_module.db.session, "add", add_mock)
    monkeypatch.setattr(app_module.db.session, "commit", commit_mock)

    resp = client.post(
        "/api/check_profanity",
        json={"user_id": "U1", "subject": "bad text", "description": "bad text"},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {
        "is_flagged": True,
        "severity_score": score,
        "reason": reason,
        "destination": "fraud_requests",
        "flagged_categories": flagged_categories,
    }
    add_mock.assert_called_once()
    commit_mock.assert_called_once()

    recorded_record = add_mock.call_args[0][0]
    assert recorded_record.user_id == "U1"
    assert recorded_record.reason == reason


# ---------------------------------------------------------------------------
# 10. Route request validation -> 400
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,body,raw_data",
    [
        ("non-dict body", None, "null"),
        ("missing user_id", {"subject": "a", "description": "b"}, None),
        ("bool user_id", {"user_id": True, "subject": "a", "description": "b"}, None),
        ("blank user_id", {"user_id": "   ", "subject": "a", "description": "b"}, None),
        ("missing subject", {"user_id": "U1", "description": "b"}, None),
        ("blank subject", {"user_id": "U1", "subject": "   ", "description": "b"}, None),
        ("missing description", {"user_id": "U1", "subject": "a"}, None),
        ("blank description", {"user_id": "U1", "subject": "a", "description": "   "}, None),
    ],
)
def test_route_rejects_invalid_request_bodies(client, monkeypatch, name, body, raw_data):
    # Guard: if validation ever regresses and lets invalid input through,
    # fail loudly instead of silently reaching the (would-be) profanity call.
    def _should_not_be_called(*_args, **_kwargs):
        raise AssertionError(f"call_profanity_api should not be called for invalid input: {name}")

    monkeypatch.setattr(app_module, "call_profanity_api", _should_not_be_called)

    if raw_data is not None:
        resp = client.post("/api/check_profanity", data=raw_data, content_type="application/json")
    else:
        resp = client.post("/api/check_profanity", json=body)

    assert resp.status_code == 400, name
    assert "error" in resp.get_json()


# ---------------------------------------------------------------------------
# 11. Route upstream (Profanity API) error -> 502
# ---------------------------------------------------------------------------


def test_route_profanity_api_error_returns_502_without_leaking_details(client, monkeypatch):
    def _raise_profanity_error(subject, description):
        raise ProfanityAPIError("PROFANITY_API_URL=https://secret.example.com/api?key=XYZ failed")

    monkeypatch.setattr(app_module, "call_profanity_api", _raise_profanity_error)

    resp = client.post(
        "/api/check_profanity",
        json={"user_id": "U1", "subject": "x", "description": "y"},
    )

    assert resp.status_code == 502
    body = resp.get_json()
    assert body == {"error": "Unable to classify the request at this time"}
    dumped = json.dumps(body)
    assert "secret.example.com" not in dumped
    assert "XYZ" not in dumped


# ---------------------------------------------------------------------------
# 12. Route DB error -> 500 + rollback
# ---------------------------------------------------------------------------


def test_route_db_commit_failure_returns_500_and_rolls_back(client, monkeypatch):
    _mock_profanity_pipeline(
        monkeypatch, 1, "fraud_requests", "Foul Language", True, [{"score": 1, "category": "Foul Language"}]
    )

    add_mock = Mock()
    rollback_mock = Mock()

    def _failing_commit():
        raise RuntimeError(
            "connection to server at host.docker.internal:5432 failed: "
            "password authentication failed for user postgres"
        )

    monkeypatch.setattr(app_module.db.session, "add", add_mock)
    monkeypatch.setattr(app_module.db.session, "commit", _failing_commit)
    monkeypatch.setattr(app_module.db.session, "rollback", rollback_mock)

    resp = client.post(
        "/api/check_profanity",
        json={"user_id": "U1", "subject": "bad", "description": "bad"},
    )

    assert resp.status_code == 500
    body = resp.get_json()
    assert body == {"error": "Unable to record the flagged request"}
    rollback_mock.assert_called_once()

    dumped = json.dumps(body)
    assert "host.docker.internal" not in dumped
    assert "postgres" not in dumped
    assert "5432" not in dumped


# ---------------------------------------------------------------------------
# 13. App integration - route registration / existing routes unaffected
# ---------------------------------------------------------------------------


def test_check_profanity_route_is_registered():
    rules = {rule.rule: rule.methods for rule in app_module.app.url_map.iter_rules()}
    assert "/api/check_profanity" in rules
    assert "POST" in rules["/api/check_profanity"]


def test_existing_routes_still_registered():
    rules = {rule.rule for rule in app_module.app.url_map.iter_rules()}
    assert "/" in rules
    assert "/api/check_fraud" in rules
    assert "/api/translate" in rules
