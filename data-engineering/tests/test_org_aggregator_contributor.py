"""Contributor response contract; optional integration uses a disposable schema.

Run with ORG_AGGREGATOR_TEST_DSN to include PostgreSQL tests. AWS is stubbed;
no dev credentials or external GenAI/geocoding calls are needed.
"""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import types
import uuid

import pandas as pd
import pytest


AGGREGATOR = Path(__file__).resolve().parents[1] / "src/saayam-org-aggregator"


def load_module(name, path, monkeypatch):
    """Load an isolated module while restoring imports after each test."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules(monkeypatch):
    """Load the real handler/helpers with cold-start service calls stubbed."""
    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *args, **kwargs: types.SimpleNamespace()
    boto3.exceptions = types.SimpleNamespace(Boto3Error=RuntimeError)
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    parameters = types.ModuleType("aws_lambda_powertools.utilities.parameters")
    parameters.get_parameter = lambda *args, **kwargs: json.dumps({
        "DATABASE NAME": "fixture", "HOST": "unused", "USERNAME": "unused",
        "PASSWORD": "unused", "PORT": 5432,
    })
    utilities = types.ModuleType("aws_lambda_powertools.utilities")
    utilities.parameters = parameters
    powertools = types.ModuleType("aws_lambda_powertools")
    powertools.utilities = utilities
    for name, module in {
        "aws_lambda_powertools": powertools,
        "aws_lambda_powertools.utilities": utilities,
        "aws_lambda_powertools.utilities.parameters": parameters,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    import psycopg2
    with monkeypatch.context() as cold_start:
        cold_start.setattr(psycopg2, "connect", lambda **kwargs: types.SimpleNamespace())
        distance = load_module("distance", AGGREGATOR / "distance.py", monkeypatch)
        helpers = load_module("helpers", AGGREGATOR / "helpers.py", monkeypatch)
        handler = load_module("lambda_function", AGGREGATOR / "lambda_function.py", monkeypatch)
    return helpers, handler, distance


def ai_frame(helpers, monkeypatch, records):
    """Exercise the real GenAI parser with a synthetic Lambda response."""
    payload = {"statusCode": 200, "body": {"organizations": records}}
    monkeypatch.setattr(helpers.lambda_client, "invoke", lambda **kwargs: {
        "Payload": io.BytesIO(json.dumps(payload).encode())
    }, raising=False)
    return helpers.get_ai_orgs("Food", "Need food", "Phoenix", "Food")


@pytest.mark.parametrize("values,expected", [
    ([True, False, None], [True, False, None]),
    ([1, 0, float("nan")], [True, False, None]),
    (pd.Series([True, False, pd.NA], dtype="boolean"), [True, False, None]),
])
@pytest.mark.parametrize("include_ai", [False, True])
def test_flags_are_json_booleans_or_null(modules, monkeypatch, values, expected, include_ai):
    """Mixed sources and nullable/numeric pandas columns retain JSON types."""
    helpers, _, _ = modules
    db = pd.DataFrame({"org_name": ["A", "B", "C"],
                       "is_collaborator": values, "is_contributor": values})
    ai = ai_frame(helpers, monkeypatch, [{"organization_name": "AI"}]) if include_ai else None
    records = helpers.merge_organizations(db, ai).to_dict("records")
    for field in ("collaborator", "contributor"):
        actual = [row[field] for row in records]
        assert actual == expected + ([False] if include_ai else [])
        assert all(value is None or type(value) is bool for value in actual)
        json.dumps(actual, allow_nan=False)
    for row in records:
        keys = list(row)
        assert keys[keys.index("collaborator") + 1] == "contributor"


@pytest.mark.parametrize("db,ai", [(None, None), (pd.DataFrame(), pd.DataFrame())])
def test_empty_inputs(modules, db, ai):
    """No organizations still returns an empty result with stable columns."""
    helpers, _, _ = modules
    result = helpers.merge_organizations(db, ai)
    assert result.empty
    assert list(result.columns) == helpers.ORG_COLUMNS + helpers.GEO_COLUMNS


def test_missing_db_column_and_ai_only(modules, monkeypatch):
    """Absent DB flags are null and GenAI flags are always false."""
    helpers, _, _ = modules
    ai = ai_frame(helpers, monkeypatch, [{"organization_name": "AI", "contributor": True}])
    for db in (None, pd.DataFrame({"org_name": ["DB"]})):
        records = helpers.merge_organizations(db, ai).to_dict("records")
        assert records[-1]["contributor"] is False
        assert records[-1]["collaborator"] is False
        if db is not None:
            assert records[0]["contributor"] is None
            assert records[0]["collaborator"] is None


@pytest.fixture
def postgres():
    """Create only synthetic data in a unique schema and remove it afterward."""
    dsn = os.environ.get("ORG_AGGREGATOR_TEST_DSN")
    if not dsn:
        pytest.skip("Set ORG_AGGREGATOR_TEST_DSN for PostgreSQL integration")
    import psycopg2
    from psycopg2 import sql
    connection = psycopg2.connect(dsn)
    connection.autocommit = True
    schema = "contributor_test_" + uuid.uuid4().hex
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        cursor.execute("""
            CREATE TABLE organizations (
                org_id integer, org_name text, org_type text,
                is_collaborator boolean, is_contributor boolean,
                city_name text, state_id text, org_size integer, org_rating float,
                phone text, email text, web_url text, mission text);
            CREATE TABLE org_skills (org_id integer, cat_id integer);
            CREATE TABLE help_categories (cat_id integer, cat_name text);
            INSERT INTO help_categories VALUES (1, 'Food');
            INSERT INTO organizations VALUES
                (1, 'Org A', 'NGO', true, true, 'Phoenix', 'AZ', 10, 4.5,
                 '123', 'a@example.org', 'https://example.org', 'Food'),
                (2, 'Org B', 'NGO', false, false, 'Phoenix', 'AZ', 20, 3.5,
                 '456', 'b@example.org', 'https://example.org', 'Food'),
                (3, 'Org C', 'NGO', NULL, NULL, 'Phoenix', 'AZ', 30, 2.5,
                 '789', 'c@example.org', 'https://example.org', 'Food');
            INSERT INTO org_skills VALUES (1, 1), (2, 1), (3, 1);
        """)
    try:
        yield connection, schema
    finally:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        connection.close()


@pytest.mark.parametrize("has_column", [True, False])
@pytest.mark.parametrize("city", ["Phoenix", ""])
def test_postgres_handler_response(modules, monkeypatch, postgres, has_column, city):
    """Real SELECT o.* works with both schemas and both search query paths."""
    helpers, handler, distance = modules
    connection, schema = postgres
    if not has_column:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE organizations DROP COLUMN is_contributor")
    monkeypatch.setattr(helpers, "_db_conn", connection)
    monkeypatch.setattr(helpers, "_db_name", schema)
    # Unrelated profile/representative/geocoding services are isolated here.
    monkeypatch.setattr(helpers, "get_representatives_for_orgs", lambda frame: frame)
    monkeypatch.setattr(helpers, "get_state_country_names", lambda ids: {})
    monkeypatch.setattr(handler, "get_beneficiary_location", lambda beneficiary: ("Phoenix", city))
    monkeypatch.setattr(handler, "get_req_info", lambda *args: {
        "subject": "Food", "description": "Need food", "category": "Food"})
    monkeypatch.setattr(handler, "get_beneficiary_location_candidates", lambda *args: [])
    monkeypatch.setenv("GEOCODER_PROVIDER", "none")
    ai_frame(helpers, monkeypatch, [{
        "organization_name": "AI", "org_type": "NGO", "location": "Online",
        "size": 5, "rating": 4, "contact": "000", "email": "ai@example.org",
        "web_url": "https://example.org", "mission": "Food",
    }])
    event = {"request_id": "request", "beneficiary_id": "beneficiary"}
    response = handler.lambda_handler(event, None)
    assert response["statusCode"] == 200
    records = json.loads(response["body"])
    by_name = {row["name"]: row for row in records}
    assert len(records) == 4
    expected = {"Org A": True, "Org B": False, "Org C": None}
    for name, value in expected.items():
        row = by_name[name]
        assert row["contributor"] is (value if has_column else None)
        assert row["collaborator"] is value
        assert row["location"] == "Phoenix, AZ"
        assert row["source"] == "db"
    assert by_name["AI"]["contributor"] is False
    assert by_name["AI"]["collaborator"] is False
    for row in records:
        keys = list(row)
        assert keys[keys.index("collaborator") + 1] == "contributor"
        assert row["distance"] is None
        assert row["distance_unit"] == "miles"
        assert not any(key.startswith("_geo_") for key in row)

    # Reproduce the test-branch merge shape, then compare the complete handler
    # response: every existing field (including distance) must be unchanged.
    def original_merge(db, ai):
        columns = [c for c in helpers.ORG_COLUMNS if c != "contributor"] + helpers.GEO_COLUMNS
        return pd.concat([
            db.rename(columns=helpers.DB_RENAME).reindex(columns=columns),
            ai.rename(columns=helpers.AI_RENAME).reindex(columns=columns),
        ], ignore_index=True)
    monkeypatch.setattr(handler, "merge_organizations", original_merge)
    baseline = handler.lambda_handler(event, None)
    assert baseline["statusCode"] == 200
    baseline_records = json.loads(baseline["body"])
    without_contributor = [{k: v for k, v in row.items() if k != "contributor"} for row in records]
    assert without_contributor == baseline_records
