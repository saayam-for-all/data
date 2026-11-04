"""Tests for severity-based routing of help requests (#422).

The database session and model are fakes: no database is contacted.
"""

import json
import types
import urllib.error
from datetime import datetime

import pytest

from src.profanity_severity import lambda_function as ps
from src.profanity_severity.routing import (
    FLAGGED_REASONS,
    RoutingError,
    route_by_severity,
)

API_URL = "https://api.example.test/requests/v0.0.1/checkProfanity"
FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5)


class FakeModel:
    def __init__(self, user_id, request_datetime, reason):
        self.user_id = user_id
        self.request_datetime = request_datetime
        self.reason = reason
        self.fraud_request_id = None


class FakeSession:
    def __init__(self, commit_error=None, rollback_error=None):
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.commit_error = commit_error
        self.rollback_error = rollback_error

    def add(self, record):
        self.added.append(record)

    def commit(self):
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error
        for index, record in enumerate(self.added, start=1):
            record.fraud_request_id = index

    def rollback(self):
        self.rollbacks += 1
        if self.rollback_error is not None:
            raise self.rollback_error


# ---- route_by_severity ------------------------------------------------------

def test_score_zero_writes_nothing_and_is_not_flagged():
    session = FakeSession()
    result = route_by_severity(0, "user-1", session, FakeModel, now=FIXED_NOW)
    assert result == {
        "is_flagged": False,
        "routing": "none",
        "reason": None,
        "fraud_request_id": None,
        "active_matching_invoked": False,
    }
    assert session.added == [] and session.commits == 0


@pytest.mark.parametrize("score", [1, 2, 3])
def test_flagged_scores_are_recorded_in_fraud_requests(score):
    session = FakeSession()
    result = route_by_severity(score, "user-1", session, FakeModel, now=FIXED_NOW)

    assert result["is_flagged"] is True
    assert result["routing"] == "fraud_requests"
    assert result["reason"] == FLAGGED_REASONS[score]
    assert result["fraud_request_id"] == 1
    assert result["active_matching_invoked"] is False

    record = session.added[0]
    assert (record.user_id, record.request_datetime, record.reason) == (
        "user-1", FIXED_NOW, FLAGGED_REASONS[score]
    )
    assert session.commits == 1 and session.rollbacks == 0


def test_integer_user_id_is_stored_as_string():
    session = FakeSession()
    route_by_severity(2, 42, session, FakeModel, now=FIXED_NOW)
    assert session.added[0].user_id == "42"


def test_request_datetime_defaults_to_now():
    session = FakeSession()
    route_by_severity(1, "u", session, FakeModel)
    assert isinstance(session.added[0].request_datetime, datetime)


@pytest.mark.parametrize("score", [-1, 4, "1", 1.0, None, True])
def test_invalid_score_is_rejected_without_writing(score):
    session = FakeSession()
    with pytest.raises(ValueError):
        route_by_severity(score, "u", session, FakeModel)
    assert session.added == []


@pytest.mark.parametrize("user_id", [None, "", "   ", True, 1.5, ["u"]])
def test_flagged_request_requires_a_valid_user_id(user_id):
    session = FakeSession()
    with pytest.raises(ValueError):
        route_by_severity(3, user_id, session, FakeModel)
    assert session.added == [] and session.commits == 0


def test_database_error_rolls_back_and_raises_routing_error():
    session = FakeSession(commit_error=RuntimeError("connection to db-host:5432 failed"))
    with pytest.raises(RoutingError) as excinfo:
        route_by_severity(3, "u", session, FakeModel)
    assert session.rollbacks == 1
    assert "db-host" not in str(excinfo.value)


def test_failed_rollback_still_raises_routing_error():
    session = FakeSession(
        commit_error=RuntimeError("commit"), rollback_error=RuntimeError("rollback")
    )
    with pytest.raises(RoutingError):
        route_by_severity(2, "u", session, FakeModel)


def test_compatible_with_the_real_fraud_requests_model():
    pytest.importorskip("flask_sqlalchemy")
    from src.models.fraud_requests import FraudRequests

    session = FakeSession()
    route_by_severity(1, "user-9", session, FraudRequests, now=FIXED_NOW)
    record = session.added[0]
    assert isinstance(record, FraudRequests)
    assert record.user_id == "user-9"
    assert record.request_datetime == FIXED_NOW
    assert record.reason == FLAGGED_REASONS[1]


# ---- /api/check_profanity route ---------------------------------------------

@pytest.fixture
def client(monkeypatch):
    pytest.importorskip("flask")
    pytest.importorskip("flask_sqlalchemy")
    from flask import Flask

    from src.profanity_severity import routes

    session = FakeSession()
    monkeypatch.setattr(routes, "db", types.SimpleNamespace(session=session))
    monkeypatch.setattr(routes, "FraudRequests", FakeModel)
    monkeypatch.setenv("PROFANITY_API_URL", API_URL)
    monkeypatch.delenv("PROFANITY_SCORE_FIELD", raising=False)

    app = Flask(__name__)
    app.register_blueprint(routes.profanity_bp)
    test_client = app.test_client()
    test_client.session = session
    test_client.monkeypatch = monkeypatch
    return test_client


