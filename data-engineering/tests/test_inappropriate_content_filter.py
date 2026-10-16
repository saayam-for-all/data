import json
import sqlite3
import sys
import types
from unittest.mock import MagicMock

import pytest

# groq and boto3 are only needed at call time; stub them if not installed.
sys.modules.setdefault("groq", types.SimpleNamespace(Groq=MagicMock()))
sys.modules.setdefault("boto3", MagicMock())

from src.inappropriate_content_filter import inappropriate_content_filter as icf


def _llm_reply(**overrides):
    reply = {
        "contains_profanity": False,
        "1. profanity": [],
        "contains_depressive_content": False,
        "contains_suicidal_content": False,
        "2. Depressive/Suicidal Content": [],
        "contains_threatening_content": False,
        "3. Threatening Content": [],
    }
    reply.update(overrides)
    return reply


@pytest.fixture
def run_filter(tmp_path, monkeypatch):
    db = sqlite3.connect(tmp_path / "profane_words.db")
    db.execute("CREATE TABLE profane_words (words TEXT UNIQUE)")
    db.execute("INSERT INTO profane_words VALUES ('damn')")
    db.commit()
    db.close()
    monkeypatch.chdir(tmp_path)

    def run(text, llm_reply=None, llm_fails=False):
        client = MagicMock()
        if llm_fails:
            client.chat.completions.create.side_effect = RuntimeError("down")
        else:
            message = MagicMock()
            message.content = json.dumps(llm_reply or _llm_reply())
            client.chat.completions.create.return_value.choices = [MagicMock(message=message)]
        monkeypatch.setattr(icf, "Groq", MagicMock(return_value=client))
        monkeypatch.setattr(icf, "boto3", MagicMock())
        event = {"body": json.dumps({"subject": "Help", "description": text})}
        result = icf.lambda_handler(event, None)
        assert result["statusCode"] == 200
        return json.loads(result["body"])

    return run


@pytest.mark.parametrize(
    "flags, score, categories",
    [
        ({}, 0, ["normal"]),
        ({"contains_profanity": True}, 1, ["profanity"]),
        ({"contains_depressive_content": True}, 2, ["depressive_suicidal"]),
        ({"contains_suicidal_content": True}, 2, ["depressive_suicidal"]),
        ({"contains_threatening_content": True}, 3, ["threatening"]),
        (
            {"contains_profanity": True, "contains_threatening_content": True},
            3,
            ["profanity", "threatening"],
        ),
    ],
)
def test_build_severity(flags, score, categories):
    result_score, result_categories = icf.build_severity(flags)

    assert result_score == score
    assert [c["category"] for c in result_categories] == categories


def test_normal_request_scores_zero(run_filter):
    body = run_filter("I need help with groceries")

    assert body["severity_score"] == 0
    assert body["severity_partial"] is False
    assert "0. This is a normal request" in body


def test_profanity_from_word_list_scores_one(run_filter):
    body = run_filter("this is damn urgent")

    assert body["severity_score"] == 1
    assert body["contains_profanity"] is True


def test_depressive_content_scores_two(run_filter):
    body = run_filter("no hope", _llm_reply(contains_depressive_content=True))

    assert body["severity_score"] == 2


def test_threat_scores_three(run_filter):
    body = run_filter("you will regret it", _llm_reply(contains_threatening_content=True))

    assert body["severity_score"] == 3


def test_profanity_plus_threat_routes_by_highest(run_filter):
    body = run_filter("damn you will pay", _llm_reply(contains_threatening_content=True))

    assert body["severity_score"] == 3
    assert [c["score"] for c in body["severity_categories"]] == [1, 3]


def test_llm_failure_still_scores_word_list_and_is_marked_partial(run_filter):
    body = run_filter("this is damn urgent", llm_fails=True)

    assert body["severity_score"] == 1
    assert body["severity_partial"] is True


def test_llm_failure_on_clean_text_is_partial_zero(run_filter):
    body = run_filter("I need help", llm_fails=True)

    assert body["severity_score"] == 0
    assert body["severity_partial"] is True
