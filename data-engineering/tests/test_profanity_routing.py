"""Tests for the Profanity API severity scale and routing (issue #422).

The routing contract in `src/profanity/severity.py` is pure, so it is tested
directly with no mocks. The classifier's live gpt-3.5-turbo call cannot be
exercised here - there is no API key in this environment and `openai` is not
installed - so those tests inject a fake client and cover what is actually
testable: prompt construction, validation and coercion of the model's reply,
and the error paths.

Run with:
    pytest -v tests/test_profanity_routing.py
"""
import json

import pytest

from src.profanity import classifier as classifier_module
from src.profanity.handler import lambda_handler, parse_body
from src.profanity.severity import (
    ACTION_BLOCK,
    ACTION_FLAG,
    ACTION_HOLD,
    ACTION_PROCEED,
    SEVERITY_CLEAN,
    SEVERITY_EXTREME,
    SEVERITY_MILD,
    SEVERITY_SCALE,
    SEVERITY_SEVERE,
    normalize_score,
    route,
)


DECISION_KEYS = {
    "severity_score",
    "severity_label",
    "action",
    "allowed",
    "requires_review",
    "description",
    "reasoning",
    "error",
}


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeClient:
    """Stands in for openai.OpenAI, recording the prompt it was handed."""

    def __init__(self, content=None, raises=None):
        self._content = content
        self._raises = raises
        self.calls = []
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return FakeCompletion(self._content)


@pytest.fixture
def fake_client(monkeypatch):
    """Install a fake OpenAI client in place of the real one."""

    def _install(content=None, raises=None):
        client = FakeClient(content=content, raises=raises)
        monkeypatch.setattr(classifier_module, "get_client", lambda: client)
        return client

    return _install


def reply(score, reasoning="because"):
    return json.dumps({"severity_score": score, "reasoning": reasoning})


# --------------------------------------------------------------------------
# The severity scale itself
# --------------------------------------------------------------------------


def test_scale_covers_exactly_the_four_documented_scores():
    assert set(SEVERITY_SCALE) == {0, 1, 2, 3}


def test_scale_matches_the_issue_tiers():
    assert SEVERITY_SCALE[SEVERITY_CLEAN]["action"] == ACTION_PROCEED
    assert SEVERITY_SCALE[SEVERITY_MILD]["action"] == ACTION_FLAG
    assert SEVERITY_SCALE[SEVERITY_SEVERE]["action"] == ACTION_HOLD
    assert SEVERITY_SCALE[SEVERITY_EXTREME]["action"] == ACTION_BLOCK


def test_only_clean_and_mild_may_enter_the_matching_workflow():
    assert SEVERITY_SCALE[SEVERITY_CLEAN]["allowed"] is True
    assert SEVERITY_SCALE[SEVERITY_MILD]["allowed"] is True
    assert SEVERITY_SCALE[SEVERITY_SEVERE]["allowed"] is False
    assert SEVERITY_SCALE[SEVERITY_EXTREME]["allowed"] is False


def test_review_is_required_for_mild_and_severe_only():
    """A blocked request needs no review; it is already rejected."""
    assert SEVERITY_SCALE[SEVERITY_CLEAN]["requires_review"] is False
    assert SEVERITY_SCALE[SEVERITY_MILD]["requires_review"] is True
    assert SEVERITY_SCALE[SEVERITY_SEVERE]["requires_review"] is True
    assert SEVERITY_SCALE[SEVERITY_EXTREME]["requires_review"] is False


def test_allowed_scores_are_monotonically_more_restrictive():
    allowed = [SEVERITY_SCALE[s]["allowed"] for s in sorted(SEVERITY_SCALE)]
    assert allowed == [True, True, False, False]


# --------------------------------------------------------------------------
# normalize_score
# --------------------------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [(0, 0), (1, 1), (2, 2), (3, 3)])
def test_normalize_accepts_valid_ints(raw, expected):
    assert normalize_score(raw) == expected


@pytest.mark.parametrize("raw, expected", [(0.0, 0), (2.0, 2), ("3", 3), (" 1 ", 1), ("2.0", 2)])
def test_normalize_accepts_whole_valued_floats_and_strings(raw, expected):
    """An LLM may answer 2, 2.0 or "2" for the same verdict."""
    assert normalize_score(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [None, -1, 4, 99, 2.5, "2.5", "high", "", "  ", [2], {"severity_score": 2}, object()],
)
def test_normalize_rejects_unusable_values(raw):
    assert normalize_score(raw) is None


@pytest.mark.parametrize("raw", [True, False])
def test_normalize_rejects_booleans(raw):
    """bool is an int subclass, so True must not silently become score 1."""
    assert normalize_score(raw) is None


def test_out_of_range_scores_are_rejected_not_clamped():
    """A 7 is a broken classifier, not an EXTREME verdict."""
    assert normalize_score(7) is None
    assert normalize_score(-3) is None


