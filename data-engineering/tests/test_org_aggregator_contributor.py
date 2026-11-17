"""Tests for the `contributor` field of the organization aggregator (issue #673).

Unit tests run anywhere. The PostgreSQL tests run the real aggregator SQL and
Lambda handler against an isolated, synthetic schema and are skipped unless
ORG_AGGREGATOR_TEST_PG_DSN points at a PostgreSQL database, e.g.

    ORG_AGGREGATOR_TEST_PG_DSN="host=127.0.0.1 port=5432 user=postgres dbname=postgres" \\
        pytest tests/test_org_aggregator_contributor.py
"""

import importlib
import json
import os
import re
import sys
import uuid
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd
import psycopg2
import pytest

AGGREGATOR_DIR = Path(__file__).resolve().parents[1] / "src" / "saayam-org-aggregator"
PG_DSN = os.environ.get("ORG_AGGREGATOR_TEST_PG_DSN")
MODULE_NAMES = ("distance", "helpers", "lambda_function")


@pytest.fixture(scope="module")
def agg():
    """Import the aggregator with its module-level AWS/DB connections mocked."""
    saved = {name: sys.modules.pop(name, None) for name in MODULE_NAMES}
    sys.path.insert(0, str(AGGREGATOR_DIR))
    credentials = json.dumps(
        {"DATABASE NAME": "test", "HOST": "h", "USERNAME": "u", "PASSWORD": "p", "PORT": 5432}
    )
    try:
        with mock.patch("boto3.client"), mock.patch(
            "aws_lambda_powertools.utilities.parameters.get_parameter", return_value=credentials
        ), mock.patch("psycopg2.connect"):
            helpers = importlib.import_module("helpers")
            lambda_function = importlib.import_module("lambda_function")
        yield SimpleNamespace(
            helpers=helpers,
            lf=lambda_function,
            distance=importlib.import_module("distance"),
        )
    finally:
        sys.path.remove(str(AGGREGATOR_DIR))
        for name in MODULE_NAMES:
            sys.modules.pop(name, None)
            if saved[name] is not None:
                sys.modules[name] = saved[name]


def db_frame(**flags):
    """A frame shaped like get_orgs_from_db output (raw DB column names)."""
    n = len(next(iter(flags.values())))
    frame = pd.DataFrame(
        {
            "org_id": list(range(1, n + 1)),
            "org_name": [f"DB Org {i}" for i in range(1, n + 1)],
            "org_type": ["Non-Profit"] * n,
            "org_rating": [4.5] * n,
            "org_size": ["small"] * n,
            "web_url": ["https://db.example"] * n,
            "phone": ["555-0100"] * n,
            "source": ["db"] * n,
            "location": ["Reston, VA"] * n,
        }
    )
    for column, values in flags.items():
        frame[column] = values
    return frame


def ai_frame(n=1, **extra):
    """A frame shaped like get_ai_orgs output (get_ai_orgs sets is_collaborator)."""
    frame = pd.DataFrame(
        {
            "organization_name": [f"AI Org {i}" for i in range(1, n + 1)],
            "org_type": ["Non-Profit"] * n,
            "contact": ["555-0200"] * n,
            "web_url": ["https://ai.example"] * n,
            "source": ["ai"] * n,
            "is_collaborator": [False] * n,
        }
    )
    for column, values in extra.items():
        frame[column] = values
    return frame


def merged_records(agg, db=None, ai=None):
    return agg.helpers.merge_organizations(db, ai).to_dict(orient="records")


def strict_json(records):
    """Serialize only the boolean fields, refusing NaN/Infinity.

    Other columns (email, mission, ...) can hold NaN after the merge; the
    distance step replaces those with null later, so only the flags are checked
    here. The handler tests below check the complete response body.
    """
    flags = [{k: r[k] for k in ("collaborator", "contributor")} for r in records]
    return json.dumps(flags, allow_nan=False)


# --------------------------------------------------------------------------- #
# Database organizations
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "stored, expected",
    [(True, True), (False, False), (None, None)],
    ids=["true", "false", "sql-null"],
)
def test_db_contributor_value(agg, stored, expected):
    frame = db_frame(is_contributor=[stored, stored])
    records = merged_records(agg, db=frame)

    assert [r["contributor"] for r in records] == [expected, expected]
    assert all(type(r["contributor"]) is type(expected) for r in records)


