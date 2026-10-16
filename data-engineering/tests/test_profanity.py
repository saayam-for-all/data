import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from src import profanity_check as sc

API_URL = "https://moderation.example.com/check"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.setenv("PROFANITY_API_URL", API_URL)
    monkeypatch.delenv("PROFANITY_API_KEY", raising=False)


def reply(body):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    response = MagicMock()
    response.read.return_value = raw
    context = MagicMock()
    context.__enter__.return_value = response
    context.__exit__.return_value = False
    return context


def with_reply(body):
    opener = MagicMock()
    opener.open.return_value = reply(body)
    return patch.object(sc.urllib.request, "build_opener", return_value=opener), opener


def call(body, **kwargs):
    patcher, opener = with_reply(body)
    with patcher:
        return sc.get_severity_score("Need food", "for my family", **kwargs), opener


# ---- extract_score: valid replies ----

@pytest.mark.parametrize("score", [0, 1, 2, 3])
def test_single_score(score):
    assert sc.extract_score({"severity_score": score}) == score


def test_list_only_uses_highest():
    assert sc.extract_score({"severity_scores": [1, 3]}) == 3


def test_list_of_one():
    assert sc.extract_score({"severity_scores": [0]}) == 0


def test_single_and_list_that_agree():
    assert sc.extract_score({"severity_score": 3, "severity_scores": [1, 3]}) == 3


def test_extra_fields_are_ignored():
    assert sc.extract_score({"severity_score": 2, "note": "anything"}) == 2


# ---- extract_score: envelopes ----

def test_unwraps_json_string_body():
    payload = {"statusCode": 200, "body": json.dumps({"severity_score": 3})}
    assert sc.extract_score(payload) == 3


def test_unwraps_dict_body():
    assert sc.extract_score({"statusCode": 200, "body": {"severity_score": 1}}) == 1


def test_envelope_without_status_code_is_unwrapped():
    assert sc.extract_score({"body": json.dumps({"severity_score": 2})}) == 2


@pytest.mark.parametrize("status", [400, 500, 502, 302, "200", True])
def test_failing_envelope_status_is_rejected(status):
    payload = {"statusCode": status, "body": json.dumps({"severity_score": 0})}
    with pytest.raises(sc.SeverityCheckError):
        sc.extract_score(payload)


def test_envelope_with_invalid_json_body_is_rejected():
    with pytest.raises(sc.SeverityCheckError):
        sc.extract_score({"statusCode": 200, "body": "not json"})


def test_envelope_nested_twice_is_rejected():
    inner = {"statusCode": 200, "body": json.dumps({"severity_score": 0})}
    with pytest.raises(sc.SeverityCheckError):
        sc.extract_score({"statusCode": 200, "body": json.dumps(inner)})


# ---- extract_score: invalid replies never pass ----

@pytest.mark.parametrize("payload", [
    {},
    [],
    "3",
    None,
    {"severity_score": None},
    {"severity_score": 4},
    {"severity_score": -1},
    {"severity_score": "2"},
    {"severity_score": 2.0},
    {"severity_score": True},
    {"severity_score": False},
    {"severity_scores": []},
    {"severity_scores": "13"},
    {"severity_scores": [1, 4]},
    {"severity_scores": [True]},
    {"severity_score": 1, "severity_scores": [1, 3]},
    {"severity_score": 0, "error": "model failed"},
])
def test_invalid_replies_are_rejected(payload):
    with pytest.raises(sc.SeverityCheckError):
        sc.extract_score(payload)


# ---- get_severity_score: the request ----

def test_returns_score_from_api():
    score, _ = call({"severity_score": 2})
    assert score == 2


def test_sends_expected_request():
    _, opener = call({"severity_score": 0})

    request = opener.open.call_args[0][0]
    assert request.full_url == API_URL
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {
        "subject": "Need food",
        "description": "for my family",
    }
    assert opener.open.call_args.kwargs["timeout"] == 10


def test_timeout_can_be_changed():
    _, opener = call({"severity_score": 0}, timeout=3)
    assert opener.open.call_args.kwargs["timeout"] == 3


def test_api_key_header_is_sent_when_configured(monkeypatch):
    monkeypatch.setenv("PROFANITY_API_KEY", "secret")
    _, opener = call({"severity_score": 0})
    assert opener.open.call_args[0][0].get_header("X-api-key") == "secret"


