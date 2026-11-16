"""Request Details Organizations — contributor field on the org aggregator (#673)."""

import importlib.util
import io
import json
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import Mock

import pandas as pd
import pytest


SOURCE = Path(__file__).resolve().parents[1] / "src" / "saayam-org-aggregator"
SAMPLE_ORGS = (
    Path(__file__).resolve().parents[2]
    / "data-analytics"
    / "sql"
    / "organizations.csv"
)


@pytest.fixture
def helpers(monkeypatch):
    """Load helpers.py without contacting AWS or a database."""
    monkeypatch.syspath_prepend(str(SOURCE))

    boto3 = ModuleType("boto3")
    boto3.client = Mock()
    boto3.exceptions = ModuleType("boto3.exceptions")
    boto3.exceptions.Boto3Error = RuntimeError

    psycopg2 = ModuleType("psycopg2")
    psycopg2.connect = Mock(return_value=Mock())

    parameters = Mock()
    parameters.get_parameter.return_value = json.dumps(
        {
            "DATABASE NAME": "virginia_dev_saayam_rdbms",
            "HOST": "localhost",
            "USERNAME": "unused",
            "PASSWORD": "unused",
            "PORT": 5432,
        }
    )
    utilities = ModuleType("aws_lambda_powertools.utilities")
    utilities.parameters = parameters

    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "psycopg2", psycopg2)
    monkeypatch.setitem(
        sys.modules, "aws_lambda_powertools", ModuleType("aws_lambda_powertools")
    )
    monkeypatch.setitem(sys.modules, "aws_lambda_powertools.utilities", utilities)

    # Fresh module each time so FLAG_COLUMNS / rename maps always match source.
    sys.modules.pop("org_aggregator_helpers_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "org_aggregator_helpers_under_test", SOURCE / "helpers.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_json_flags(records):
    """collaborator / contributor are only True, False, or None and JSON-safe."""
    for record in records:
        keys = list(record)
        assert keys[keys.index("collaborator") + 1] == "contributor"
        for flag in ("collaborator", "contributor"):
            value = record[flag]
            # type(True) is bool — do not use `in (0, 1)` because bool subclasses int.
            assert value is None or type(value) is bool, (flag, value, type(value))
    payload = [[r["collaborator"], r["contributor"]] for r in records]
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


def test_contributor_follows_collaborator_in_schema(helpers):
    columns = list(helpers.ORG_COLUMNS)
    assert columns[columns.index("collaborator") + 1] == "contributor"


@pytest.mark.parametrize(
    "values, expected",
    [
        ([True, False, None], [True, False, None]),
        ([1, 0, float("nan")], [True, False, None]),
        (["TRUE", "FALSE", ""], [True, False, None]),
        (["yes", "no", "maybe"], [True, False, None]),
        (
            pd.Series([True, False, pd.NA], dtype="boolean"),
            [True, False, None],
        ),
    ],
)
def test_db_flags_become_native_nullable_booleans(helpers, values, expected):
    db = pd.DataFrame(
        {
            "org_name": ["A", "B", "C"],
            "is_collaborator": values,
            "is_contributor": values,
        }
    )
    records = helpers.merge_organizations(db, None).to_dict(orient="records")
    assert [r["contributor"] for r in records] == expected
    assert [r["collaborator"] for r in records] == expected
    _assert_json_flags(records)


def test_missing_is_contributor_column_is_null_for_db_orgs(helpers):
    """Older DB schemas without is_contributor still return 200-shaped rows."""
    db = pd.DataFrame(
        {
            "org_name": ["DB only"],
            "is_collaborator": [True],
        }
    )
    records = helpers.merge_organizations(db, None).to_dict(orient="records")
    assert len(records) == 1
    assert records[0]["collaborator"] is True
    assert records[0]["contributor"] is None
    _assert_json_flags(records)


def test_missing_db_column_stays_null_when_merged_with_ai(helpers):
    """Concat with AI False must not coerce the DB null into 0.0."""
    db = pd.DataFrame({"org_name": ["DB"], "is_collaborator": [False]})
    ai = pd.DataFrame(
        {
            "organization_name": ["AI"],
            "is_collaborator": [False],
            "is_contributor": [False],
        }
    )
    records = helpers.merge_organizations(db, ai).to_dict(orient="records")
    assert [r["contributor"] for r in records] == [None, False]
    assert [r["collaborator"] for r in records] == [False, False]
    assert type(records[1]["contributor"]) is bool
    _assert_json_flags(records)


def test_genai_cannot_claim_contributor_or_collaborator(helpers):
    payload = {
        "statusCode": 200,
        "body": {
            "organizations": [
                {
                    "organization_name": "AI claimed",
                    "is_collaborator": True,
                    "is_contributor": True,
                }
            ]
        },
    }
    helpers.lambda_client.invoke.return_value = {
        "Payload": io.BytesIO(json.dumps(payload).encode())
    }
    ai = helpers.get_ai_orgs("subject", "description", "city", "category")
    record = helpers.merge_organizations(None, ai).to_dict(orient="records")[0]
    assert record["collaborator"] is False
    assert record["contributor"] is False
    _assert_json_flags([record])


@pytest.mark.parametrize(
    "ai_payload",
    [
        {"statusCode": 200, "body": {"organizations": []}},
        {"statusCode": 502, "body": {"code": "ORG_SEARCH_UNAVAILABLE"}},
    ],
)
def test_empty_or_unavailable_genai_keeps_db_contributor(helpers, ai_payload):
    helpers.lambda_client.invoke.return_value = {
        "Payload": io.BytesIO(json.dumps(ai_payload).encode())
    }
    ai = helpers.get_ai_orgs("subject", "description", "city", "category")
    db = pd.DataFrame(
        {
            "org_name": ["DB"],
            "is_collaborator": [True],
            "is_contributor": [False],
        }
    )
    record = helpers.merge_organizations(db, ai).to_dict(orient="records")[0]
    assert record["collaborator"] is True
    assert record["contributor"] is False
    _assert_json_flags([record])


def test_empty_sources_keep_ordered_schema(helpers):
    merged = helpers.merge_organizations(pd.DataFrame(), None)
    assert merged.empty
    keys = list(merged)
    assert keys[keys.index("collaborator") + 1] == "contributor"
    assert merged.to_dict(orient="records") == []


def test_only_new_field_vs_baseline_columns(helpers):
    """Compared to the prior schema, the only added response column is contributor."""
    baseline = [
        "name",
        "organization_type",
        "collaborator",
        "location",
        "size",
        "rating",
        "contact",
        "email",
        "web_url",
        "mission",
        "source",
    ]
    assert helpers.ORG_COLUMNS == [
        *baseline[:3],
        "contributor",
        *baseline[3:],
    ]


def test_sample_organizations_csv_maps_is_contributor(helpers):
    """Repo sample data includes is_contributor; merge must surface it as bools."""
    assert SAMPLE_ORGS.exists(), f"missing sample file: {SAMPLE_ORGS}"
    sample = pd.read_csv(SAMPLE_ORGS)
    assert "is_contributor" in sample.columns
    db = sample.rename(columns={"org_rating": "org_rating"}).head(5).copy()
    # Mimic SELECT * shape used by get_orgs_from_db.
    records = helpers.merge_organizations(db, None).to_dict(orient="records")
    assert len(records) == 5
    for row, record in zip(db.itertuples(index=False), records):
        expected = helpers._to_json_flag(getattr(row, "is_contributor"))
        assert record["contributor"] is expected or record["contributor"] == expected
        assert type(record["contributor"]) is bool
    _assert_json_flags(records)


def test_postgres_style_rows_with_and_without_column(helpers):
    """Simulate SELECT * frames from a table that may or may not have the column."""
    with_column = pd.DataFrame(
        [
            {
                "org_name": "Helping Hands",
                "org_type": "Nonprofit",
                "is_collaborator": True,
                "is_contributor": False,
                "org_size": "Medium",
                "org_rating": 4.8,
                "phone": "555-0100",
                "email": "a@example.org",
                "web_url": "https://example.org",
                "mission": "Education",
                "city_name": "Reston",
            },
            {
                "org_name": "Food Bank",
                "org_type": "Nonprofit",
                "is_collaborator": False,
                "is_contributor": True,
                "org_size": "Large",
                "org_rating": 4.5,
                "phone": "555-0101",
                "email": "b@example.org",
                "web_url": "https://food.example.org",
                "mission": "Hunger",
                "city_name": "Fairfax",
            },
        ]
    )
    records = helpers.merge_organizations(with_column, None).to_dict(orient="records")
    assert [r["contributor"] for r in records] == [False, True]
    _assert_json_flags(records)

    without_column = with_column.drop(columns=["is_contributor"])
    records_null = helpers.merge_organizations(without_column, None).to_dict(
        orient="records"
    )
    assert [r["contributor"] for r in records_null] == [None, None]
    assert [r["collaborator"] for r in records_null] == [True, False]
    _assert_json_flags(records_null)


def test_lambda_json_body_round_trip(helpers):
    """Match lambda_function.py: to_dict → distance cleanup → json.dumps."""
    from distance import without_distance

    db = pd.DataFrame(
        {
            "org_name": ["A", "B"],
            "is_collaborator": [True, False],
            "is_contributor": [False, True],
        }
    )
    ai = pd.DataFrame(
        {
            "organization_name": ["AI"],
            "is_collaborator": [False],
            "is_contributor": [False],
        }
    )
    organizations = helpers.merge_organizations(db, ai).to_dict(orient="records")
    # Production always runs distance enrichment (or its fallback), which strips
    # internal _geo_* keys and turns remaining NaN into null before json.dumps.
    organizations = without_distance(organizations)
    body = json.dumps(organizations, allow_nan=False)
    loaded = json.loads(body)
    assert [row["contributor"] for row in loaded] == [False, True, False]
    for row in loaded:
        assert type(row["contributor"]) is bool
        assert list(row).index("contributor") == list(row).index("collaborator") + 1
        assert not any(key.startswith("_geo_") for key in row)