def test_db_contributor_true_false_and_null_together(agg):
    frame = db_frame(is_contributor=[True, False, None])

    records = merged_records(agg, db=frame)

    assert [r["contributor"] for r in records] == [True, False, None]
    assert json.loads(strict_json(records))[2]["contributor"] is None


def test_db_without_is_contributor_column_gives_null(agg):
    frame = db_frame(is_collaborator=[True, False])
    assert "is_contributor" not in frame.columns

    records = merged_records(agg, db=frame)

    assert [r["contributor"] for r in records] == [None, None]
    assert [r["collaborator"] for r in records] == [True, False]


# --------------------------------------------------------------------------- #
# GenAI organizations
# --------------------------------------------------------------------------- #
def test_ai_contributor_is_always_false(agg):
    records = merged_records(agg, ai=ai_frame(n=2))

    assert [r["contributor"] for r in records] == [False, False]
    assert [r["collaborator"] for r in records] == [False, False]


@pytest.mark.parametrize(
    "unexpected", [True, "true", 1, None, np.nan, "yes", ["x", "y"], {"a": 1, "b": 2}, (True, False)]
)
@pytest.mark.parametrize("key", ["contributor", "is_contributor"])
def test_unexpected_genai_contributor_is_overridden(agg, key, unexpected):
    ai = ai_frame(n=2, **{key: [unexpected, unexpected]})

    records = merged_records(agg, ai=ai)

    assert [r["contributor"] for r in records] == [False, False]
    assert strict_json(records)


def test_get_ai_orgs_end_to_end_overrides_genai_values(agg):
    payload = {
        "statusCode": 200,
        "body": json.dumps(
            {
                "organizations": [
                    {"organization_name": "A", "is_contributor": True, "contributor": True},
                    {"organization_name": "B", "is_collaborator": True},
                ]
            }
        ),
    }
    client = mock.Mock()
    client.invoke.return_value = {"Payload": BytesIO(json.dumps(payload).encode())}

    with mock.patch.object(agg.helpers, "lambda_client", client):
        ai = agg.helpers.get_ai_orgs("subj", "desc", "Reston, VA", "Education")
    records = merged_records(agg, ai=ai)

    assert [r["contributor"] for r in records] == [False, False]
    assert [r["collaborator"] for r in records] == [False, False]


# --------------------------------------------------------------------------- #
# Combined, DB-only, GenAI-only and empty results
# --------------------------------------------------------------------------- #
def test_mixed_db_and_genai_organizations(agg):
    db = db_frame(is_collaborator=[True, False, None], is_contributor=[True, None, False])

    records = merged_records(agg, db=db, ai=ai_frame(n=2))

    assert [r["source"] for r in records] == ["db", "db", "db", "ai", "ai"]
    assert [r["collaborator"] for r in records] == [True, False, None, False, False]
    assert [r["contributor"] for r in records] == [True, None, False, False, False]


def test_db_only_and_genai_only(agg):
    db_only = merged_records(agg, db=db_frame(is_contributor=[True]), ai=None)
    ai_only = merged_records(agg, db=None, ai=ai_frame())

    assert [r["contributor"] for r in db_only] == [True]
    assert [r["contributor"] for r in ai_only] == [False]


@pytest.mark.parametrize(
    "db, ai",
    [(None, None), (pd.DataFrame(), None), (None, pd.DataFrame())],
    ids=["none-none", "empty-db", "empty-ai"],
)
def test_empty_results(agg, db, ai):
    merged = agg.helpers.merge_organizations(db, ai)

    assert merged.empty
    assert list(merged.columns[:4]) == ["name", "organization_type", "collaborator", "contributor"]
    assert merged.to_dict(orient="records") == []


# --------------------------------------------------------------------------- #
# NumPy / pandas boolean and missing values
# --------------------------------------------------------------------------- #
FLAG_CASES = {
    "python-bool": ([True, False], [True, False]),
    "python-bool-null": ([True, None], [True, None]),
    "numpy-bool": ([np.True_, np.False_], [True, False]),
    "numpy-bool-array": (np.array([True, False]), [True, False]),
    "float-nan": ([True, np.nan], [True, None]),
    "all-nan": ([np.nan, np.nan], [None, None]),
    "pandas-nullable": (pd.array([True, None], dtype="boolean"), [True, None]),
    "pandas-NA": ([pd.NA, False], [None, False]),
    "bool-dtype": (pd.Series([False, True], dtype=bool), [False, True]),
}


