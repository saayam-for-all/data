"""Tests for the severity scores returned by the inappropriate content filter (issue #422)."""

import json
import sqlite3
import sys
import types
from unittest.mock import MagicMock

import pytest

# groq and boto3 are only available in the Lambda runtime; stub them so the
# module can be imported locally. Every test replaces them with fakes anyway.
for _name, _attribute in (("groq", "Groq"), ("boto3", "client")):
    try:
        __import__(_name)
    except ImportError:
        sys.modules[_name] = types.SimpleNamespace(**{_attribute: MagicMock()})

from src.inappropriate_content_filter import inappropriate_content_filter as content_filter


def _event(subject, description):
    return {"body": json.dumps({"subject": subject, "description": description})}


def _flagged_scores(severity_scores):
    return [entry["score"] for entry in severity_scores if entry["flagged"]]


@pytest.fixture
def profane_db(tmp_path, monkeypatch):
    """Create a small profane_words.db in the directory the handler reads from."""
    connection = sqlite3.connect(tmp_path / "profane_words.db")
    connection.execute("CREATE TABLE profane_words (words TEXT UNIQUE)")
    connection.executemany(
        "INSERT INTO profane_words (words) VALUES (?)", [("damn",), ("idiot",)]
    )
    connection.commit()
    connection.close()
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def fake_llm(monkeypatch):
    """Return a function that makes the LLM call answer with the given flags."""

    def _configure(**overrides):
        payload = {
            "contains_profanity": False,
            "1. profanity": [],
            "contains_depressive_content": False,
            "contains_suicidal_content": False,
            "2. Depressive/Suicidal Content": [],
            "contains_threatening_content": False,
            "3. Threatening Content": [],
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

    return _configure


@pytest.fixture
def llm_unavailable(monkeypatch):
    """Make the LLM call fail so the handler uses its word-list fallback."""
    monkeypatch.setattr(content_filter.boto3, "client", MagicMock())
    monkeypatch.setattr(
        content_filter, "Groq", MagicMock(side_effect=RuntimeError("model unavailable"))
    )


def test_scores_always_list_all_four_categories_in_order():
    """Every response carries scores 0-3, flagged or not."""
    scores = content_filter.build_severity_scores({})

    assert [(entry["score"], entry["category"]) for entry in scores] == [
        (0, "normal"),
        (1, "profanity"),
        (2, "depressive_suicidal"),
        (3, "threatening"),
    ]
    assert all(set(entry) == {"score", "category", "flagged"} for entry in scores)


def test_normal_request_flags_only_score_zero():
    """With no category detected, only score 0 is flagged."""
    scores = content_filter.build_severity_scores(
        {
            "contains_profanity": False,
            "contains_depressive_content": False,
            "contains_suicidal_content": False,
            "contains_threatening_content": False,
        }
    )

    assert _flagged_scores(scores) == [0]


def test_profanity_flags_score_one():
    """Profanity alone flags score 1 and clears score 0."""
    scores = content_filter.build_severity_scores({"contains_profanity": True})

    assert _flagged_scores(scores) == [1]


@pytest.mark.parametrize("flag", ["contains_depressive_content", "contains_suicidal_content"])
def test_depressive_or_suicidal_flags_score_two(flag):
    """Either the depressive or the suicidal flag is enough for score 2."""
    scores = content_filter.build_severity_scores({flag: True})

    assert _flagged_scores(scores) == [2]


def test_threatening_flags_score_three():
    """Threatening content flags score 3."""
    scores = content_filter.build_severity_scores({"contains_threatening_content": True})

    assert _flagged_scores(scores) == [3]


def test_multiple_categories_are_all_flagged():
    """All matching scores are returned, not only the highest one."""
    scores = content_filter.build_severity_scores(
        {
            "contains_profanity": True,
            "contains_suicidal_content": True,
            "contains_threatening_content": True,
        }
    )

    assert _flagged_scores(scores) == [1, 2, 3]


def test_handler_returns_scores_for_normal_request(profane_db, fake_llm):
    """A clean request comes back with score 0 flagged and the existing keys intact."""
    fake_llm()

    response = content_filter.lambda_handler(_event("Groceries", "I need help buying food"), None)
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert _flagged_scores(body["severity_scores"]) == [0]
    assert "0. This is a normal request" in body
    assert body["contains_profanity"] is False


def test_handler_combines_word_list_and_llm_categories(profane_db, fake_llm):
    """Word-list profanity and LLM-detected threats are both flagged."""
    fake_llm(
        contains_threatening_content=True,
        **{"3. Threatening Content": ["you will regret it"]},
    )

    response = content_filter.lambda_handler(
        _event("Hey", "Move that damn car or you will regret it"), None
    )
    body = json.loads(response["body"])

    assert _flagged_scores(body["severity_scores"]) == [1, 3]
    assert body["1. profanity"] == ["damn"]
    assert body["3. Threatening Content"] == ["you will regret it"]


def test_handler_still_returns_scores_when_llm_fails(profane_db, llm_unavailable):
    """The word-list fallback still reports severity scores."""
    response = content_filter.lambda_handler(_event("Hey", "what an idiot"), None)
    body = json.loads(response["body"])

    assert _flagged_scores(body["severity_scores"]) == [1]
    assert len(body["severity_scores"]) == 4
    assert body["status_code"] == 500
