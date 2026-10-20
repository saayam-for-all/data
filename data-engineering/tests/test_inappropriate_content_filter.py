"""Tests for the severity score and routing added to the inappropriate content
filter (issue #422).

The Groq call (get_llm_flags) is patched out and a small profane_words.db is
built in a temp folder from a hand-picked word list, so nothing touches AWS
or the network. The real list is checked separately by building it with
create_profane_words_db().
"""
import json
import sqlite3
from unittest.mock import patch

import pytest

from src.inappropriate_content_filter import inappropriate_content_filter as icf
from src.inappropriate_content_filter.create_profane_words_db import create_profane_words_db


def make_event(subject="", description=""):
    return {"body": json.dumps({"subject": subject, "description": description})}


def llm_flags(profanity=False, depressive=False, suicidal=False, threatening=False, words=None):
    return {
        "contains_profanity": profanity,
        "1. profanity": words or [],
        "contains_depressive_content": depressive,
        "contains_suicidal_content": suicidal,
        "2. Depressive/Suicidal Content": [],
        "contains_threatening_content": threatening,
        "3. Threatening Content": [],
    }


@pytest.fixture
def word_db(tmp_path, monkeypatch):
    db_path = tmp_path / "profane_words.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE profane_words (words TEXT UNIQUE)")
    conn.executemany("INSERT INTO profane_words VALUES (?)", [("damn",), ("crap",)])
    conn.commit()
    conn.close()
    monkeypatch.setattr(icf, "DB_PATH", str(db_path))
    return db_path


def call(event, flags=None, llm_error=False):
    if llm_error:
        mock = patch.object(icf, "get_llm_flags", side_effect=RuntimeError("groq down"))
    else:
        mock = patch.object(icf, "get_llm_flags", return_value=flags or llm_flags())
    with mock:
        result = icf.lambda_handler(event, None)
    return result["statusCode"], json.loads(result["body"])


# ---- Scoring ----

@pytest.mark.parametrize("flags, expected", [
    (llm_flags(), 0),
    (llm_flags(profanity=True), 1),
    (llm_flags(depressive=True), 2),
    (llm_flags(suicidal=True), 2),
    (llm_flags(threatening=True), 3),
    # highest category wins when more than one is flagged
    (llm_flags(profanity=True, depressive=True), 2),
    (llm_flags(profanity=True, suicidal=True, threatening=True), 3),
])
def test_get_severity_score(flags, expected):
    assert icf.get_severity_score(flags) == expected


def test_severity_labels_cover_all_scores():
    assert icf.SEVERITY_LABELS == {
        0: "Good Request",
        1: "Foul Language",
        2: "Depressive or Suicidal",
        3: "Threatening",
    }


# ---- Routing ----

def test_score_zero_routes_to_active_matching():
    assert icf.route_request(0) == {"route_to": "request", "allow_active_matching": True}


@pytest.mark.parametrize("score", [1, 2, 3])
def test_flagged_scores_route_to_fraud_requests(score):
    assert icf.route_request(score) == {"route_to": "fraud_requests", "allow_active_matching": False}


@pytest.mark.parametrize("score", [-1, 4, True, False, "1", None, 1.5])
def test_invalid_score_is_rejected(score):
    with pytest.raises(ValueError):
        icf.route_request(score)


# ---- Handler, end to end with the model mocked ----

def test_clean_request_goes_to_request_table(word_db):
    status, body = call(make_event("Groceries", "Need help carrying groceries home"))
    assert status == 200
    assert body["severity_score"] == 0
    assert body["severity_label"] == "Good Request"
    assert body["route_to"] == "request"
    assert body["allow_active_matching"] is True
    assert body["llm_checked"] is True
    assert "0. This is a normal request" in body


def test_word_list_match_scores_foul_language(word_db):
    status, body = call(make_event("Help", "This damn sink is broken"))
    assert status == 200
    assert body["severity_score"] == 1
    assert body["severity_label"] == "Foul Language"
    assert body["route_to"] == "fraud_requests"
    assert body["allow_active_matching"] is False
    assert "damn" in body["1. profanity"]
    assert "0. This is a normal request" not in body


