"""Tests for the Help Request content filter's severity scores (#422).

The underlying word-list + LLM moderation call is the already-implemented
Profanity API this issue extends -- these tests stub boto3/groq (neither
is installed locally) and focus on (a) build_severity_scores' scoring
rules and (b) the handler wiring: word-list and LLM results combine
correctly, failures degrade gracefully, and bad input is rejected
cleanly rather than crashing.
"""
import importlib
import json
import os
import sqlite3
import sys
import types
from unittest.mock import MagicMock

import pytest

IMPL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data-engineering", "src", "inappropriate_content_filter",
)

# boto3 and groq are only available in the Lambda runtime; stub them so the
# module can be imported locally. Every test that touches them replaces
# the stub with a MagicMock anyway.
for _name, _attribute in (("boto3", "client"), ("groq", "Groq")):
    if _name not in sys.modules:
        sys.modules[_name] = types.SimpleNamespace(**{_attribute: MagicMock()})


@pytest.fixture
def content_filter(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFANE_WORDS_DB", str(tmp_path / "profane_words.db"))
    monkeypatch.syspath_prepend(IMPL_DIR)
    sys.modules.pop("lambda_function", None)
    module = importlib.import_module("lambda_function")
    return module


@pytest.fixture
def profane_db(tmp_path):
    """A small profane_words.db at the path PROFANE_WORDS_DB points to."""
    connection = sqlite3.connect(tmp_path / "profane_words.db")
    connection.execute("CREATE TABLE profane_words (words TEXT UNIQUE)")
    connection.executemany(
        "INSERT INTO profane_words (words) VALUES (?)", [("damn",), ("idiot",)]
    )
    connection.commit()
    connection.close()


def _fake_llm(content_filter, monkeypatch, **overrides):
    payload = {
        "contains_depressive_content": False,
        "contains_suicidal_content": False,
        "contains_threatening_content": False,
        "depressive_suicidal_terms": [],
        "threatening_terms": [],
    }
    payload.update(overrides)

    ssm = MagicMock()
    ssm.get_parameter.return_value = {"Parameter": {"Value": "test-key"}}
    monkeypatch.setattr(content_filter.boto3, "client", MagicMock(return_value=ssm))

    completion = MagicMock()
    completion.choices[0].message.content = json.dumps(payload)
    client = MagicMock()
    client.chat.completions.create.return_value = completion
    monkeypatch.setattr(content_filter, "Groq", MagicMock(return_value=client))


def _llm_unavailable(content_filter, monkeypatch):
    monkeypatch.setattr(content_filter.boto3, "client", MagicMock())
    monkeypatch.setattr(
        content_filter, "Groq", MagicMock(side_effect=RuntimeError("model unavailable"))
    )


def _event(subject=None, description=None):
    return {"body": json.dumps({"subject": subject, "description": description})}


def _flagged(severity_scores):
    return [entry["score"] for entry in severity_scores if entry["flagged"]]


# --- build_severity_scores ---------------------------------------------

def test_all_four_scores_always_present_in_order(content_filter):
    scores = content_filter.build_severity_scores({})
    assert [(e["score"], e["category"]) for e in scores] == [
        (0, "normal"),
        (1, "profanity"),
        (2, "depressive_suicidal"),
        (3, "threatening"),
    ]
    assert all(set(e) == {"score", "category", "flagged"} for e in scores)


def test_no_flags_means_only_score_zero(content_filter):
    assert _flagged(content_filter.build_severity_scores({})) == [0]


def test_profanity_flag_means_score_one(content_filter):
    flags = {"contains_profanity": True}
    assert _flagged(content_filter.build_severity_scores(flags)) == [1]


@pytest.mark.parametrize("flag", ["contains_depressive_content", "contains_suicidal_content"])
def test_depressive_or_suicidal_means_score_two(content_filter, flag):
    assert _flagged(content_filter.build_severity_scores({flag: True})) == [2]


def test_threatening_flag_means_score_three(content_filter):
    flags = {"contains_threatening_content": True}
    assert _flagged(content_filter.build_severity_scores(flags)) == [3]


def test_every_matching_category_is_flagged_not_only_the_highest(content_filter):
    flags = {
        "contains_profanity": True,
        "contains_suicidal_content": True,
        "contains_threatening_content": True,
    }
    assert _flagged(content_filter.build_severity_scores(flags)) == [1, 2, 3]


# --- lambda_handler ------------------------------------------------------

def test_normal_request_returns_score_zero_only(content_filter, monkeypatch, profane_db):
    _fake_llm(content_filter, monkeypatch)
    response = content_filter.lambda_handler(
        _event("Groceries", "I need help buying food"), None
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert _flagged(body["severity_scores"]) == [0]
    assert body["contains_profanity"] is False


def test_word_list_and_llm_results_combine(content_filter, monkeypatch, profane_db):
    _fake_llm(content_filter, monkeypatch, contains_threatening_content=True, threatening_terms=["regret it"])
    response = content_filter.lambda_handler(
        _event("Hey", "Move that damn car or you will regret it"), None
    )
    body = json.loads(response["body"])

    assert _flagged(body["severity_scores"]) == [1, 3]
    assert body["profanity_terms"] == ["damn"]
    assert body["threatening_terms"] == ["regret it"]


def test_llm_failure_degrades_to_word_list_only(content_filter, monkeypatch, profane_db):
    _llm_unavailable(content_filter, monkeypatch)
    response = content_filter.lambda_handler(_event("Hey", "what an idiot"), None)
    body = json.loads(response["body"])

    assert response["statusCode"] == 200  # degraded, not a hard failure
    assert _flagged(body["severity_scores"]) == [1]
    assert "llm_error" in body


def test_missing_subject_and_description_is_a_400(content_filter, monkeypatch, profane_db):
    _fake_llm(content_filter, monkeypatch)
    response = content_filter.lambda_handler(_event(), None)
    assert response["statusCode"] == 400


def test_blank_subject_and_description_is_a_400(content_filter, monkeypatch, profane_db):
    _fake_llm(content_filter, monkeypatch)
    response = content_filter.lambda_handler(_event("  ", ""), None)
    assert response["statusCode"] == 400


def test_missing_word_list_database_is_a_500(content_filter, monkeypatch):
    # No profane_db fixture here -- PROFANE_WORDS_DB points nowhere.
    _fake_llm(content_filter, monkeypatch)
    response = content_filter.lambda_handler(_event("Hey", "hello there"), None)
    assert response["statusCode"] == 500


def test_api_gateway_proxy_event_with_string_body(content_filter, monkeypatch, profane_db):
    _fake_llm(content_filter, monkeypatch)
    response = content_filter.lambda_handler(
        {"body": json.dumps({"subject": "Hi", "description": "hello there"})}, None
    )
    assert response["statusCode"] == 200


def test_malformed_body_is_a_400(content_filter):
    response = content_filter.lambda_handler({"body": "not json"}, None)
    assert response["statusCode"] == 400


def test_response_body_is_a_json_string(content_filter, monkeypatch, profane_db):
    _fake_llm(content_filter, monkeypatch)
    response = content_filter.lambda_handler(_event("Hi", "hello there"), None)
    assert isinstance(response["body"], str)


def test_module_imports_without_groq_or_boto3(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFANE_WORDS_DB", str(tmp_path / "profane_words.db"))
    monkeypatch.syspath_prepend(IMPL_DIR)
    sys.modules.pop("lambda_function", None)
    monkeypatch.setitem(sys.modules, "groq", None)
    monkeypatch.setitem(sys.modules, "boto3", None)

    module = importlib.import_module("lambda_function")
    assert module.Groq is None
    assert module.boto3 is None
