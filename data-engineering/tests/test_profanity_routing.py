"""Tests for Help Request sentiment scoring and routing (issue #422).

Run from the `data-engineering/` directory:

    python -m pytest tests/test_profanity_routing.py -v

The database is mocked the way tests/test_organization_analytics.py and
CONTRIBUTING.md do it, so no Postgres and no AWS credentials are needed.

What these tests do NOT establish: that the lexicon catches real-world abuse
or real-world distress. They pin the taxonomy, the precedence rules and the
routing policy. Classification quality needs a labelled corpus, which this
repo does not have yet - see the PR notes.
"""

import importlib
import sys
import types

import pytest

# psycopg2 and boto3 are only needed by handler.py; stub them so the suite
# runs on a bare interpreter.
if "psycopg2" not in sys.modules:
    _psycopg2 = types.ModuleType("psycopg2")
    _psycopg2.connect = lambda **kwargs: None
    _extras = types.ModuleType("psycopg2.extras")
    _extras.RealDictCursor = object
    _psycopg2.extras = _extras
    sys.modules["psycopg2"] = _psycopg2
    sys.modules["psycopg2.extras"] = _extras

if "boto3" not in sys.modules:
    _boto3 = types.ModuleType("boto3")
    _boto3.client = lambda *args, **kwargs: None
    sys.modules["boto3"] = _boto3

from src.profanity import routing  # noqa: E402
from src.profanity import severity  # noqa: E402
from src.profanity.handler import lambda_handler, parse_event_body  # noqa: E402


# --- Test doubles ---------------------------------------------------------

class FakeCursor:
    """Replays canned rows and records the statements it was given."""

    def __init__(self, rows=None, raise_on_execute=None):
        self._rows = list(rows or [])
        self._raise = raise_on_execute
        self.queries = []
        self._current = None

    def execute(self, query, params=None):
        if self._raise:
            raise self._raise
        self.queries.append((query, params))
        self._current = self._rows.pop(0) if self._rows else None

    def fetchone(self):
        return self._current

    def fetchall(self):
        return self._current or []

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, **kwargs):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


CODE_ROW = {"code_label": "Foul Language", "code_desc": "offensive language"}
STATUS_ROW = {"req_status_id": 7}
SEQ_ROW = {"seq": 42}
INSERTED_ROW = {"req_id": "SP-000-000-004-0042"}


def payload(**overrides):
    base = {
        "req_user_id": "SID-00-000-000-000-000-001",
        "req_for_id": 1,
        "req_islead_id": 1,
        "req_cat_id": "1.1",
        "req_type_id": 2,
        "req_priority_id": 2,
        "req_subj": "Need help",
        "req_desc": "Please help with groceries",
    }
    base.update(overrides)
    return base


# --- Taxonomy -------------------------------------------------------------

class TestTaxonomy:
    """The codes must match the sentiment_codes seed data, not a severity ladder."""

    def test_codes_match_sentiment_codes_seed(self):
        assert severity.SAFE == 0
        assert severity.FOUL_LANGUAGE == 1
        assert severity.DEPRESSIVE_OR_SUICIDAL == 2
        assert severity.THREATENING == 3

    def test_labels_match_seed_labels(self):
        assert severity.CODE_LABELS[0] == "Good Request"
        assert severity.CODE_LABELS[1] == "Foul Language"
        assert severity.CODE_LABELS[2] == "Depressive or Suicidal"
        assert severity.CODE_LABELS[3] == "Threatening"


# --- Classification -------------------------------------------------------