def test_api_key_header_is_absent_when_not_configured():
    _, opener = call({"severity_score": 0})
    assert opener.open.call_args[0][0].get_header("X-api-key") is None


def test_arguments_override_environment():
    other = "https://other.example.com/check"
    _, opener = call({"severity_score": 0}, url=other, api_key="from-arg")
    request = opener.open.call_args[0][0]
    assert request.full_url == other
    assert request.get_header("X-api-key") == "from-arg"


def test_redirects_are_refused():
    patcher, _ = with_reply({"severity_score": 0})
    with patcher as build_opener:
        sc.get_severity_score("a", "b")
    build_opener.assert_called_once_with(sc._NoRedirect)
    assert sc._NoRedirect().redirect_request() is None


# ---- get_severity_score: configuration and input ----

@pytest.mark.parametrize("url", ["http://insecure.example.com", "ftp://x", "", "   "])
def test_requires_https_url(monkeypatch, url):
    monkeypatch.setenv("PROFANITY_API_URL", url)
    with pytest.raises(sc.SeverityCheckError):
        sc.get_severity_score("a", "b")


def test_missing_url_is_rejected(monkeypatch):
    monkeypatch.delenv("PROFANITY_API_URL")
    with pytest.raises(sc.SeverityCheckError):
        sc.get_severity_score("a", "b")


@pytest.mark.parametrize("subject, description", [
    (None, "help"),
    ("help", None),
    (123, "help"),
    ("", ""),
    ("   ", "  "),
])
def test_unusable_input_raises_value_error(subject, description):
    with pytest.raises(ValueError):
        sc.get_severity_score(subject, description)


def test_one_empty_field_is_allowed():
    patcher, _ = with_reply({"severity_score": 0})
    with patcher:
        assert sc.get_severity_score("Need food", "") == 0


# ---- get_severity_score: failures never look clean ----

@pytest.mark.parametrize("error", [
    urllib.error.URLError("connection refused"),
    urllib.error.HTTPError(API_URL, 500, "Server Error", {}, None),
    urllib.error.HTTPError(API_URL, 302, "Found", {}, None),
    TimeoutError("timed out"),
    ConnectionResetError("reset"),
])
def test_network_and_http_failures_raise(error):
    opener = MagicMock()
    opener.open.side_effect = error
    with patch.object(sc.urllib.request, "build_opener", return_value=opener):
        with pytest.raises(sc.SeverityCheckError):
            sc.get_severity_score("a", "b")


@pytest.mark.parametrize("raw", [b"not json", b"", b"\xff\xfe", b'{"severity_score": 9}'])
def test_unusable_replies_raise(raw):
    patcher, _ = with_reply(raw)
    with patcher:
        with pytest.raises(sc.SeverityCheckError):
            sc.get_severity_score("a", "b")


def test_failure_chains_the_original_error():
    opener = MagicMock()
    opener.open.side_effect = TimeoutError("timed out")
    with patch.object(sc.urllib.request, "build_opener", return_value=opener):
        with pytest.raises(sc.SeverityCheckError) as info:
            sc.get_severity_score("a", "b")
    assert isinstance(info.value.__cause__, TimeoutError)


# ---- Routing ----

class FakeFraudModel:
    def __init__(self, **fields):
        self.fields = fields
        self.fraud_request_id = None


class FakeSession:
    def __init__(self, fail_on_commit=None):
        self.added, self.commits, self.rollbacks = [], 0, 0
        self.fail_on_commit = fail_on_commit

    def add(self, row):
        self.added.append(row)

    def commit(self):
        if self.fail_on_commit:
            raise self.fail_on_commit
        self.commits += 1
        for number, row in enumerate(self.added, start=1):
            row.fraud_request_id = number

    def rollback(self):
        self.rollbacks += 1


def route(score, **kwargs):
    session = kwargs.pop("session", None) or FakeSession()
    result = sc.route_help_request(
        kwargs.pop("user_id", "user-1"), score, session=session,
        fraud_model=FakeFraudModel, **kwargs,
    )
    return result, session


def test_score_zero_continues_without_writing():
    result, session = route(0)
    assert result == {"severity_score": 0, "routed_to": "active_matching"}
    assert session.added == [] and session.commits == 0