@pytest.mark.parametrize("column", ["is_contributor", "is_collaborator"])
@pytest.mark.parametrize("values, expected", FLAG_CASES.values(), ids=FLAG_CASES.keys())
def test_flag_columns_handle_numpy_and_pandas_values(agg, column, values, expected):
    records = merged_records(agg, db=db_frame(**{column: values}), ai=ai_frame())
    field = "contributor" if column == "is_contributor" else "collaborator"

    assert [r[field] for r in records[:2]] == expected
    assert all(r[field] is None or type(r[field]) is bool for r in records)
    body = strict_json(records)
    assert not re.search(r'"(collaborator|contributor)": (NaN|[01](\.0)?[,}])', body)


def test_flag_values_are_never_numeric_or_text(agg):
    db = db_frame(is_collaborator=[1, 0, 1.0, "true", "F", "maybe"], is_contributor=[0, 1, 0.0, "f", "T", 7])

    records = merged_records(agg, db=db)

    assert [r["collaborator"] for r in records] == [True, False, True, True, False, None]
    assert [r["contributor"] for r in records] == [False, True, False, False, True, None]


# --------------------------------------------------------------------------- #
# Field order and JSON
# --------------------------------------------------------------------------- #
def test_field_order_contributor_directly_after_collaborator(agg):
    helpers = agg.helpers
    assert helpers.ORG_COLUMNS[:4] == ["name", "organization_type", "collaborator", "contributor"]

    records = merged_records(agg, db=db_frame(is_contributor=[True]), ai=ai_frame())
    for record in records:
        keys = list(record)
        assert keys.index("contributor") == keys.index("collaborator") + 1


# --------------------------------------------------------------------------- #
# Lambda handler (database and distance functions stubbed)
# --------------------------------------------------------------------------- #
@pytest.fixture
def handler(agg):
    """Return a callable running lambda_handler with stubbed data sources."""

    def run(db, ai, event=None):
        lf, dist = agg.lf, agg.distance
        event = event or {"request_id": "r1", "beneficiary_id": "b1"}
        patches = [
            mock.patch.object(lf, "get_beneficiary_location", return_value=("1 Main St", "Reston")),
            mock.patch.object(
                lf, "get_req_info", return_value={"subject": "s", "description": "d", "category": "Education"}
            ),
            mock.patch.object(lf, "get_orgs_from_db", return_value=db),
            mock.patch.object(lf, "get_ai_orgs", return_value=ai),
            mock.patch.object(lf, "get_beneficiary_location_candidates", return_value=[]),
            mock.patch.object(lf, "_get_geocoder", return_value=dist.NoGeocoder()),
        ]
        for patcher in patches:
            patcher.start()
        try:
            return lf.lambda_handler(event, None)
        finally:
            for patcher in patches:
                patcher.stop()

    return run


def db_frame_with_geo(agg, **flags):
    frame = db_frame(**flags)
    for column in agg.helpers.GEO_COLUMNS:
        frame[column] = None
    return frame


def test_handler_serializes_true_false_null_without_numeric_flags(agg, handler):
    db = db_frame_with_geo(
        agg, is_collaborator=[True, False, None], is_contributor=[True, None, False]
    )

    response = handler(db, ai_frame())

    assert response["statusCode"] == 200
    body = response["body"]
    assert "NaN" not in body
    organizations = json.loads(body)
    assert [o["contributor"] for o in organizations] == [True, None, False, False]
    assert [o["collaborator"] for o in organizations] == [True, False, None, False]
    assert all(list(o)[2:4] == ["collaborator", "contributor"] for o in organizations)


def test_handler_returns_200_when_db_has_no_contributor_column(agg, handler):
    db = db_frame_with_geo(agg, is_collaborator=[True, False])

    response = handler(db, None)

    assert response["statusCode"] == 200
    assert [o["contributor"] for o in json.loads(response["body"])] == [None, None]