class TestClassification:

    def test_clean_request_scores_zero(self):
        result = severity.classify("Need help with grocery delivery and milk")
        assert result["severity_score"] == 0
        assert result["contains_profanity"] is False
        assert result["matched_codes"] == []

    def test_empty_text_scores_zero(self):
        assert severity.classify("")["severity_score"] == 0
        assert severity.classify(None)["severity_score"] == 0

    def test_foul_language_scores_one(self):
        result = severity.classify("this damn plumbing is broken")
        assert result["severity_score"] == 1
        assert result["contains_profanity"] is True

    def test_distress_scores_two(self):
        result = severity.classify("i want to kill myself, nobody can help")
        assert result["severity_score"] == 2

    def test_threat_scores_three(self):
        result = severity.classify("i will kill you if you ignore this")
        assert result["severity_score"] == 3

    def test_weapon_reference_scores_three(self):
        assert severity.classify("i have a gun")["severity_score"] == 3

    def test_case_and_punctuation_are_ignored(self):
        assert severity.classify("What the HELL?!")["severity_score"] == 1

    def test_stretched_letters_are_matched(self):
        assert severity.classify("fuuuuucking useless")["severity_score"] == 1

    def test_substrings_do_not_match(self):
        # "assistance" contains "ass"; "classic" contains "ass" too.
        result = severity.classify("I need assistance with a classic car")
        assert result["severity_score"] == 0

    def test_matched_terms_are_reported_for_audit(self):
        result = severity.classify("this shit is damn broken")
        assert set(result["matches"][1]) == {"shit", "damn"}

    def test_classify_request_combines_subject_and_description(self):
        result = severity.classify_request("Need help", "this is damn urgent")
        assert result["severity_score"] == 1
        assert result["evaluated_fields"] == ["subject", "description"]


class TestPrecedence:
    """Distress must never be demoted to a profanity problem."""

    def test_kill_myself_is_distress_not_threat(self):
        result = severity.classify("i am going to kill myself")
        assert result["severity_score"] == 2

    def test_distress_outranks_foul_language(self):
        result = severity.classify("this damn life, i want to die")
        assert result["severity_score"] == 2
        assert 1 in result["matched_codes"]

    def test_threat_outranks_distress_but_both_recorded(self):
        result = severity.classify("i will kill you then kill myself")
        assert result["severity_score"] == 3
        assert result["matched_codes"] == [3, 2]

    def test_threat_outranks_foul_language(self):
        result = severity.classify("you damn fool, i will shoot you")
        assert result["severity_score"] == 3


# --- Routing policy -------------------------------------------------------

class TestRouting:

    def test_clean_request_is_allowed_and_writes_nothing(self):
        cursor = FakeCursor([{"code_label": "Good Request",
                              "code_desc": "clean"}])
        decision = routing.route(cursor, payload(),
                                 severity.classify("need groceries"))
        assert decision["action"] == routing.ALLOW
        assert decision["stored_in"] is None
        # Only the label lookup ran - no INSERT.
        assert not any("INSERT" in q for q, _ in cursor.queries)

    def test_foul_language_is_diverted_and_stored(self):
        cursor = FakeCursor([CODE_ROW, SEQ_ROW, STATUS_ROW, INSERTED_ROW])
        decision = routing.route(cursor, payload(),
                                 severity.classify("this damn thing"))
        assert decision["action"] == routing.DIVERT
        assert decision["stored_in"].endswith(".fraud_requests")
        assert decision["req_id"] == INSERTED_ROW["req_id"]
        assert decision["requires_human_review"] is True

    def test_distress_is_escalated_not_blocked(self):
        cursor = FakeCursor([CODE_ROW, SEQ_ROW, STATUS_ROW, INSERTED_ROW])
        decision = routing.route(cursor, payload(),
                                 severity.classify("i want to kill myself"))
        assert decision["escalate"] is True
        assert decision["blocked"] is False

    def test_threat_is_blocked(self):
        cursor = FakeCursor([CODE_ROW, SEQ_ROW, STATUS_ROW, INSERTED_ROW])
        decision = routing.route(cursor, payload(),
                                 severity.classify("i will kill you"))
        assert decision["blocked"] is True
        assert decision["escalate"] is False

    def test_ref_code_recorded_equals_the_score(self):
        cursor = FakeCursor([CODE_ROW, SEQ_ROW, STATUS_ROW, INSERTED_ROW])
        routing.route(cursor, payload(), severity.classify("i have a gun"))
        insert = [(q, p) for q, p in cursor.queries if "INSERT" in q][0]
        assert insert[1]["ref_code"] == 3

    def test_diverted_request_is_never_public(self):
        cursor = FakeCursor([CODE_ROW, SEQ_ROW, STATUS_ROW, INSERTED_ROW])
        routing.route(cursor, payload(to_public=True),
                      severity.classify("this damn thing"))
        insert = [(q, p) for q, p in cursor.queries if "INSERT" in q][0]
        assert insert[1]["to_public"] is False

    def test_caller_supplied_req_id_is_reused(self):
        cursor = FakeCursor([CODE_ROW, STATUS_ROW,
                             {"req_id": "REQ-000-000-000-0009"}])
        decision = routing.route(cursor, payload(req_id="REQ-000-000-000-0009"),
                                 severity.classify("this damn thing"))
        assert decision["req_id"] == "REQ-000-000-000-0009"
        # The SP sequence is not consulted when an id already exists.
        assert not any("nextval" in q for q, _ in cursor.queries)

    def test_label_comes_from_the_lookup_table(self):
        cursor = FakeCursor([{"code_label": "Seeded Label",
                              "code_desc": "from the DB"}])
        decision = routing.route(cursor, payload(),
                                 severity.classify("need groceries"))
        assert decision["severity_label"] == "Seeded Label"

    def test_label_lookup_works_with_a_tuple_cursor(self):
        cursor = FakeCursor([("Seeded Label", "from the DB")])
        label, desc = routing.resolve_code_label(cursor, 0)
        assert (label, desc) == ("Seeded Label", "from the DB")

    def test_unseeded_lookup_falls_back_without_failing(self):
        cursor = FakeCursor([None])
        decision = routing.route(cursor, payload(),
                                 severity.classify("need groceries"))
        assert decision["severity_label"] == "Good Request"


