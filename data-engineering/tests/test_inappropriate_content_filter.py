"""Tests for the severity score and routing added to the inappropriate content
filter (issue #422). The Groq call is patched out, and a small profane_words.db
is built in a temp folder so nothing hits AWS.
"""
import json
import sqlite3
from unittest.mock import patch

import pytest

from src.inappropriate_content_filter import inappropriate_content_filter as icf


def make_event(subject="", description=""):
    return {"body": json.dumps({"subject": subject, "description": description})}


def llm_flags(profanity=False, depressive=False, suicidal=False, threatening=False):
    return {
        "contains_profanity": profanity,
        "1. profanity": [],
        "contains_depressive_content": depressive,
        "contains_suicidal_content": suicidal,
        "2. Depressive/Suicidal Content": [],
        "contains_threatening_content": threatening,
        "3. Threatening Content": [],
    }


@pytest.fixture
def word_db(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "profane_words.db")
    conn.execute("CREATE TABLE profane_words (words TEXT UNIQUE)")
    conn.executemany("INSERT INTO profane_words VALUES (?)", [("damn",), ("crap",)])
    conn.commit()
    conn.close()
    # the Lambda looks for the db in the working directory
    monkeypatch.chdir(tmp_path)


def call(event, flags=None, llm_error=False):
    if llm_error:
        mock = patch.object(icf, "get_llm_flags", side_effect=RuntimeError("groq down"))
    else:
        mock = patch.object(icf, "get_llm_flags", return_value=flags or llm_flags())
    with mock:
        result = icf.lambda_handler(event, None)
    return result["statusCode"], json.loads(result["body"])


@pytest.mark.parametrize("flags, expected", [
    (llm_flags(), 0),
    (llm_flags(profanity=True), 1),
    (llm_flags(depressive=True), 2),
    (llm_flags(suicidal=True), 2),
    (llm_flags(threatening=True), 3),
    # highest category wins when more than one is flagged
    (llm_flags(profanity=True, depressive=True, threatening=True), 3),
])
def test_get_severity_score(flags, expected):
    assert icf.get_severity_score(flags) == expected


def test_route_request():
    assert icf.route_request(0) == "requests"
    for score in (1, 2, 3):
        assert icf.route_request(score) == "fraud_requests"
    with pytest.raises(ValueError):
        icf.route_request(4)


def test_clean_request_goes_to_requests(word_db):
    status, body = call(make_event("Groceries", "Need help carrying groceries home"))
    assert status == 200
    assert body["severity_score"] == 0
    assert body["severity_label"] == "Good Request"
    assert body["route_to"] == "requests"
    assert "0. This is a normal request" in body


def test_word_list_match_is_flagged(word_db):
    status, body = call(make_event("Help", "This damn sink is broken"))
    assert status == 200
    assert body["severity_score"] == 1
    assert body["severity_label"] == "Foul Language"
    assert body["route_to"] == "fraud_requests"
    assert "damn" in body["1. profanity"]


def test_threatening_request_goes_to_fraud_requests(word_db):
    status, body = call(make_event("Hi", "Get out of my way or you will regret it"),
                        flags=llm_flags(threatening=True))
    assert status == 200
    assert body["severity_score"] == 3
    assert body["route_to"] == "fraud_requests"


def test_llm_failure_still_uses_word_list(word_db):
    status, body = call(make_event("Help", "crap, my car broke down"), llm_error=True)
    assert status == 200
    assert body["Error"] == "Invalid API key or issue with the model"
    assert body["severity_score"] == 1
    assert body["route_to"] == "fraud_requests"


def test_only_punctuation_does_not_crash(word_db):
    status, body = call(make_event("!!!", "???"))
    assert status == 200
    assert body["severity_score"] == 0


@pytest.mark.parametrize("event", [
    {"body": "not json"},
    {"body": None},
    make_event("", "   "),
    {"body": json.dumps({"subject": 123, "description": "hi"})},
])
def test_bad_input_returns_400(word_db, event):
    status, body = call(event)
    assert status == 400
    assert "error" in body


def test_missing_db_returns_500(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    status, body = call(make_event("Hi", "Need a ride"))
    assert status == 500