def test_handler_empty_results(agg, handler):
    response = handler(db_frame_with_geo(agg, is_contributor=[]).iloc[0:0], None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == []


def test_handler_keeps_distance_fields_and_distance_sort(agg, handler):
    db = db_frame_with_geo(agg, is_collaborator=[True, False], is_contributor=[False, True])

    response = handler(db, ai_frame(), {"request_id": "r1", "beneficiary_id": "b1", "sort_by": "distance"})

    organizations = json.loads(response["body"])
    assert len(organizations) == 3
    for organization in organizations:
        assert organization["distance"] is None
        assert organization["distance_unit"] == "miles"
        assert organization["distance_method"] == "straight_line"
        assert organization["distance_status"] == "unknown_location"
        assert not any(key.startswith("_geo_") for key in organization)
    # Ties keep their original order, so contributor values stay with their rows.
    assert [o["name"] for o in organizations] == ["DB Org 1", "DB Org 2", "AI Org 1"]
    assert [o["contributor"] for o in organizations] == [False, True, False]


# --------------------------------------------------------------------------- #
# Real PostgreSQL: real SQL and the full Lambda handler on an isolated schema
# --------------------------------------------------------------------------- #
SCHEMA_SQL = """
CREATE SCHEMA {s};
CREATE TABLE {s}.countries (country_id TEXT PRIMARY KEY, country_name TEXT);
CREATE TABLE {s}.states (state_id TEXT PRIMARY KEY, state_name TEXT, state_code TEXT, country_id TEXT);
CREATE TABLE {s}.cities (city_name TEXT, state_id TEXT, lattitude DOUBLE PRECISION, longitude DOUBLE PRECISION);
CREATE TABLE {s}.help_categories (cat_id INT PRIMARY KEY, cat_name TEXT);
CREATE TABLE {s}.users (
    user_id TEXT PRIMARY KEY, first_name TEXT, last_name TEXT, addr_ln1 TEXT, addr_ln2 TEXT,
    addr_ln3 TEXT, city_name TEXT, state_id TEXT, zip_code TEXT,
    primary_phone_number TEXT, primary_email_address TEXT);
CREATE TABLE {s}.user_locations (user_id TEXT, curr_loc TEXT);
CREATE TABLE {s}.requests (
    req_id TEXT PRIMARY KEY, beneficiary_id TEXT, req_cat_id INT, req_desc TEXT, req_subj TEXT, req_loc TEXT);
CREATE TABLE {s}.organizations (
    org_id INT PRIMARY KEY, org_name TEXT, street TEXT, city_name TEXT, state_id TEXT, zip_code TEXT,
    mission TEXT, web_url TEXT, phone TEXT, email TEXT, org_type TEXT, org_size TEXT,
    org_rating NUMERIC(3, 1), is_collaborator BOOLEAN{contributor_column});
CREATE TABLE {s}.org_skills (org_id INT, cat_id INT);
CREATE TABLE {s}.user_org_map (org_id INT, user_id TEXT);

INSERT INTO {s}.countries VALUES ('US', 'UNITED_STATES');
INSERT INTO {s}.states VALUES ('VA', 'VIRGINIA', 'US-VA', 'US');
INSERT INTO {s}.cities VALUES ('Reston', 'VA', 38.9586, -77.3570), ('Fairfax', 'VA', 38.8462, -77.3064);
INSERT INTO {s}.help_categories VALUES (1, 'Education'), (2, 'Health');
INSERT INTO {s}.users VALUES
    ('b1', 'Ben', 'Eficiary', '1 Main St', NULL, NULL, 'Reston', 'VA', '20190', '555-1', 'b@x.org'),
    ('rep1', 'Rita', 'Rep', NULL, NULL, NULL, 'Reston', 'VA', '20190', '555-2', 'r@x.org');
INSERT INTO {s}.requests VALUES ('r1', 'b1', 1, 'Need tutoring', 'Tutoring', NULL);
{org_rows}
INSERT INTO {s}.org_skills VALUES (1, 1), (2, 1), (3, 1), (4, 2), (5, 1);
INSERT INTO {s}.user_org_map VALUES (2, 'rep1');
"""

ORG_INSERT = (
    "INSERT INTO {s}.organizations ({columns}) VALUES\n"
    "  ({rows});"
)
# org_id, name, city, collaborator, contributor
ORG_FIXTURES = [
    (1, "Alpha Tutors", "Reston", "TRUE", "TRUE"),
    (2, "Beta Learning", "Reston", "FALSE", "FALSE"),
    (3, "Gamma Scholars", "Reston", "NULL", "NULL"),
    (4, "Delta Clinic", "Reston", "FALSE", "TRUE"),  # other category: filtered out
    (5, "Epsilon Academy", "Fairfax", "TRUE", "TRUE"),  # other city: filtered out
]


def build_schema_sql(schema, with_contributor):
    columns = "org_id, org_name, street, city_name, state_id, zip_code, org_type, org_size, org_rating, is_collaborator"
    if with_contributor:
        columns += ", is_contributor"
    rows = []
    for org_id, name, city, collaborator, contributor in ORG_FIXTURES:
        row = f"{org_id}, '{name}', '{org_id} Oak St', '{city}', 'VA', '20190', 'Non-Profit', 'small', 4.{org_id}, {collaborator}"
        rows.append(row + (f", {contributor}" if with_contributor else ""))
    org_rows = f"INSERT INTO {schema}.organizations ({columns}) VALUES\n  (" + "),\n  (".join(rows) + ");"
    return SCHEMA_SQL.format(
        s=schema,
        contributor_column=", is_contributor BOOLEAN" if with_contributor else "",
        org_rows=org_rows,
    )


@pytest.fixture(params=[True, False], ids=["column-present", "column-missing"])
def pg_run(request, agg):
    """Run lambda_handler against a throwaway schema; yields (response, with_column)."""
    if not PG_DSN:
        pytest.skip("ORG_AGGREGATOR_TEST_PG_DSN not set")
    with_contributor = request.param
    schema = f"org_agg_test_{uuid.uuid4().hex[:10]}"
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    conn.cursor().execute(build_schema_sql(schema, with_contributor))

    genai_payload = {
        "statusCode": 200,
        "body": json.dumps(
            {
                "organizations": [
                    {"organization_name": "AI One", "address": "Reston, VA", "is_contributor": True},
                    {"organization_name": "AI Two", "contributor": True, "is_collaborator": True},
                ]
            }
        ),
    }
    client = mock.Mock()
    client.invoke.side_effect = lambda **_: {"Payload": BytesIO(json.dumps(genai_payload).encode())}

    def run(event):
        agg.lf._GEOCODER = None
        agg.distance.get_cache()._store.clear()
        with mock.patch.object(agg.helpers, "_db_conn", conn), mock.patch.object(
            agg.helpers, "_db_name", schema
        ), mock.patch.object(agg.helpers, "lambda_client", client):
            return agg.lf.lambda_handler(event, None)

    try:
        yield run, with_contributor
    finally:
        conn.cursor().execute(f"DROP SCHEMA {schema} CASCADE")
        conn.close()
        agg.lf._GEOCODER = None


@pytest.mark.filterwarnings("ignore:pandas only supports SQLAlchemy")
def test_postgres_handler_end_to_end(pg_run):
    run, with_contributor = pg_run

    response = run({"request_id": "r1", "beneficiary_id": "b1"})

    assert response["statusCode"] == 200
    body = response["body"]
    assert "NaN" not in body
    organizations = {o["name"]: o for o in json.loads(body)}

    # Category and city filtering still apply: Delta (other category) and
    # Epsilon (other city) are excluded.
    assert sorted(organizations) == ["AI One", "AI Two", "Alpha Tutors", "Beta Learning", "Gamma Scholars"]

    expected_contributor = (
        {"Alpha Tutors": True, "Beta Learning": False, "Gamma Scholars": None}
        if with_contributor
        else {"Alpha Tutors": None, "Beta Learning": None, "Gamma Scholars": None}
    )
    for name, value in expected_contributor.items():
        assert organizations[name]["contributor"] is value
    assert organizations["AI One"]["contributor"] is False
    assert organizations["AI Two"]["contributor"] is False

    assert organizations["Alpha Tutors"]["collaborator"] is True
    assert organizations["Beta Learning"]["collaborator"] is False
    assert organizations["Gamma Scholars"]["collaborator"] is None
    assert organizations["AI Two"]["collaborator"] is False

    for organization in organizations.values():
        keys = list(organization)
        assert keys.index("contributor") == keys.index("collaborator") + 1
        assert not any(key.startswith("_geo_") for key in keys)

    # Distance behavior (issue #433): city-centroid distance from the beneficiary.
    assert organizations["Alpha Tutors"]["distance"] == 0.0
    assert organizations["Alpha Tutors"]["distance_method"] == "city_centroid"
    assert organizations["Alpha Tutors"]["distance_status"] == "ok"


@pytest.mark.filterwarnings("ignore:pandas only supports SQLAlchemy")
def test_postgres_distance_sort_keeps_contributor_with_its_organization(pg_run):
    run, with_contributor = pg_run

    response = run({"request_id": "r1", "beneficiary_id": "b1", "sort_by": "distance"})

    assert response["statusCode"] == 200
    organizations = json.loads(response["body"])
    distances = [o["distance"] for o in organizations]
    known = [d for d in distances if d is not None]
    assert known == sorted(known)
    assert distances[len(known):] == [None] * (len(distances) - len(known))
    by_name = {o["name"]: o["contributor"] for o in organizations}
    assert by_name["Alpha Tutors"] is (True if with_contributor else None)