class TestNoHardcodedIds:

    def test_status_is_resolved_by_name(self):
        cursor = FakeCursor([CODE_ROW, SEQ_ROW, STATUS_ROW, INSERTED_ROW])
        routing.route(cursor, payload(), severity.classify("this damn thing"))
        status_query = [(q, p) for q, p in cursor.queries
                        if "request_status" in q][0]
        assert "req_status" in status_query[0]
        assert status_query[1]["name"] == routing.STATUS_FOR_SPECIAL_REQUEST

    def test_resolved_status_id_is_what_gets_inserted(self):
        cursor = FakeCursor([CODE_ROW, SEQ_ROW, STATUS_ROW, INSERTED_ROW])
        routing.route(cursor, payload(), severity.classify("this damn thing"))
        insert = [(q, p) for q, p in cursor.queries if "INSERT" in q][0]
        assert insert[1]["req_status_id"] == STATUS_ROW["req_status_id"]

    def test_unknown_status_name_raises_rather_than_guessing(self):
        cursor = FakeCursor([CODE_ROW, SEQ_ROW, None])
        with pytest.raises(LookupError) as exc:
            routing.route(cursor, payload(),
                          severity.classify("this damn thing"))
        assert "STATUS_FOR_SPECIAL_REQUEST" in str(exc.value)


class TestSpecialRequestId:

    def test_id_uses_the_sp_prefix_and_grouping(self):
        # 42 -> zfill(13) -> "0000000000042" -> 3/3/3/4 grouping
        cursor = FakeCursor([{"seq": 42}])
        assert routing.next_special_request_id(cursor) == "SP-000-000-000-0042"

    def test_id_grouping_with_a_larger_sequence_value(self):
        cursor = FakeCursor([{"seq": 1234567890123}])
        assert routing.next_special_request_id(cursor) == "SP-123-456-789-0123"

    def test_id_works_with_a_tuple_cursor(self):
        cursor = FakeCursor([(7,)])
        assert routing.next_special_request_id(cursor) == "SP-000-000-000-0007"

    def test_id_reads_the_configured_sequence(self):
        cursor = FakeCursor([{"seq": 1}])
        routing.next_special_request_id(cursor)
        query, _params = cursor.queries[0]
        assert routing.SPECIAL_REQUEST_SEQUENCE in query


