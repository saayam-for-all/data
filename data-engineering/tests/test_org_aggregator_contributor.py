"""Regression tests for Request Details organization contributor flags (#673)."""

import importlib.util
import io
import json
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import Mock

import pandas as pd
import pytest


@pytest.fixture
def helpers(monkeypatch):
    """Load the Lambda helpers without making AWS or database connections."""
    source = Path(__file__).resolve().parents[1] / "src/saayam-org-aggregator"
    monkeypatch.syspath_prepend(str(source))
    boto3 = ModuleType("boto3")
    boto3.client = Mock()
    boto3.exceptions = Mock(Boto3Error=RuntimeError)
    psycopg2 = ModuleType("psycopg2")
    psycopg2.connect = Mock()
    parameters = Mock()
    parameters.get_parameter.return_value = json.dumps(
        {key: "unused" for key in (
            "DATABASE NAME", "HOST", "USERNAME", "PASSWORD", "PORT"
        )}
    )
    utilities = ModuleType("aws_lambda_powertools.utilities")
    utilities.parameters = parameters
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "psycopg2", psycopg2)
    monkeypatch.setitem(
        sys.modules, "aws_lambda_powertools",
        ModuleType("aws_lambda_powertools"),
    )
    monkeypatch.setitem(sys.modules, "aws_lambda_powertools.utilities", utilities)
    spec = importlib.util.spec_from_file_location(
        "org_aggregator_helpers", source / "helpers.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("values", [
    [True, False, None],
    [1, 0, float("nan")],
    pd.Series([True, False, pd.NA], dtype="boolean"),
])
def test_db_flags_are_native_nullable_booleans(helpers, values):
    """Missing/numeric pandas values must not leak into the JSON flags."""
    db = pd.DataFrame({"org_name": ["A", "B", "C"],
                       "is_collaborator": values, "is_contributor": values})
    records = helpers.merge_organizations(db, None).to_dict(orient="records")
    for column in ("collaborator", "contributor"):
        actual = [record[column] for record in records]
        assert actual == [True, False, None]
        assert all(value is None or type(value) is bool for value in actual)
        assert json.loads(json.dumps(actual, allow_nan=False)) == actual
    keys = list(records[0])
    assert keys[keys.index("collaborator") + 1] == "contributor"


def test_missing_db_column_is_null_with_ai_results(helpers):
    """An older DB schema still merges with GenAI without coercing flags."""
    db = pd.DataFrame([{"org_name": "DB", "is_collaborator": False}])
    ai = pd.DataFrame([{"organization_name": "AI", "is_collaborator": False,
                        "is_contributor": False}])
    records = helpers.merge_organizations(db, ai).to_dict(orient="records")
    assert [record["contributor"] for record in records] == [None, False]
    assert records[0]["contributor"] is None
    assert records[1]["contributor"] is False
    assert all(record["collaborator"] is False for record in records)


def test_genai_flags_are_always_false(helpers):
    """The GenAI payload cannot claim collaborator/contributor status."""
    payload = {"statusCode": 200, "body": {"organizations": [
        {"organization_name": "AI", "location": "Online",
         "is_collaborator": True, "is_contributor": True}
    ]}}
    helpers.lambda_client.invoke.return_value = {
        "Payload": io.BytesIO(json.dumps(payload).encode())
    }
    ai = helpers.get_ai_orgs("subject", "description", "city", "category")
    record = helpers.merge_organizations(None, ai).to_dict(orient="records")[0]
    assert record["collaborator"] is False
    assert record["contributor"] is False


@pytest.mark.parametrize("ai_payload", [
    {"statusCode": 200, "body": {"organizations": []}},
    {"statusCode": 502, "body": {"code": "ORG_SEARCH_UNAVAILABLE"}},
])
def test_empty_genai_preserves_db_flags(helpers, ai_payload):
    """Empty and unavailable GenAI results retain the DB contributor value."""
    helpers.lambda_client.invoke.return_value = {
        "Payload": io.BytesIO(json.dumps(ai_payload).encode())
    }
    ai = helpers.get_ai_orgs("subject", "description", "city", "category")
    db = pd.DataFrame([{"org_name": "DB", "is_collaborator": True,
                        "is_contributor": False}])
    record = helpers.merge_organizations(db, ai).to_dict(orient="records")[0]
    assert record["collaborator"] is True
    assert record["contributor"] is False


def test_empty_sources_preserve_response_columns(helpers):
    """An empty result keeps the ordered schema and serializes as an empty list."""
    merged = helpers.merge_organizations(pd.DataFrame(), None)
    assert merged.empty
    keys = list(merged)
    assert keys[keys.index("collaborator") + 1] == "contributor"
    assert merged.to_dict(orient="records") == []
