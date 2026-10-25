"""
Unit tests for the Help Request Content Evaluator.
Validates routing logic, DB interactions, and fallback mechanisms without AWS/Groq dependencies.
"""

import json
import sqlite3
import pytest

from src.content_filter import lambda_function as handler

SCHEMA_KEYS = [
    "contains_profanity",
    "1. profanity",
    "contains_depressive_content",
    "contains_suicidal_content",
    "2. Depressive/Suicidal Content",
    "contains_threatening_content",
    "3. Threatening Content",
    "severity_score"
]


@pytest.fixture
def setup_mock_db(tmp_path, monkeypatch):
    """Provisions a temporary SQLite database populated with test words."""
    db_file = tmp_path / "profane_words.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE profane_words (words TEXT UNIQUE)")
        conn.executemany(
            "INSERT INTO profane_words VALUES (?)", 
            [("dang",), ("shoot",), ("ass",)]
        )
    monkeypatch.setenv("PROFANE_WORDS_DB", str(db_file))
    return db_file


def mock_successful_llm(text: str):
    """Simulates a valid Groq LLM response based on keywords."""
    response = {"profanity": [], "depressive": [], "suicidal": [], "threatening": []}
    if "hopeless" in text:
        response["depressive"] = ["hopeless"]
    if "jump off" in text:
        response["suicidal"] = ["jump off"]
    if "i will find you" in text:
        response["threatening"] = ["i will find you"]
    return response


def mock_failed_llm(text: str):
    """Simulates a total failure of the LLM service."""
    raise ConnectionError("Timeout connecting to LLM provider.")


@pytest.fixture
def patch_llm_success(monkeypatch):
    monkeypatch.setattr(handler, "invoke_llm_classifier", mock_successful_llm)


@pytest.fixture
def patch_llm_failure(monkeypatch):
    monkeypatch.setattr(handler, "invoke_llm_classifier", mock_failed_llm)


def execute_lambda(**kwargs):
    """Helper to structure the event payload and invoke the handler."""
    api_event = {"body": json.dumps(kwargs)}
    response = handler.lambda_handler(api_event, None)
    return response["statusCode"], json.loads(response["body"])


def test_routing_clean_request(setup_mock_db, patch_llm_success):
    status, body = execute_lambda(subject="Volunteer matching", description="I'd like to help.")
    assert status == 200
    assert "0. This is a normal request" in body
    assert body["severity_score"] == 0
    for flag in ["contains_profanity", "contains_depressive_content", "contains_suicidal_content", "contains_threatening_content"]:
        assert not body[flag]


def test_routing_profanity_score_1(setup_mock_db, patch_llm_success):
    status, body = execute_lambda(subject="Frustrated", description="Ah shoot, this is hard.")
    assert status == 200
    assert body["contains_profanity"] is True
    assert body["1. profanity"] == ["shoot"]
    assert body["severity_score"] == 1
    assert "0. This is a normal request" not in body


def test_routing_depressive_score_2(setup_mock_db, patch_llm_success):
    status, body = execute_lambda(subject="Struggling", description="I feel hopeless lately.")
    assert status == 200
    assert body["contains_depressive_content"] is True
    assert body["severity_score"] == 2
    assert body["2. Depressive/Suicidal Content"] == ["hopeless"]


def test_routing_threatening_score_3(setup_mock_db, patch_llm_success):
    status, body = execute_lambda(subject="Angry", description="Approve this or i will find you.")
    assert status == 200
    assert body["contains_threatening_content"] is True
    assert body["severity_score"] == 3


def test_db_stemming_matches_plural(setup_mock_db, patch_llm_success):
    _, body = execute_lambda(subject="Test", description="multiple dangs in here")
    assert body["1. profanity"] == ["dang"]
    assert body["severity_score"] == 1


def test_llm_and_db_results_are_merged(setup_mock_db, monkeypatch):
    monkeypatch.setattr(
        handler, 
        "invoke_llm_classifier", 
        lambda txt: {"profanity": ["Crap"], "depressive": [], "suicidal": [], "threatening": []}
    )
    _, body = execute_lambda(subject="Review", description="shoot this is bad")
    assert sorted(body["1. profanity"]) == ["crap", "shoot"]


def test_fallback_when_llm_fails(setup_mock_db, patch_llm_failure):
    status, body = execute_lambda(subject="Upset", description="Ah shoot")
    assert status == 200
    assert body["contains_profanity"] is True
    assert body["1. profanity"] == ["shoot"]
    assert body["severity_score"] == 1
    assert "Content analysis model unavailable" in body["Error"]


def test_500_when_both_systems_fail(tmp_path, monkeypatch, patch_llm_failure):
    monkeypatch.setenv("PROFANE_WORDS_DB", str(tmp_path / "nonexistent.db"))
    status, body = execute_lambda(subject="Hello", description="Testing failures")
    assert status == 500
    assert body == {"error": "Content analysis unavailable"}


def test_400_on_malformed_json():
    response = handler.lambda_handler({"body": "{invalid_json"}, None)
    assert response["statusCode"] == 400


def test_array_sanitization():
    assert handler.sanitize_llm_array([" valid ", "", None, 123, "text"]) == ["valid", "text"]
    assert handler.sanitize_llm_array("not an array") == []