@pytest.mark.parametrize("score", [1, 2, 3])
def test_flagged_scores_are_saved_to_fraud_requests(score):
    result, session = route(score)
    assert result == {
        "severity_score": score,
        "routed_to": "fraud_requests",
        "fraud_request_id": 1,
    }
    assert session.commits == 1
    row = session.added[0]
    assert row.fields["user_id"] == "user-1"
    assert f"score {score}" in row.fields["reason"]
    assert sc.SCORE_LABELS[score] in row.fields["reason"]


def test_reason_fits_the_255_column_limit():
    for score in sc.FRAUD_SCORES:
        _, session = route(score)
        assert len(session.added[0].fields["reason"]) <= 255


def test_request_datetime_is_saved_when_given():
    stamp = object()
    _, session = route(3, request_datetime=stamp)
    assert session.added[0].fields["request_datetime"] is stamp


def test_request_datetime_is_left_to_the_model_default_when_omitted():
    _, session = route(3)
    assert "request_datetime" not in session.added[0].fields


def test_fraud_scores_can_be_changed_in_one_place(monkeypatch):
    monkeypatch.setattr(sc, "FRAUD_SCORES", frozenset({3}))
    assert route(1)[0]["routed_to"] == "active_matching"
    assert route(3)[0]["routed_to"] == "fraud_requests"


def test_database_failure_rolls_back_and_raises():
    session = FakeSession(fail_on_commit=RuntimeError("db down"))
    with pytest.raises(RuntimeError, match="db down"):
        route(3, session=session)
    assert session.rollbacks == 1


@pytest.mark.parametrize("score", [4, -1, "2", 2.0, True, None])
def test_invalid_score_is_not_routed(score):
    session = FakeSession()
    with pytest.raises(ValueError):
        route(score, session=session)
    assert session.added == []


@pytest.mark.parametrize("user_id", ["", "   ", None, 12])
def test_invalid_user_id_is_not_routed(user_id):
    session = FakeSession()
    with pytest.raises(ValueError):
        route(3, user_id=user_id, session=session)
    assert session.added == []


def test_check_and_route_end_to_end():
    session = FakeSession()
    patcher, _ = with_reply({"severity_scores": [1, 3]})
    with patcher:
        result = sc.check_and_route(
            "Subject", "Description", "user-9", session=session, fraud_model=FakeFraudModel
        )
    assert result["routed_to"] == "fraud_requests"
    assert result["severity_score"] == 3
    assert session.added[0].fields["user_id"] == "user-9"


def test_check_and_route_clean_request_continues():
    session = FakeSession()
    patcher, _ = with_reply({"severity_score": 0})
    with patcher:
        result = sc.check_and_route(
            "Subject", "Description", "user-9", session=session, fraud_model=FakeFraudModel
        )
    assert result == {"severity_score": 0, "routed_to": "active_matching"}
    assert session.added == []


def test_check_and_route_writes_nothing_when_the_check_fails():
    session = FakeSession()
    opener = MagicMock()
    opener.open.side_effect = TimeoutError("timed out")
    with patch.object(sc.urllib.request, "build_opener", return_value=opener):
        with pytest.raises(sc.SeverityCheckError):
            sc.check_and_route(
                "Subject", "Description", "user-9",
                session=session, fraud_model=FakeFraudModel,
            )
    assert session.added == [] and session.commits == 0


# ---- Approved mapping: 0 -> active_matching, 1-3 -> fraud_requests ----

@pytest.mark.parametrize("score, destination", [
    (0, "active_matching"),
    (1, "fraud_requests"),
    (2, "fraud_requests"),
    (3, "fraud_requests"),
])
def test_score_to_destination_mapping(score, destination):
    result, session = route(score)
    assert result["routed_to"] == destination
    assert (len(session.added) == 1) == (destination == "fraud_requests")


def test_destination_names():
    assert sc.ACTIVE_MATCHING == "active_matching"
    assert sc.FRAUD_REQUESTS == "fraud_requests"


def test_failure_while_adding_the_row_rolls_back_and_raises():
    class BrokenSession(FakeSession):
        def add(self, row):
            raise RuntimeError("cannot add")

    session = BrokenSession()
    with pytest.raises(RuntimeError, match="cannot add"):
        route(2, session=session)
    assert session.rollbacks == 1 and session.commits == 0