"""Reliability and response-contract tests for the inappropriate content filter (#422).

All external dependencies (AWS SSM, Groq) are replaced with in-memory fakes and
the profane-word database is a temporary SQLite file, so no live AWS, Groq or
database resource is ever contacted.
"""

import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest

DATA_ENGINEERING_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DATA_ENGINEERING_DIR))

# Stub the third-party SDKs so the tests do not need them installed.
if "groq" not in sys.modules:
    groq_stub = types.ModuleType("groq")

    class Groq:
        pass

    groq_stub.Groq = Groq
    sys.modules["groq"] = groq_stub

if "boto3" not in sys.modules:
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.client = lambda *args, **kwargs: None
    sys.modules["boto3"] = boto3_stub

from src.inappropriate_content_filter import inappropriate_content_filter as content_filter

SECRET_VALUE = "gsk_fake_secret_value_123"
SENSITIVE_MESSAGE = "AccessDenied for arn:aws:ssm:us-east-1:123456789012:parameter/dev/saayam/GenAI/groq/key"
THREAT_TEXT = "Get out of my way or you will regret it"

CLEAN_LLM = {
    "contains_profanity": False,
    "1. profanity": [],
    "contains_depressive_content": False,
    "contains_suicidal_content": False,
    "2. Depressive/Suicidal Content": [],
    "contains_threatening_content": False,
    "3. Threatening Content": [],
}


def llm_json(**overrides):
    return json.dumps({**CLEAN_LLM, **overrides})


