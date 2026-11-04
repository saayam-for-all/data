"""Tests for profanity severity parsing and request routing."""

import pytest
from flask import Flask
from sqlalchemy.exc import SQLAlchemyError

from src.extensions import db
from src.profanity import (
    ProfanityAPIError,
    get_routing_decision,
    parse_profanity_response,
)
from src.profanity_routes import profanity_bp


@pytest.mark.parametrize(
    ("score", "destination"),
    [
        (0, "active_matching"),
        (1, "fraud_requests"),
        (2, "fraud_requests"),
        (3, "fraud_requests"),
    ],
)
def test_routing_decision(score, destination):
    decision = get_routing_decision(score)

    assert decision["severity_score"] == score
    assert decision["destination"] == destination
    assert decision["reason"]


@pytest.mark.parametrize("score", [-1, 4, True, 1.0, "1"])
def test_invalid_routing_score_is_rejected(score):
    with pytest.raises(ValueError):
        get_routing_decision(score)


def test_parse_severity_scores_uses_highest_flagged_score():
    result = parse_profanity_response({
        "severity_scores": [
            {"category": "foul_language", "score": 1, "flagged": True},
            {"category": "threat", "score": 3, "flagged": False},
            {"category": "self_harm", "score": 2, "flagged": True},
        ]
    })

    assert result == {
        "severity_score": 2,
        "is_flagged": True,
        "flagged_categories": [
            {"score": 1, "category": "foul_language"},
            {"score": 2, "category": "self_harm"},
        ],
    }


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"score": True},
        {"score": 4},
        {"severity_scores": []},
        {"severity_scores": [{"score": 1, "category": "abuse"}]},
    ],
)
def test_invalid_classifier_response_is_rejected(payload):
    with pytest.raises(ProfanityAPIError):
        parse_profanity_response(payload)


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(profanity_bp)
    monkeypatch.setattr(db.session, "add", lambda record: None)
    monkeypatch.setattr(db.session, "commit", lambda: None)
    monkeypatch.setattr(db.session, "rollback", lambda: None)
    return app.test_client()


@pytest.mark.parametrize(
    ("score", "destination"),
    [
        (0, "active_matching"),
        (1, "fraud_requests"),
        (2, "fraud_requests"),
        (3, "fraud_requests"),
    ],
)
def test_check_profanity_returns_score_and_destination(
    client, monkeypatch, score, destination
):
    monkeypatch.setattr(
        "src.profanity_routes.call_profanity_api",
        lambda subject, description: {"severity_score": score},
    )

    response = client.post(
        "/api/check_profanity",
        json={
            "user_id": "user-123",
            "subject": "Need assistance",
            "description": "Please help",
        },
    )

    assert response.status_code == 200
    assert response.json["severity_score"] == score
    assert response.json["destination"] == destination


def test_flagged_request_is_saved(client, monkeypatch):
    records = []
    monkeypatch.setattr(
        "src.profanity_routes.call_profanity_api",
        lambda subject, description: {"severity_score": 2},
    )
    monkeypatch.setattr(db.session, "add", records.append)

    response = client.post(
        "/api/check_profanity",
        json={
            "user_id": "user-123",
            "subject": "Need assistance",
            "description": "Please help",
        },
    )

    assert response.status_code == 200
    assert len(records) == 1
    assert records[0].user_id == "user-123"
    assert records[0].reason == "Depressive or Suicidal Content"


def test_api_failure_is_not_routed_as_normal(client, monkeypatch):
    def fail(subject, description):
        raise ProfanityAPIError("offline")

    monkeypatch.setattr("src.profanity_routes.call_profanity_api", fail)
    response = client.post(
        "/api/check_profanity",
        json={
            "user_id": "user-123",
            "subject": "Need assistance",
            "description": "Please help",
        },
    )

    assert response.status_code == 502
    assert response.json["error"]


def test_database_failure_rolls_back_flagged_request(client, monkeypatch):
    rollback_called = []

    def fail_commit():
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(
        "src.profanity_routes.call_profanity_api",
        lambda subject, description: {"severity_score": 1},
    )
    monkeypatch.setattr(db.session, "commit", fail_commit)
    monkeypatch.setattr(db.session, "rollback", lambda: rollback_called.append(True))

    response = client.post(
        "/api/check_profanity",
        json={
            "user_id": "user-123",
            "subject": "Need assistance",
            "description": "Please help",
        },
    )

    assert response.status_code == 500
    assert rollback_called == [True]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"user_id": "user-123", "subject": "subject"},
        {
            "subject": "subject",
            "description": "description",
        },
    ],
)
def test_invalid_request_body_is_rejected(client, payload):
    response = client.post("/api/check_profanity", json=payload)

    assert response.status_code == 400