class TestSqlHygiene:

    def test_values_are_bound_not_interpolated(self):
        cursor = FakeCursor([CODE_ROW, SEQ_ROW, STATUS_ROW, INSERTED_ROW])
        routing.route(cursor,
                      payload(req_subj="'; DROP TABLE requests;--"),
                      severity.classify("this damn thing"))
        for query, params in cursor.queries:
            assert "DROP TABLE" not in query
            if params is not None:
                assert isinstance(params, dict)

    def test_invalid_schema_name_is_rejected(self):
        original = routing.SCHEMA_NAME
        routing.SCHEMA_NAME = "public; DROP TABLE requests;--"
        try:
            with pytest.raises(ValueError):
                routing._schema()
        finally:
            routing.SCHEMA_NAME = original

    def test_invalid_table_name_is_rejected(self):
        original = routing.SPECIAL_REQUEST_TABLE
        routing.SPECIAL_REQUEST_TABLE = "fraud_requests; DROP TABLE users;--"
        try:
            cursor = FakeCursor([SEQ_ROW, STATUS_ROW, INSERTED_ROW])
            with pytest.raises(ValueError):
                routing.store_special_request(
                    cursor, payload(), severity.classify("damn"))
        finally:
            routing.SPECIAL_REQUEST_TABLE = original


# --- Handler --------------------------------------------------------------

class HandlerHarness:
    def run(self, event, rows, raise_on_execute=None, raise_on_connect=None,
            monkeypatch=None):
        cursor = FakeCursor(rows, raise_on_execute)
        self.connection = FakeConnection(cursor)
        self.cursor = cursor

        def fake_connection():
            if raise_on_connect:
                raise raise_on_connect
            return self.connection

        monkeypatch.setattr("src.profanity.handler.get_db_connection",
                            fake_connection)
        response = lambda_handler(event, None)
        import json as _json
        response["parsed"] = _json.loads(response["body"])
        return response


class TestHandler(HandlerHarness):

    def test_clean_request_returns_allow(self, monkeypatch):
        response = self.run(
            {"req_subj": "Need help", "req_desc": "groceries please"},
            [{"code_label": "Good Request", "code_desc": "clean"}],
            monkeypatch=monkeypatch)
        assert response["statusCode"] == 200
        assert response["parsed"]["action"] == "ALLOW"
        assert response["parsed"]["severity_score"] == 0
        # Nothing was written, so nothing to commit.
        assert self.connection.committed is False

    def test_diverted_request_is_committed(self, monkeypatch):
        event = dict(payload(), req_desc="this damn thing is broken")
        response = self.run(
            event, [CODE_ROW, SEQ_ROW, STATUS_ROW, INSERTED_ROW],
            monkeypatch=monkeypatch)
        assert response["parsed"]["action"] == "DIVERT"
        assert self.connection.committed is True

    def test_missing_text_returns_400(self, monkeypatch):
        response = self.run({}, [], monkeypatch=monkeypatch)
        assert response["statusCode"] == 400
        assert "req_subj" in response["parsed"]["error"]

    def test_diversion_without_required_columns_returns_422(self, monkeypatch):
        # Scored but unroutable: the score is still reported back.
        response = self.run({"req_desc": "i will kill you"}, [],
                            monkeypatch=monkeypatch)
        assert response["statusCode"] == 422
        assert response["parsed"]["severity_score"] == 3
        assert "req_user_id" in response["parsed"]["error"]

    def test_clean_request_does_not_require_insert_columns(self, monkeypatch):
        # A clean request needs no insert, so the columns stay optional.
        response = self.run(
            {"req_desc": "need help with groceries"},
            [{"code_label": "Good Request", "code_desc": "clean"}],
            monkeypatch=monkeypatch)
        assert response["statusCode"] == 200

    def test_api_gateway_string_body_is_parsed(self, monkeypatch):
        import json as _json
        response = self.run(
            {"body": _json.dumps({"req_desc": "need groceries"})},
            [{"code_label": "Good Request", "code_desc": "clean"}],
            monkeypatch=monkeypatch)
        assert response["statusCode"] == 200

    def test_connection_failure_returns_500(self, monkeypatch):
        response = self.run(
            {"req_desc": "need groceries"}, [],
            raise_on_connect=RuntimeError("connection refused"),
            monkeypatch=monkeypatch)
        assert response["statusCode"] == 500
        assert response["parsed"]["error"] == "Internal server error"

    def test_query_failure_rolls_back_and_returns_500(self, monkeypatch):
        response = self.run(
            dict(payload(), req_desc="this damn thing"), [],
            raise_on_execute=RuntimeError("syntax error"),
            monkeypatch=monkeypatch)
        assert response["statusCode"] == 500
        assert self.connection.rolled_back is True

    def test_failure_does_not_leak_internals(self, monkeypatch):
        response = self.run(
            {"req_desc": "need groceries"}, [],
            raise_on_connect=RuntimeError("password=hunter2 host=db.internal"),
            monkeypatch=monkeypatch)
        assert "hunter2" not in response["body"]

    def test_response_reports_the_score_for_the_dashboard(self, monkeypatch):
        event = dict(payload(), req_desc="i want to kill myself")
        response = self.run(
            event, [CODE_ROW, SEQ_ROW, STATUS_ROW, INSERTED_ROW],
            monkeypatch=monkeypatch)
        body = response["parsed"]
        assert body["severity_score"] == 2
        assert body["escalate"] is True
        assert body["blocked"] is False
        assert body["requiresHumanReview"] is True

    def test_user_words_are_not_in_the_response(self, monkeypatch):
        # The matched terms are the user's own words; the API reports codes.
        event = dict(payload(), req_desc="this damn thing")
        response = self.run(
            event, [CODE_ROW, SEQ_ROW, STATUS_ROW, INSERTED_ROW],
            monkeypatch=monkeypatch)
        assert "damn" not in response["body"]


