"""Tests for the content filter Lambda. No AWS or Groq access is needed."""

import json
import sqlite3

import pytest

from src.content_filter import lambda_function as lf

EXPECTED_KEYS = [
    "contains_profanity",
    "1. profanity",
    "contains_depressive_content",
    "contains_suicidal_content",
    "2. Depressive/Suicidal Content",
    "contains_threatening_content",
    "3. Threatening Content",
]


@pytest.fixture
def word_db(tmp_path, monkeypatch):
    """A tiny stand-in profanity DB (mild words only)."""
    path = tmp_path / "profane_words.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE profane_words (words TEXT UNIQUE)")
    conn.executemany(
        "INSERT INTO profane_words VALUES (?)", [("darn",), ("heck",), ("ass",)]
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("PROFANE_WORDS_DB", str(path))
    return path


def fake_llm(text):
    out = {"profanity": [], "depressive": [], "suicidal": [], "threatening": []}
    if "no hope" in text:
        out["depressive"] = ["no hope"]
    if "end it all" in text:
        out["suicidal"] = ["end it all"]
    if "regret it" in text:
        out["threatening"] = ["you will regret it"]
    return out


def broken_llm(text):
    raise RuntimeError("boom")


@pytest.fixture
def working_llm(monkeypatch):
    monkeypatch.setattr(lf, "call_llm", fake_llm)


@pytest.fixture
def failing_llm(monkeypatch):
    monkeypatch.setattr(lf, "call_llm", broken_llm)


def invoke(**fields):
    result = lf.lambda_handler({"body": json.dumps(fields)}, None)
    return result["statusCode"], json.loads(result["body"])


def test_normal_request(word_db, working_llm):
    status, body = invoke(subject="Groceries", description="I need food this week")
    assert status == 200
    assert list(body)[0] == "0. This is a normal request"
    assert list(body)[1:] == EXPECTED_KEYS
    assert not body["contains_profanity"]
    assert not body["contains_depressive_content"]
    assert not body["contains_suicidal_content"]
    assert not body["contains_threatening_content"]


def test_flagged_response_has_exactly_the_agreed_keys(word_db, working_llm):
    status, body = invoke(subject="Help", description="I have no hope")
    assert status == 200
    assert list(body) == EXPECTED_KEYS


def test_profanity_from_word_list(word_db, working_llm):
    status, body = invoke(subject="Help", description="What the heck")
    assert status == 200
    assert body["contains_profanity"] is True
    assert body["1. profanity"] == ["heck"]
    assert "0. This is a normal request" not in body


def test_plural_form_matches_word_list(word_db, working_llm):
    _, body = invoke(subject="Help", description="these darns are bad")
    assert body["1. profanity"] == ["darn"]


def test_assess_is_not_flagged(word_db, working_llm):
    _, body = invoke(subject="Help", description="I need to assess my groceries")
    assert body["contains_profanity"] is False
    assert "0. This is a normal request" in body


def test_llm_profanity_is_merged_with_word_list(word_db, monkeypatch):
    monkeypatch.setattr(
        lf,
        "call_llm",
        lambda text: {"profanity": ["Frak"], "depressive": [], "suicidal": [], "threatening": []},
    )
    _, body = invoke(subject="Help", description="What the heck")
    assert body["1. profanity"] == ["frak", "heck"]


def test_depressive_content(word_db, working_llm):
    _, body = invoke(subject="Help", description="I have no hope")
    assert body["contains_depressive_content"] is True
    assert body["contains_suicidal_content"] is False
    assert body["2. Depressive/Suicidal Content"] == ["no hope"]


def test_suicidal_content(word_db, working_llm):
    _, body = invoke(subject="Help", description="I want to end it all")
    assert body["contains_suicidal_content"] is True
    assert body["contains_depressive_content"] is False
    assert body["2. Depressive/Suicidal Content"] == ["end it all"]


def test_threatening_content(word_db, working_llm):
    _, body = invoke(subject="Pay up", description="Pay me or you will regret it")
    assert body["contains_threatening_content"] is True
    assert body["3. Threatening Content"] == ["you will regret it"]


def test_llm_failure_keeps_keyword_results(word_db, failing_llm):
    status, body = invoke(subject="Help", description="What the heck")
    assert status == 200
    assert body["1. profanity"] == ["heck"]
    assert body["Error"] == "Content analysis model unavailable"
    assert "0. This is a normal request" not in body


def test_llm_failure_never_reports_normal(word_db, failing_llm):
    status, body = invoke(subject="Hello", description="I need groceries")
    assert status == 200
    assert "Error" in body
    assert "0. This is a normal request" not in body


def test_missing_word_list_still_uses_llm(tmp_path, monkeypatch, working_llm):
    monkeypatch.setenv("PROFANE_WORDS_DB", str(tmp_path / "nope.db"))
    status, body = invoke(subject="Help", description="I want to end it all")
    assert status == 200
    assert body["contains_suicidal_content"] is True
    assert body["Error"] == "Profane word database not found"
    assert "0. This is a normal request" not in body


def test_both_sources_unavailable_returns_500(tmp_path, monkeypatch, failing_llm):
    monkeypatch.setenv("PROFANE_WORDS_DB", str(tmp_path / "nope.db"))
    status, body = invoke(subject="Help", description="anything")
    assert status == 500
    assert body == {"error": "Content analysis unavailable"}


def test_malformed_json_returns_400():
    result = lf.lambda_handler({"body": "{bad"}, None)
    assert result["statusCode"] == 400


def test_empty_payload_returns_400():
    assert lf.lambda_handler({"body": json.dumps({})}, None)["statusCode"] == 400
    assert lf.lambda_handler(None, None)["statusCode"] == 400


def test_non_string_fields_return_400():
    status, _ = invoke(subject=5, description="x")
    assert status == 400


def test_direct_invocation_matches_api_gateway(word_db, working_llm):
    fields = {"subject": "Help", "description": "What the heck"}
    wrapped = lf.lambda_handler({"body": json.dumps(fields)}, None)
    assert lf.lambda_handler(fields, None) == wrapped


def test_unexpected_error_returns_500(monkeypatch):
    def explode(text):
        raise RuntimeError("boom")

    monkeypatch.setattr(lf, "analyze_text", explode)
    status, body = invoke(subject="Help", description="x")
    assert status == 500
    assert body == {"error": "Internal server error"}


def test_clean_list_filters_bad_values():
    assert lf.clean_list(["ok", "", 5, None, " hi "]) == ["ok", "hi"]
    assert lf.clean_list("not a list") == []