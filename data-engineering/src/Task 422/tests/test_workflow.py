"""Real database transactions and HTTP-based screening through both endpoints."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
import requests
from sqlalchemy import func, select, text

from profanity_routing.domain import Classification, HelpRequest, WorkflowError
from profanity_routing.local_tools import local_server


def row_counts(store):
    """Count the persisted workflow effects in each table."""
    with store.engine.connect() as connection:
        return tuple(
            connection.scalar(select(func.count()).select_from(table))
            for table in (store.requests, store.fraud_requests, store.screenings)
        )


@pytest.mark.parametrize(
    "subject,score",
    [
        ("Normal fixture", 0),
        ("Profanity fixture", 1),
        ("Support fixture", 2),
        ("Threat fixture", 3),
        ("Mixed fixture", 3),
    ],
)
def test_end_to_end_routing(app, store, submission, subject, score):
    """Screen via real upstream HTTP and inspect actual destination rows."""
    submission["subject"] = subject
    with local_server(app) as url:
        response = requests.post(f"{url}/api/help_requests", json=submission, timeout=5)
    assert response.status_code == 200
    result = response.json()
    assert result["severity_score"] == score
    assert result["recorded"] is True
    assert result["replayed"] is False
    assert result["matching_invoked"] is False
    assert row_counts(store) == ((1, 0, 1) if score == 0 else (0, 1, 1))
    with store.engine.connect() as connection:
        audit = connection.execute(select(store.screenings)).mappings().one()
        assert audit["payload"]["description"] == submission["description"]
        assert audit["severity_score"] == score
        if score == 0:
            row = connection.execute(select(store.requests)).mappings().one()
            assert row["req_id"] == submission["request_id"]
            assert row["req_subj"] == subject
            assert result["workflow_status"] == "ready_for_matching"
        else:
            row = connection.execute(select(store.fraud_requests)).mappings().one()
            assert row["user_id"] == submission["user_id"]
            assert f"score {score}" in row["reason"]
            assert result["workflow_status"] == "held_for_review"


@pytest.mark.parametrize(
    "subject", ["API outage fixture", "Model failure fixture", "Unknown fixture"]
)
def test_failed_classification_writes_nothing(app, store, submission, subject):
    """The original API's embedded model error is a failure despite HTTP 200."""
    submission["subject"] = subject
    response = app.test_client().post("/api/help_requests", json=submission)
    assert response.status_code == 503
    assert response.json["severity_score"] is None
    assert response.json["recorded"] is False
    assert row_counts(store) == (0, 0, 0)


@pytest.mark.parametrize("payload", [None, [], {}, {"request_id": 123}])
def test_invalid_payloads_do_not_call_api(app, service, store, monkeypatch, payload):
    """Validate the input before any external operation."""
    classify = Mock()
    monkeypatch.setattr(service.client, "classify", classify)
    response = app.test_client().post("/api/help_requests", json=payload)
    assert response.status_code == 400
    classify.assert_not_called()
    assert row_counts(store) == (0, 0, 0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", ""),
        ("user_id", True),
        ("subject", " "),
        ("description", None),
        ("subject", "x" * 126),
        ("description", "x" * 256),
        ("location", "x" * 126),
        ("category_id", "x" * 51),
        ("severity_score", 0),
    ],
)
def test_input_constraints(app, submission, field, value):
    """Reject malformed fields, schema overflows and client-supplied scores."""
    submission[field] = value
    assert app.test_client().post("/api/help_requests", json=submission).status_code == 400


def test_http_boundary(app):
    """Malformed JSON, wrong methods, and oversized requests stay controlled."""
    client = app.test_client()
    assert client.get("/health").json == {"status": "ok"}
    assert client.get("/api/help_requests").status_code == 405
    assert (
        client.post("/api/help_requests", data="{", content_type="application/json").status_code
        == 400
    )
    assert (
        client.post(
            "/api/help_requests", data="x" * 20_000, content_type="application/json"
        ).status_code
        == 413
    )


@pytest.mark.parametrize("subject", ["Normal fixture", "Threat fixture"])
def test_retry_replays_without_rescreening(app, service, store, submission, monkeypatch, subject):
    """Committed submissions stay idempotent even if the API is later down."""
    submission["subject"] = subject
    first = app.test_client().post("/api/help_requests", json=submission)
    assert first.status_code == 200
    before = row_counts(store)
    classify = Mock(side_effect=AssertionError("Must not rescreen a committed request"))
    monkeypatch.setattr(service.client, "classify", classify)
    replay = app.test_client().post("/api/check_profanity", json=submission)
    assert replay.status_code == 200
    assert replay.json == {**first.json, "replayed": True}
    assert row_counts(store) == before
    classify.assert_not_called()


def test_conflicting_id_is_not_a_new_request(app, store, submission):
    """An ID cannot be reused to replace already-screened text or identity."""
    client = app.test_client()
    assert client.post("/api/help_requests", json=submission).status_code == 200
    response = client.post("/api/help_requests", json={**submission, "user_id": "another-user"})
    assert response.status_code == 409
    assert response.json["error_code"] == "request_id_conflict"
    assert row_counts(store) == (1, 0, 1)


@pytest.mark.parametrize(
    "subject,table", [("Normal fixture", "request"), ("Threat fixture", "fraud_requests")]
)
def test_database_failure_rolls_back_and_can_be_retried(app, store, submission, subject, table):
    """Fail the destination insert after the ledger write, then retry successfully."""
    submission["subject"] = subject
    with store.engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE TRIGGER fail_destination BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'test storage failure'); END"
            )
        )
    client = app.test_client()
    response = client.post("/api/help_requests", json=submission)
    assert response.status_code == 503
    assert response.json["error_code"] == "storage_unavailable"
    assert "test storage failure" not in response.get_data(as_text=True)
    assert row_counts(store) == (0, 0, 0)
    with store.engine.begin() as connection:
        connection.execute(text("DROP TRIGGER fail_destination"))
    assert client.post("/api/help_requests", json=submission).status_code == 200
    assert row_counts(store) == ((1, 0, 1) if table == "request" else (0, 1, 1))


def test_unavailable_database_does_not_call_api(app, service, store, submission, monkeypatch):
    """A missing ledger cannot allow an untracked request into matching."""
    store.screenings.drop(store.engine)
    classify = Mock()
    monkeypatch.setattr(service.client, "classify", classify)
    response = app.test_client().post("/api/help_requests", json=submission)
    assert response.status_code == 503
    classify.assert_not_called()


@pytest.mark.parametrize("score", [0, 3])
def test_concurrent_duplicate_writes_are_atomic(store, submission, score):
    """Two simultaneous workers create one destination row and one receipt."""
    request = HelpRequest.from_payload(submission)
    classification = Classification(score, () if score == 0 else ("threatening",))
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(store.record, request, classification) for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]
    assert sorted(result["replayed"] for result in results) == [False, True]
    assert row_counts(store) == ((1, 0, 1) if score == 0 else (0, 1, 1))


def test_unicode_and_optional_fields(app, store, submission):
    """Preserve multilingual text and supplied matching fields in the database."""
    submission.update(
        description="Necesito ayuda con alimentación.", location="Chicago", category_id="food"
    )
    assert app.test_client().post("/api/help_requests", json=submission).status_code == 200
    with store.engine.connect() as connection:
        row = connection.execute(select(store.requests)).mappings().one()
    assert row["req_desc"] == submission["description"]
    assert row["req_loc"] == "Chicago"
    assert row["req_cat_id"] == "food"