def test_plural_word_is_matched(word_db):
    _, body = call(make_event("Help", "Too many damns given"))
    assert body["severity_score"] == 1


def test_llm_profanity_is_merged_with_word_list(word_db):
    _, body = call(make_event("Help", "damn this, something rude"),
                   flags=llm_flags(profanity=True, words=["rude"]))
    assert body["severity_score"] == 1
    assert body["1. profanity"] == ["damn", "rude"]


@pytest.mark.parametrize("flags, score, label", [
    (llm_flags(depressive=True), 2, "Depressive or Suicidal"),
    (llm_flags(suicidal=True), 2, "Depressive or Suicidal"),
    (llm_flags(threatening=True), 3, "Threatening"),
])
def test_model_flags_route_to_fraud_requests(word_db, flags, score, label):
    status, body = call(make_event("Hi", "Some request text"), flags=flags)
    assert status == 200
    assert body["severity_score"] == score
    assert body["severity_label"] == label
    assert body["route_to"] == "fraud_requests"


def test_profanity_and_threat_routes_by_highest(word_db):
    _, body = call(make_event("Hi", "damn, get out of my way or you will regret it"),
                   flags=llm_flags(threatening=True))
    assert body["contains_profanity"] is True
    assert body["severity_score"] == 3


def test_llm_failure_still_uses_word_list(word_db):
    status, body = call(make_event("Help", "crap, my car broke down"), llm_error=True)
    assert status == 200
    assert body["Error"] == "Invalid API key or issue with the model"
    assert body["llm_checked"] is False
    assert body["severity_score"] == 1
    assert body["route_to"] == "fraud_requests"


def test_llm_failure_on_clean_text_is_marked_unchecked(word_db):
    _, body = call(make_event("Help", "Need a ride to the clinic"), llm_error=True)
    assert body["severity_score"] == 0
    assert body["llm_checked"] is False


def test_missing_groq_key_falls_back_to_word_list(word_db, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    result = icf.lambda_handler(make_event("Help", "crap"), None)
    body = json.loads(result["body"])
    assert result["statusCode"] == 200
    assert body["llm_checked"] is False
    assert body["severity_score"] == 1


def test_only_punctuation_does_not_crash(word_db):
    status, body = call(make_event("!!!", "???"))
    assert status == 200
    assert body["severity_score"] == 0


@pytest.mark.parametrize("event", [
    {"body": "not json"},
    {"body": None},
    {"body": json.dumps(["a", "list"])},
    make_event("", "   "),
    {"body": json.dumps({"subject": 123, "description": "hi"})},
])
def test_bad_input_returns_400(word_db, event):
    status, body = call(event)
    assert status == 400
    assert "error" in body


def test_missing_db_returns_500(tmp_path, monkeypatch):
    monkeypatch.setattr(icf, "DB_PATH", str(tmp_path / "missing.db"))
    status, body = call(make_event("Hi", "Need a ride"))
    assert status == 500
    assert body["error"] == "Database file not found"


def test_response_keeps_cors_headers(word_db):
    with patch.object(icf, "get_llm_flags", return_value=llm_flags()):
        result = icf.lambda_handler(make_event("Hi", "Need a ride"), None)
    assert result["headers"]["Access-Control-Allow-Origin"] == "*"
    assert result["headers"]["Content-Type"] == "application/json"


# ---- The shipped word list ----

def test_shipped_word_list_builds_and_scores(tmp_path, monkeypatch):
    db_path = tmp_path / "profane_words.db"
    create_profane_words_db(db_path=str(db_path))
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM profane_words").fetchone()[0]
    blank = conn.execute("SELECT COUNT(*) FROM profane_words WHERE words = ''").fetchone()[0]
    conn.close()
    assert count > 1000
    assert blank == 0

    monkeypatch.setattr(icf, "DB_PATH", str(db_path))
    _, clean = call(make_event("Groceries", "Need help carrying groceries home"), llm_error=True)
    _, foul = call(make_event("Help", "this crap is broken"), llm_error=True)
    assert clean["severity_score"] == 0
    assert foul["severity_score"] == 1