class FakeResponse:
    status = 200

    def __init__(self, body):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def upstream(client, body=None, error=None):
    calls = []

    def fake(request, timeout=None):
        calls.append(request)
        if error is not None:
            raise error
        return FakeResponse(body)

    client.monkeypatch.setattr(ps._OPENER, "open", fake)
    return calls


def clean_flags(**overrides):
    body = {
        "contains_profanity": False,
        "contains_depressive_content": False,
        "contains_suicidal_content": False,
        "contains_threatening_content": False,
    }
    body.update(overrides)
    return body


def post(client, **payload):
    payload.setdefault("user_id", "user-1")
    payload.setdefault("subject", "Need help")
    payload.setdefault("description", "Groceries please")
    response = client.post("/api/check_profanity", json=payload)
    return response.status_code, response.get_json()


def test_route_score_zero_is_not_flagged_and_writes_nothing(client):
    upstream(client, clean_flags())
    status, body = post(client)
    assert status == 200
    assert body["severity_score"] == 0
    assert body["classification_status"] == "complete"
    assert body["is_flagged"] is False
    assert body["routing"] == "none"
    assert body["active_matching_invoked"] is False
    assert client.session.added == []


@pytest.mark.parametrize(
    "flags, score",
    [
        ({"contains_profanity": True}, 1),
        ({"contains_depressive_content": True}, 2),
        ({"contains_suicidal_content": True}, 2),
        ({"contains_threatening_content": True}, 3),
        ({"contains_profanity": True, "contains_threatening_content": True}, 3),
    ],
)
def test_route_flagged_scores_write_fraud_request(client, flags, score):
    upstream(client, clean_flags(**flags))
    status, body = post(client)
    assert status == 200
    assert body["severity_score"] == score
    assert body["is_flagged"] is True
    assert body["routing"] == "fraud_requests"
    assert body["reason"] == FLAGGED_REASONS[score]
    assert body["fraud_request_id"] == 1
    assert body["active_matching_invoked"] is False
    assert len(client.session.added) == 1
    assert client.session.added[0].user_id == "user-1"


def test_route_numeric_score_is_supported(client):
    upstream(client, {"severity_score": 2})
    status, body = post(client)
    assert status == 200
    assert body["severity_score"] == 2
    assert body["routing"] == "fraud_requests"


def test_route_upstream_failure_is_503_and_writes_nothing(client):
    upstream(client, error=urllib.error.URLError("down"))
    status, body = post(client)
    assert status == 503
    assert body["severity_score"] is None
    assert body["classification_status"] == "degraded"
    assert body["error_code"] == "profanity_api_unavailable"
    assert "routing" not in body
    assert client.session.added == [] and client.session.commits == 0


def test_route_degraded_upstream_payload_is_503_and_writes_nothing(client):
    upstream(client, {"status_code": 500, "Error": "model", **clean_flags()})
    status, body = post(client)
    assert status == 503
    assert body["severity_score"] is None
    assert client.session.added == []


def test_route_insufficient_response_is_503(client):
    upstream(client, {"contains_profanity": True})
    status, body = post(client)
    assert status == 503
    assert body["error_code"] == "profanity_api_response_invalid"
    assert client.session.added == []


def test_route_database_error_is_500_with_score_but_no_clean_routing(client):
    upstream(client, clean_flags(contains_threatening_content=True))
    client.session.commit_error = RuntimeError("db down")
    status, body = post(client)
    assert status == 500
    assert body["severity_score"] == 3
    assert body["routing"] == "failed"
    assert body["error_code"] == "flagged_request_not_recorded"
    assert body["is_flagged"] is True
    assert client.session.rollbacks == 1
    assert "db down" not in json.dumps(body)


def test_route_database_error_is_not_triggered_for_score_zero(client):
    upstream(client, clean_flags())
    client.session.commit_error = RuntimeError("db down")
    status, body = post(client)
    assert status == 200
    assert body["is_flagged"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {"user_id": None},
        {"user_id": ""},
        {"user_id": True},
        {"subject": None},
        {"description": 5},
        {"subject": " ", "description": ""},
    ],
)
def test_route_invalid_input_is_400_without_calling_upstream(client, payload):
    calls = upstream(client, clean_flags())
    status, body = post(client, **payload)
    assert status == 400
    assert body["severity_score"] is None
    assert body["error_code"] == "invalid_input"
    assert calls == []
    assert client.session.added == []


def test_route_requires_json_object_body(client):
    calls = upstream(client, clean_flags())
    response = client.post("/api/check_profanity", data="not json", content_type="text/plain")
    assert response.status_code == 400
    assert response.get_json()["severity_score"] is None
    assert calls == []


def test_route_forwards_authorization_header(client):
    calls = upstream(client, clean_flags())
    client.post(
        "/api/check_profanity",
        json={"user_id": "u", "subject": "s", "description": "d"},
        headers={"Authorization": "tok"},
    )
    assert calls[0].get_header("Authorization") == "tok"
