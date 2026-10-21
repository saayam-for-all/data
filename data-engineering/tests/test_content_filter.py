"""Tests for the Content Filter Lambda (issue #422).

These stub out the OpenAI client and the better-profanity package so the
tests run without network access or a real OPENAI_API_KEY -- matching
CONTRIBUTING.md's "develop and test locally with mock data" guidance.
Only the pure logic (profanity word-matching, JSON parsing/validation,
fail-safe behavior, and the Lambda handler's request parsing) is under
test here; the actual OpenAI call itself is not exercised end-to-end.
"""

import json
import sys
import types

import pytest


@pytest.fixture(autouse=True)
def stub_external_dependencies(monkeypatch):
    """Stub openai, dotenv, and better_profanity before each test imports
    the module under test, so no real package/network/API key is needed.
    """
    fake_openai = types.ModuleType("openai")

    class FakeOpenAI:
        def __init__(self, api_key=None):
            pass

    fake_openai.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    fake_dotenv = types.ModuleType("dotenv")
    fake_dotenv.load_dotenv = lambda *a, **kw: None
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)

    fake_bp = types.ModuleType("better_profanity")

    class FakeProfanity:
        _words = {"damn", "shit", "shitty", "hell", "ass"}

        def load_censor_words(self):
            pass

        def contains_profanity(self, word):
            return word.lower() in self._words

    fake_bp.Profanity = FakeProfanity
    monkeypatch.setitem(sys.modules, "better_profanity", fake_bp)

    # Re-import fresh each test so module-level state (e.g. `client`) is reset
    sys.modules.pop("src.content_filter.lambda_function", None)
    from src.content_filter import lambda_function  # noqa: F401


@pytest.fixture
def module():
    from src.content_filter import lambda_function
    return lambda_function


class FakeRaisingClient:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("simulated API outage")


def test_check_profanity_clean_text(module):
    contains, words = module.check_profanity("I need help with groceries this week")
    assert contains is False
    assert words == []


def test_check_profanity_flags_and_deduplicates(module):
    contains, words = module.check_profanity(
        "This is such a damn damn shitty situation, hell"
    )
    assert contains is True
    assert words == ["damn", "shitty", "hell"]


def test_parse_llm_classification_well_formed(module):
    raw = json.dumps({
        "contains_depressive_content": True,
        "contains_suicidal_content": False,
        "2. Depressive/Suicidal Content": ["I feel so hopeless"],
        "contains_threatening_content": False,
        "3. Threatening Content": [],
    })
    result = module.parse_llm_classification(raw)
    assert result["contains_depressive_content"] is True
    assert result["contains_suicidal_content"] is False
    assert result["2. Depressive/Suicidal Content"] == ["I feel so hopeless"]
    assert result["contains_threatening_content"] is False
    assert result["3. Threatening Content"] == []


def test_parse_llm_classification_missing_fields_fail_safe(module):
    result = module.parse_llm_classification(json.dumps({}))
    # Missing fields default to True (held for review), not False
    assert result["contains_depressive_content"] is True
    assert result["contains_suicidal_content"] is True
    assert result["contains_threatening_content"] is True
    assert result["2. Depressive/Suicidal Content"] == []
    assert result["3. Threatening Content"] == []


def test_parse_llm_classification_malformed_json_raises(module):
    with pytest.raises(json.JSONDecodeError):
        module.parse_llm_classification("not json at all")


def test_lambda_handler_malformed_json_body(module):
    response = module.lambda_handler({"body": "{not valid json"}, None)
    assert response["statusCode"] == 400
    assert "error" in json.loads(response["body"])


def test_lambda_handler_empty_body_rejected(module):
    response = module.lambda_handler({"body": json.dumps({})}, None)
    assert response["statusCode"] == 400
    assert "error" in json.loads(response["body"])


def test_classify_content_llm_failure_fails_safe_but_profanity_still_local(module):
    module.client = FakeRaisingClient()
    result = module.classify_content("This is damn frustrating", "I lost my job")

    # Profanity check doesn't depend on the LLM, so it still works
    assert result["contains_profanity"] is True
    assert result["1. profanity"] == ["damn"]

    # LLM-dependent flags fail-safe to True (held for review) on error
    assert result["contains_depressive_content"] is True
    assert result["contains_suicidal_content"] is True
    assert result["contains_threatening_content"] is True
    assert "review_reason" in result


def test_lambda_handler_returns_full_schema_on_success(module):
    module.client = FakeRaisingClient()  # LLM fails -> fail-safe, still valid shape
    response = module.lambda_handler(
        {"body": json.dumps({"subject": "Need groceries", "description": "I'm out of food"})},
        None,
    )
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    expected_keys = {
        "contains_profanity",
        "1. profanity",
        "contains_depressive_content",
        "contains_suicidal_content",
        "2. Depressive/Suicidal Content",
        "contains_threatening_content",
        "3. Threatening Content",
        "review_reason",
    }
    assert set(body.keys()) == expected_keys