# --------------------------------------------------------------------------
# route
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score, action, allowed",
    [
        (0, ACTION_PROCEED, True),
        (1, ACTION_FLAG, True),
        (2, ACTION_HOLD, False),
        (3, ACTION_BLOCK, False),
    ],
)
def test_route_maps_each_score_to_its_action(score, action, allowed):
    decision = route(score)
    assert decision["severity_score"] == score
    assert decision["action"] == action
    assert decision["allowed"] is allowed


def test_route_returns_a_complete_decision():
    assert set(route(0)) == DECISION_KEYS


def test_route_carries_reasoning_and_error_through():
    decision = route(2, reasoning="slur in description", error=None)
    assert decision["reasoning"] == "slur in description"
    assert decision["error"] is None


def test_route_defaults_reasoning_to_empty_string():
    assert route(0)["reasoning"] == ""


@pytest.mark.parametrize("bad", [None, 9, "unknown", 1.5, True])
def test_unusable_score_fails_open_but_flagged(bad):
    """An undetermined verdict must not stall the request, nor pass as clean."""
    decision = route(bad)
    assert decision["severity_score"] is None
    assert decision["severity_label"] == "UNKNOWN"
    assert decision["action"] == ACTION_FLAG
    assert decision["allowed"] is True
    assert decision["requires_review"] is True


def test_unknown_is_distinguishable_from_a_real_clean_verdict():
    """The whole point of score None: a caller can tell the two apart."""
    assert route(0)["severity_score"] == 0
    assert route(None)["severity_score"] is None
    assert route(0)["action"] != route(None)["action"]


def test_route_does_not_mutate_the_shared_scale():
    """Decisions are copies; a caller editing one must not corrupt the table."""
    route(3)["description"] = "tampered"
    assert SEVERITY_SCALE[SEVERITY_EXTREME]["description"] != "tampered"
    assert "severity_score" not in SEVERITY_SCALE[SEVERITY_EXTREME]


# --------------------------------------------------------------------------
# classify_content - prompt, validation, coercion
# --------------------------------------------------------------------------


def test_empty_content_is_clean_without_calling_the_model(fake_client):
    client = fake_client(reply(3))
    result = classifier_module.classify_content("", "")
    assert result["severity_score"] == 0
    assert result["error"] is None
    assert client.calls == []


def test_whitespace_only_content_is_clean_without_calling_the_model(fake_client):
    client = fake_client(reply(3))
    assert classifier_module.classify_content("   ", "\n\t")["severity_score"] == 0
    assert client.calls == []


@pytest.mark.parametrize("score", [0, 1, 2, 3])
def test_valid_model_reply_is_returned(fake_client, score):
    fake_client(reply(score))
    result = classifier_module.classify_content("subject", "description")
    assert result["severity_score"] == score
    assert result["error"] is None


def test_model_reasoning_is_carried_through(fake_client):
    fake_client(reply(1, reasoning="one mild expletive"))
    assert classifier_module.classify_content("s", "d")["reasoning"] == "one mild expletive"


def test_prompt_contains_the_content_and_the_whole_scale(fake_client):
    client = fake_client(reply(0))
    classifier_module.classify_content("Need food", "My family has not eaten")

    prompt = client.calls[0]["messages"][0]["content"]
    assert "Need food" in prompt
    assert "My family has not eaten" in prompt
    for score in sorted(SEVERITY_SCALE):
        assert f"{score} = {SEVERITY_SCALE[score]['severity_label']}" in prompt


def test_prompt_separates_hardship_from_profanity(fake_client):
    """Guards the rule that keeps genuine distress out of the profanity score."""
    client = fake_client(reply(0))
    classifier_module.classify_content("s", "d")
    prompt = client.calls[0]["messages"][0]["content"]
    assert "not profanity" in prompt.lower()


def test_model_is_called_deterministically(fake_client):
    client = fake_client(reply(0))
    classifier_module.classify_content("s", "d")
    assert client.calls[0]["temperature"] == 0
    assert client.calls[0]["model"] == classifier_module.MODEL


@pytest.mark.parametrize("malformed", ["not json", "", "[1, 2]", '"a string"', "{broken"])
def test_malformed_model_reply_yields_an_undetermined_score(fake_client, malformed):
    fake_client(malformed)
    result = classifier_module.classify_content("s", "d")
    assert result["severity_score"] is None
    assert result["error"]


def test_missing_score_field_yields_an_undetermined_score(fake_client):
    fake_client(json.dumps({"reasoning": "forgot the score"}))
    assert classifier_module.classify_content("s", "d")["severity_score"] is None


def test_out_of_range_model_score_is_rejected_by_routing(fake_client):
    """The classifier passes the raw value on; normalize_score owns the rule."""
    fake_client(reply(9))
    result = classifier_module.classify_content("s", "d")
    assert route(result["severity_score"])["severity_score"] is None


