
import importlib.util
import json
import sys
import types
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
AGGREGATOR_DIR = ROOT / "src" / "saayam-org-aggregator"
HELPERS_PATH = AGGREGATOR_DIR / "helpers.py"


@pytest.fixture
def helpers(monkeypatch):
    """Load helpers.py with AWS and PostgreSQL dependencies mocked."""

    monkeypatch.syspath_prepend(str(AGGREGATOR_DIR))

    # Mock boto3.
    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *args, **kwargs: object()
    boto3.exceptions = types.SimpleNamespace(
        Boto3Error=Exception
    )
    monkeypatch.setitem(sys.modules, "boto3", boto3)

    # Mock AWS Lambda Powertools Parameter Store.
    powertools = types.ModuleType("aws_lambda_powertools")
    utilities = types.ModuleType("aws_lambda_powertools.utilities")
    parameters = types.ModuleType(
        "aws_lambda_powertools.utilities.parameters"
    )

    parameters.get_parameter = lambda *args, **kwargs: json.dumps({
        "DATABASE NAME": "test_db",
        "HOST": "localhost",
        "USERNAME": "test",
        "PASSWORD": "test",
        "PORT": 5432,
    })

    utilities.parameters = parameters
    powertools.utilities = utilities

    monkeypatch.setitem(
        sys.modules, "aws_lambda_powertools", powertools
    )
    monkeypatch.setitem(
        sys.modules, "aws_lambda_powertools.utilities", utilities
    )
    monkeypatch.setitem(
        sys.modules,
        "aws_lambda_powertools.utilities.parameters",
        parameters,
    )

    # Mock PostgreSQL connection.
    psycopg2 = types.ModuleType("psycopg2")

    class FakeConnection:
        autocommit = False

    psycopg2.connect = lambda *args, **kwargs: FakeConnection()
    monkeypatch.setitem(sys.modules, "psycopg2", psycopg2)

    # Load the actual helpers.py module.
    module_name = "saayam_org_aggregator_helpers_test"
    spec = importlib.util.spec_from_file_location(
        module_name, HELPERS_PATH
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)

    return module


def test_database_contributor_values_are_preserved(helpers):
    db_orgs = pd.DataFrame({
        "org_name": ["Org A", "Org B"],
        "is_contributor": [True, False],
    })

    merged = helpers.merge_organizations(
        db_orgs, pd.DataFrame()
    )

    assert merged.loc[0, "name"] == "Org A"
    assert merged.loc[1, "name"] == "Org B"
    assert merged.loc[0, "contributor"] == True
    assert merged.loc[1, "contributor"] == False


def test_missing_database_contributor_becomes_null(helpers):
    db_orgs = pd.DataFrame({
        "org_name": ["Org A"],
    })

    merged = helpers.merge_organizations(
        db_orgs, pd.DataFrame()
    )

    assert pd.isna(merged.loc[0, "contributor"])


def test_ai_contributor_default_is_preserved(helpers):
    ai_orgs = pd.DataFrame({
        "organization_name": ["AI Org"],
        "contributor": [False],
    })

    merged = helpers.merge_organizations(
        pd.DataFrame(), ai_orgs
    )

    assert merged.loc[0, "name"] == "AI Org"
    assert merged.loc[0, "contributor"] == False


def test_empty_inputs_return_empty_dataframe(helpers):
    merged = helpers.merge_organizations(
        pd.DataFrame(), pd.DataFrame()
    )

    assert merged.empty
    assert list(merged.columns) == (
        helpers.ORG_COLUMNS + helpers.GEO_COLUMNS
    )