class TestEventParsing:

    def test_direct_invoke_payload(self):
        assert parse_event_body({"req_desc": "x"}) == {"req_desc": "x"}

    def test_empty_event(self):
        assert parse_event_body(None) == {}

    def test_malformed_json_body(self):
        assert parse_event_body({"body": "{not json"}) == {}


# --- Configurability ------------------------------------------------------

class TestConfiguration:
    """The parts the issue left open must be settings, not literals."""

    def test_special_request_table_is_configurable(self, monkeypatch):
        monkeypatch.setenv("SPECIAL_REQUEST_TABLE", "special_requests")
        module = importlib.reload(routing)
        try:
            assert module.SPECIAL_REQUEST_TABLE == "special_requests"
        finally:
            monkeypatch.delenv("SPECIAL_REQUEST_TABLE")
            importlib.reload(routing)

    def test_diverted_codes_are_configurable(self, monkeypatch):
        monkeypatch.setenv("DIVERTED_SENTIMENT_CODES", "2,3")
        module = importlib.reload(routing)
        try:
            assert module.DIVERTED_CODES == {2, 3}
            # Foul language now stays in the normal flow, but is still flagged.
            cursor = FakeCursor([CODE_ROW])
            decision = module.route(cursor, payload(),
                                    severity.classify("this damn thing"))
            assert decision["action"] == module.ALLOW
            assert decision["requires_human_review"] is True
        finally:
            monkeypatch.delenv("DIVERTED_SENTIMENT_CODES")
            importlib.reload(routing)

    def test_status_name_is_configurable(self, monkeypatch):
        monkeypatch.setenv("STATUS_FOR_SPECIAL_REQUEST", "UNDER_REVIEW")
        module = importlib.reload(routing)
        try:
            assert module.STATUS_FOR_SPECIAL_REQUEST == "UNDER_REVIEW"
        finally:
            monkeypatch.delenv("STATUS_FOR_SPECIAL_REQUEST")
            importlib.reload(routing)

    def test_defaults_are_restored(self):
        assert routing.SPECIAL_REQUEST_TABLE == "fraud_requests"
        assert routing.DIVERTED_CODES == {1, 2, 3}
