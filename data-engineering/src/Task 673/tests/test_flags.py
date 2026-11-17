"""Response contract checks independent of AWS and PostgreSQL availability."""

import json
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from harness import ai_response, event, load_app


@pytest.mark.parametrize("value,expected", [
    (True, True), (False, False), (None, None),
    (np.bool_(True), True), (np.bool_(False), False),
    (1, True), (0, False), (1.0, True), (0.0, False),
    (np.int64(1), True), (np.float64(0), False),
    (float("nan"), None), (pd.NA, None),
    (" TRUE ", True), ("false", False), ("t", True), ("f", False),
    ("yes", True), ("no", False), ("on", True), ("off", False),
    ("1", True), ("0", False), ("", None), ("unknown", None),
    (2, None), (-1, None), (float("inf"), None),
])
def test_flags_are_native_booleans_or_none_after_merge(app, value, expected):
    """Exercise the pandas merge/serialization boundary, not only a converter."""
    db = pd.DataFrame([{"is_collaborator": value, "is_contributor": value}])
    merged = app.helpers.merge_organizations(db, None)
    row = merged.to_dict(orient="records")[0]
    flags = {key: row[key] for key in ("collaborator", "contributor")}
    assert flags["collaborator"] is expected
    assert flags["contributor"] is expected
    json.dumps(flags, allow_nan=False)


@pytest.mark.parametrize("ai_present", [True, False])
def test_missing_column_is_null_and_flags_survive_concat(app, ai_present):
    """An absent column must remain nullable even when AI adds false values."""
    db = pd.DataFrame([{"is_collaborator": True}, {"is_collaborator": None}])
    ai = pd.DataFrame([{"is_collaborator": False}]) if ai_present else None
    rows = app.helpers.merge_organizations(db, ai).to_dict(orient="records")
    assert [row["contributor"] for row in rows[:2]] == [None, None]
    assert rows[0]["collaborator"] is True
    assert rows[1]["collaborator"] is None
    if ai_present:
        assert rows[-1]["contributor"] is False
        assert rows[-1]["collaborator"] is False
    for row in rows:
        keys = list(row)
        assert keys[keys.index("collaborator") + 1] == "contributor"


def test_ai_flags_are_false_even_if_payload_claims_otherwise(app):
    """GenAI cannot verify membership flags."""
    ai = app.helpers.get_ai_orgs("Food", "Groceries", "Chicago", "Food")
    row = app.helpers.merge_organizations(None, ai).to_dict(orient="records")[0]
    assert row["source"] == "ai"
    assert row["collaborator"] is False
    assert row["contributor"] is False


def test_merge_does_not_mutate_inputs_or_other_fields(app):
    """Preserve response values, geocoding inputs, and input DataFrames."""
    db = pd.DataFrame([{
        "org_name": "Pantry", "org_type": "Nonprofit", "is_collaborator": True,
        "is_contributor": False, "org_rating": 4.8, "org_size": "Large",
        "location": "Chicago, IL", "phone": "555-0100", "email": "x@example.invalid",
        "web_url": "https://example.invalid", "mission": "Food", "source": "db",
        "_geo_address": "10 Example Street", "_geo_city": "Chicago", "_geo_state": "IL",
    }])
    ai = pd.DataFrame([{"organization_name": "Generated", "is_collaborator": False}])
    original_db, original_ai = db.copy(deep=True), ai.copy(deep=True)
    rows = app.helpers.merge_organizations(db, ai).to_dict(orient="records")
    expected = original_db.rename(columns=app.helpers.DB_RENAME).to_dict("records")[0]
    assert rows[0] == expected
    pd.testing.assert_frame_equal(db, original_db)
    pd.testing.assert_frame_equal(ai, original_ai)


@pytest.mark.parametrize("db,ai", [(None, None), (pd.DataFrame(), pd.DataFrame())])
def test_empty_inputs_keep_schema_and_return_no_records(app, db, ai):
    """Empty results remain valid and contain the updated column contract."""
    merged = app.helpers.merge_organizations(db, ai)
    assert merged.to_dict(orient="records") == []
    columns = list(merged.columns)
    assert columns[columns.index("collaborator") + 1] == "contributor"


@pytest.mark.parametrize("payload", [ai_response([]), ai_response(status=502)])
def test_empty_or_unavailable_ai_keeps_db_contributor(payload):
    """An empty/unavailable AI search cannot discard the DB's contributor flag."""
    with load_app(Mock(), payload=payload) as app:
        ai = app.helpers.get_ai_orgs("Food", "Groceries", "Chicago", "Food")
        db = pd.DataFrame([{"is_collaborator": False, "is_contributor": True}])
        rows = app.helpers.merge_organizations(db, ai).to_dict(orient="records")
        assert len(rows) == 1
        assert rows[0]["contributor"] is True


def test_database_errors_still_return_500(app, monkeypatch):
    """Missing-column compatibility must not swallow unrelated database errors."""
    monkeypatch.setattr(app.handler, "get_beneficiary_location", Mock(side_effect=RuntimeError("DB unavailable")))
    assert app.handler.lambda_handler(event(), None)["statusCode"] == 500


@pytest.mark.parametrize("request_event", [{}, {"body": "{"}])
def test_invalid_requests_keep_existing_400_response(app, request_event):
    """The contributor field does not change request validation."""
    assert app.handler.lambda_handler(request_event, None)["statusCode"] == 400