def test_api_error_yields_an_undetermined_score(fake_client):
    fake_client(raises=RuntimeError("upstream exploded"))
    result = classifier_module.classify_content("s", "d")
    assert result["severity_score"] is None
    assert "upstream exploded" in result["error"]
    assert "upstream exploded" in result["reasoning"]


def test_missing_api_key_is_reported_not_raised(monkeypatch):
    """A missing key must degrade to a flagged decision, never crash the workflow."""
    monkeypatch.setattr(classifier_module, "_client", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(classifier_module, "OPENAI_AVAILABLE", True)

    result = classifier_module.classify_content("s", "d")
    assert result["severity_score"] is None
    assert "OPENAI_API_KEY" in result["error"]


def test_missing_openai_package_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(classifier_module, "_client", None)
    monkeypatch.setattr(classifier_module, "OPENAI_AVAILABLE", False)

    result = classifier_module.classify_content("s", "d")
    assert result["severity_score"] is None
    assert "openai" in result["error"]


def test_severity_module_imports_without_openai():
    """The routing contract must not depend on the optional driver."""
    import importlib

    import src.profanity.severity as severity_module

    assert importlib.reload(severity_module).normalize_score(2) == 2


# --------------------------------------------------------------------------
# parse_body
# --------------------------------------------------------------------------


def test_parse_body_accepts_a_dict_body():
    assert parse_body({"body": {"subject": "s"}}) == {"subject": "s"}


def test_parse_body_accepts_a_json_string_body():
    assert parse_body({"body": json.dumps({"subject": "s"})}) == {"subject": "s"}


def test_parse_body_accepts_top_level_fields():
    assert parse_body({"subject": "s"}) == {"subject": "s"}


@pytest.mark.parametrize("event", [None, {}, "a string", 42, {"body": "not json"}, {"body": "[1]"}])
def test_parse_body_degrades_to_empty_dict(event):
    assert parse_body(event) == {}


# --------------------------------------------------------------------------
# lambda_handler
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score, action",
    [(0, ACTION_PROCEED), (1, ACTION_FLAG), (2, ACTION_HOLD), (3, ACTION_BLOCK)],
)
def test_handler_returns_the_routing_decision(fake_client, score, action):
    fake_client(reply(score))
    response = lambda_handler({"body": {"subject": "s", "description": "d"}}, None)

    assert response["statusCode"] == 200
    assert response["body"]["severity_score"] == score
    assert response["body"]["action"] == action


def test_handler_body_is_a_complete_decision(fake_client):
    fake_client(reply(0))
    assert set(lambda_handler({"subject": "s"}, None)["body"]) == DECISION_KEYS


def test_handler_accepts_request_table_column_names(fake_client):
    """req_subj/req_desc are the actual free-text columns on the request table."""
    client = fake_client(reply(0))
    lambda_handler({"req_subj": "Need a ride", "req_desc": "To a clinic"}, None)

    prompt = client.calls[0]["messages"][0]["content"]
    assert "Need a ride" in prompt
    assert "To a clinic" in prompt


def test_handler_prefers_categorizer_field_names_when_both_are_present(fake_client):
    client = fake_client(reply(0))
    lambda_handler({"subject": "preferred", "req_subj": "ignored"}, None)
    assert "preferred" in client.calls[0]["messages"][0]["content"]


@pytest.mark.parametrize("event", [None, {}, {"body": "not json"}])
def test_handler_treats_unusable_events_as_empty_clean_content(fake_client, event):
    fake_client(reply(3))
    response = lambda_handler(event, None)
    assert response["statusCode"] == 200
    assert response["body"]["severity_score"] == 0


def test_handler_fails_open_but_flagged_on_api_error(fake_client):
    fake_client(raises=RuntimeError("upstream exploded"))
    body = lambda_handler({"subject": "s", "description": "d"}, None)["body"]

    assert body["severity_score"] is None
    assert body["action"] == ACTION_FLAG
    assert body["allowed"] is True
    assert body["requires_review"] is True
    assert "upstream exploded" in body["error"]


def test_handler_returns_500_with_a_decision_on_internal_error(monkeypatch):
    """Even a bug here must hand the workflow a usable decision."""
    monkeypatch.setattr(
        "src.profanity.handler.classify_content",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    response = lambda_handler({"subject": "s"}, None)

    assert response["statusCode"] == 500
    assert set(response["body"]) == DECISION_KEYS
    assert response["body"]["action"] == ACTION_FLAG
    assert response["body"]["allowed"] is True
    assert "boom" in response["body"]["error"]


def test_handler_response_is_json_serializable(fake_client):
    fake_client(reply(2))
    json.dumps(lambda_handler({"subject": "s", "description": "d"}, None))