class Harness:
    """Fake SSM + Groq that record how the filter used them."""

    def __init__(self):
        self.ssm_calls = 0
        self.groq_api_keys = []
        self.groq_calls = 0
        self.ssm_response = {"Parameter": {"Value": SECRET_VALUE}}
        self.ssm_exception = None
        self.llm_content = llm_json()
        self.llm_exception = None
        self.groq_init_exception = None

    def invoke(self, subject, description):
        event = {"body": json.dumps({"subject": subject, "description": description})}
        return self.invoke_event(event)

    def invoke_event(self, event):
        result = content_filter.lambda_handler(event, None)
        raw = result["body"]
        try:
            body = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            body = raw
        return result["statusCode"], body, raw


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Temp profane-word DB + fake AWS/Groq wired into the filter module."""
    conn = sqlite3.connect(tmp_path / "profane_words.db")
    conn.execute("CREATE TABLE profane_words (words TEXT UNIQUE)")
    conn.executemany("INSERT INTO profane_words (words) VALUES (?)", [("damn",), ("idiot",)])
    conn.commit()
    conn.close()
    monkeypatch.chdir(tmp_path)

    h = Harness()

    class FakeSSM:
        def get_parameter(self, **kwargs):
            h.ssm_calls += 1
            if h.ssm_exception is not None:
                raise h.ssm_exception
            return h.ssm_response

    monkeypatch.setattr(content_filter.boto3, "client", lambda *a, **k: FakeSSM())

    class FakeGroq:
        def __init__(self, api_key=None, **kwargs):
            if h.groq_init_exception is not None:
                raise h.groq_init_exception
            h.groq_api_keys.append(api_key)
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            h.groq_calls += 1
            if h.llm_exception is not None:
                raise h.llm_exception
            message = types.SimpleNamespace(content=h.llm_content)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    monkeypatch.setattr(content_filter, "Groq", FakeGroq)
    return h


def flagged(body):
    return [item["score"] for item in body["severity_scores"] if item["flagged"] is True]


def assert_degraded_never_clean(status, body, raw):
    """Invariants that stop a failed classification from being read as 'normal'."""
    assert status == 503
    assert body["classification_status"] == "degraded"
    assert body["severity_score"] is None
    assert "0. This is a normal request" not in body
    zero = [i for i in body["severity_scores"] if i["score"] == 0][0]
    assert zero["flagged"] is False
    assert isinstance(body["error_code"], str) and body["error_code"]
    assert SECRET_VALUE not in raw
    assert "arn:aws" not in raw
    assert "Traceback" not in raw


# ---------------------------------------------------------------------------
# Confirmed defect 1: SSM response dict passed to Groq instead of the secret
# ---------------------------------------------------------------------------

def test_groq_receives_secret_string_not_ssm_response_dict(env):
    env.llm_content = llm_json()
    env.invoke("Need food", "We need groceries")
    assert env.groq_api_keys == [SECRET_VALUE]
    assert isinstance(env.groq_api_keys[0], str)


# ---------------------------------------------------------------------------
# Complete classification: scores, multi-category, backward compatibility
# ---------------------------------------------------------------------------

def test_normal_request_is_complete_with_score_zero(env):
    status, body, _ = env.invoke("Need food", "We need groceries")
    assert status == 200
    assert body["classification_status"] == "complete"
    assert body["severity_score"] == 0
    assert flagged(body) == [0]
    assert body["0. This is a normal request"] == []


def test_profanity_keyword_scores_one(env):
    status, body, _ = env.invoke("Help", "this is damn hard")
    assert status == 200
    assert body["classification_status"] == "complete"
    assert body["severity_score"] == 1
    assert body["contains_profanity"] is True
    assert body["1. profanity"] == ["damn"]


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"contains_depressive_content": True}, 2),
        ({"contains_suicidal_content": True}, 2),
        ({"contains_threatening_content": True}, 3),
    ],
)
def test_llm_categories_map_to_expected_score(env, overrides, expected):
    env.llm_content = llm_json(**overrides)
    status, body, _ = env.invoke("Help", "some text")
    assert status == 200
    assert body["classification_status"] == "complete"
    assert body["severity_score"] == expected


def test_multiple_categories_keep_list_and_use_highest_score(env):
    env.llm_content = llm_json(contains_threatening_content=True)
    status, body, _ = env.invoke("idiot", THREAT_TEXT)
    assert status == 200
    assert flagged(body) == [1, 3]
    # Provisional policy: highest flagged severity (precedence awaits maintainer confirmation).
    assert body["severity_score"] == 3


def test_success_response_keeps_legacy_fields_and_lambda_shape(env):
    env.llm_content = llm_json(contains_threatening_content=True, **{"3. Threatening Content": ["regret"]})
    result = content_filter.lambda_handler(
        {"body": json.dumps({"subject": "Help", "description": THREAT_TEXT})}, None
    )
    assert result["statusCode"] == 200
    assert result["headers"]["Content-Type"] == "application/json"
    assert result["headers"]["Access-Control-Allow-Origin"] == "*"
    body = json.loads(result["body"])
    for key in (
        "contains_profanity", "1. profanity",
        "contains_depressive_content", "contains_suicidal_content",
        "2. Depressive/Suicidal Content",
        "contains_threatening_content", "3. Threatening Content",
        "severity_scores",
    ):
        assert key in body
    assert [i["score"] for i in body["severity_scores"]] == [0, 1, 2, 3]
    assert body["3. Threatening Content"] == ["regret"]


# ---------------------------------------------------------------------------
# Confirmed defects 2-4: failures must not look like a clean 200 classification
# ---------------------------------------------------------------------------

def test_ssm_failure_is_degraded_not_normal(env):
    env.ssm_exception = RuntimeError(SENSITIVE_MESSAGE)
    status, body, raw = env.invoke("Help", THREAT_TEXT)
    assert_degraded_never_clean(status, body, raw)
    assert body["error_code"] == "classifier_secret_unavailable"
    assert env.groq_calls == 0
    assert THREAT_TEXT not in raw


@pytest.mark.parametrize(
    "ssm_response",
    [{}, {"Parameter": {}}, {"Parameter": {"Value": ""}}, {"Parameter": {"Value": "   "}}, {"Parameter": {"Value": None}}],
)
def test_malformed_or_empty_ssm_secret_is_degraded(env, ssm_response):
    env.ssm_response = ssm_response
    status, body, raw = env.invoke("Help", THREAT_TEXT)
    assert_degraded_never_clean(status, body, raw)
    assert body["error_code"] == "classifier_secret_unavailable"
    assert env.groq_calls == 0


def test_groq_failure_or_rate_limit_is_degraded(env):
    env.llm_exception = RuntimeError("429 Too Many Requests: rate limit for key " + SECRET_VALUE)
    status, body, raw = env.invoke("Help", THREAT_TEXT)
    assert_degraded_never_clean(status, body, raw)
    assert body["error_code"] == "classifier_unavailable"
    assert "429" not in raw


def test_groq_client_construction_failure_is_degraded(env):
    env.groq_init_exception = RuntimeError("bad key " + SECRET_VALUE)
    status, body, raw = env.invoke("Help", THREAT_TEXT)
    assert_degraded_never_clean(status, body, raw)
    assert body["error_code"] == "classifier_unavailable"


@pytest.mark.parametrize(
    "content",
    [
        "Sorry, I cannot help with that.",           # not JSON
        "[]",                                          # JSON but not an object
        "null",
        json.dumps({"contains_threatening_content": True}),  # incomplete
        llm_json(contains_threatening_content="false"),      # wrong type, looks "clean"
        llm_json(contains_depressive_content=None),
        llm_json(**{"1. profanity": "damn"}),
        llm_json(**{"2. Depressive/Suicidal Content": {"a": 1}}),
        llm_json(**{"3. Threatening Content": [1, 2]}),
    ],
)
def test_malformed_or_incomplete_llm_json_is_degraded(env, content):
    env.llm_content = content
    status, body, raw = env.invoke("Help", THREAT_TEXT)
    assert_degraded_never_clean(status, body, raw)
    assert body["error_code"] == "classifier_response_invalid"


def test_null_evidence_lists_are_treated_as_empty_lists(env):
    env.llm_content = json.dumps({
        "contains_profanity": False,
        "1. profanity": None,
        "contains_depressive_content": False,
        "contains_suicidal_content": False,
        "2. Depressive/Suicidal Content": None,
        "contains_threatening_content": False,
        "3. Threatening Content": None,
    })
    status, body, _ = env.invoke("Need food", "We need groceries")
    assert status == 200
    assert body["classification_status"] == "complete"
    assert body["severity_score"] == 0
    assert body["1. profanity"] == []
    assert body["2. Depressive/Suicidal Content"] == []
    assert body["3. Threatening Content"] == []


def test_null_evidence_list_does_not_change_severity(env):
    env.llm_content = llm_json(
        contains_threatening_content=True, **{"3. Threatening Content": None}
    )
    status, body, _ = env.invoke("Help", THREAT_TEXT)
    assert status == 200
    assert body["severity_score"] == 3
    assert body["3. Threatening Content"] == []


def test_missing_evidence_lists_are_treated_as_empty_lists(env):
    env.llm_content = json.dumps({
        "contains_depressive_content": True,
        "contains_suicidal_content": False,
        "contains_threatening_content": False,
    })
    status, body, _ = env.invoke("Help", "feeling hopeless")
    assert status == 200
    assert body["severity_score"] == 2
    assert body["1. profanity"] == []


def test_null_evidence_list_never_makes_missing_boolean_false(env):
    env.llm_content = json.dumps({
        "1. profanity": None,
        "contains_depressive_content": None,
        "contains_suicidal_content": False,
        "contains_threatening_content": False,
    })
    status, body, raw = env.invoke("Help", THREAT_TEXT)
    assert_degraded_never_clean(status, body, raw)


def test_markdown_fenced_llm_json_is_still_accepted(env):
    env.llm_content = "```json\n" + llm_json(contains_threatening_content=True) + "\n```"
    status, body, _ = env.invoke("Help", THREAT_TEXT)
    assert status == 200
    assert body["severity_score"] == 3


def test_degraded_with_keyword_hit_is_partial_information_only(env):
    env.llm_exception = RuntimeError("model unavailable")
    status, body, raw = env.invoke("damn", THREAT_TEXT)
    assert_degraded_never_clean(status, body, raw)
    assert body["contains_profanity"] is True
    assert body["1. profanity"] == ["damn"]
    assert flagged(body) == [1]
    # Required classifier output is unknown, not "false".
    assert body["contains_threatening_content"] is None
    assert body["contains_depressive_content"] is None
    assert body["contains_suicidal_content"] is None


def test_llm_cannot_override_contract_fields(env):
    env.llm_content = llm_json(
        contains_threatening_content=True,
        classification_status="degraded",
        severity_score=0,
    )
    status, body, _ = env.invoke("Help", THREAT_TEXT)
    assert status == 200
    assert body["classification_status"] == "complete"
    assert body["severity_score"] == 3


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"subject": "Help"},
        {"description": "text"},
        {"subject": None, "description": "text"},
        {"subject": "Help", "description": None},
        {"subject": 5, "description": "text"},
        {"subject": "Help", "description": ["x"]},
        {"subject": "   ", "description": ""},
    ],
)
def test_missing_or_invalid_input_returns_400_without_calling_services(env, payload):
    status, body, _ = env.invoke_event({"body": json.dumps(payload)})
    assert status == 400
    assert body["error_code"] == "invalid_input"
    assert "severity_score" not in body or body["severity_score"] is None
    assert "0. This is a normal request" not in body
    assert env.ssm_calls == 0
    assert env.groq_calls == 0


@pytest.mark.parametrize("event", [{}, {"body": None}, {"body": "not json"}, {"body": "[1, 2]"}, {"body": "null"}])
def test_missing_or_non_object_body_returns_400(env, event):
    status, body, _ = env.invoke_event(event)
    assert status == 400
    assert body["error_code"] == "invalid_input"
    assert env.ssm_calls == 0


# ---------------------------------------------------------------------------
# Keyword database failure is also a required-classifier failure
# ---------------------------------------------------------------------------

def test_missing_keyword_database_is_degraded(env, monkeypatch, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    status, body, raw = env.invoke("Help", THREAT_TEXT)
    assert status == 503
    assert body["classification_status"] == "degraded"
    assert body["severity_score"] is None
    assert body["error_code"] == "keyword_database_unavailable"
    assert "0. This is a normal request" not in body
    assert str(empty) not in raw


# ---------------------------------------------------------------------------
# Routing-consumer contract
# ---------------------------------------------------------------------------

def reference_consumer(status, body):
    """Minimal fail-closed consumer, mirroring how the routing PRs (#487/#494)
    treat a non-2xx response and the multi-score list."""
    if not 200 <= status < 300:
        return "held_for_review"
    if body.get("classification_status") != "complete":
        return "held_for_review"
    score = body["severity_score"]
    return "active_matching" if score == 0 else "fraud_requests"


def legacy_max_flagged_consumer(body):
    """Consumer logic of #487/#494 for the severity_scores list (ignores status fields)."""
    flagged_scores = [i["score"] for i in body["severity_scores"] if i["flagged"] is True and i["score"] > 0]
    return "fraud_requests" if flagged_scores else "active_matching"


@pytest.mark.parametrize(
    "setup",
    [
        lambda h: setattr(h, "ssm_exception", RuntimeError("denied")),
        lambda h: setattr(h, "llm_exception", RuntimeError("429")),
        lambda h: setattr(h, "llm_content", "not json"),
    ],
)
def test_degraded_response_is_never_routed_to_active_matching(env, setup):
    setup(env)
    status, body, _ = env.invoke("Help", THREAT_TEXT)
    assert reference_consumer(status, body) == "held_for_review"
    # Even a consumer that only reads the list and ignores status gets no
    # "flagged: true" clean marker for score 0.
    assert [i for i in body["severity_scores"] if i["score"] == 0][0]["flagged"] is False
    assert body["severity_score"] is None


def test_complete_response_routes_by_score(env):
    status, body, _ = env.invoke("Need food", "groceries please")
    assert reference_consumer(status, body) == "active_matching"
    env.llm_content = llm_json(contains_threatening_content=True)
    status, body, _ = env.invoke("Help", THREAT_TEXT)
    assert reference_consumer(status, body) == "fraud_requests"
    assert legacy_max_flagged_consumer(body) == "fraud_requests"
