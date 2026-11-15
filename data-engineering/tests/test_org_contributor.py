"""Tests for issue #673 organization contributor field."""

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd


AGGREGATOR_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "saayam-org-aggregator"
)

HELPERS_PATH = AGGREGATOR_DIR / "helpers.py"

sys.path.insert(
    0,
    str(AGGREGATOR_DIR),
)


# Stub boto3 before helpers.py is imported.
fake_boto3 = types.ModuleType("boto3")
fake_lambda_client = MagicMock()

fake_boto3.client = MagicMock(
    return_value=fake_lambda_client
)

fake_boto3.exceptions = types.SimpleNamespace(
    Boto3Error=Exception
)

sys.modules["boto3"] = fake_boto3


# Stub aws_lambda_powertools.parameters.
fake_powertools = types.ModuleType(
    "aws_lambda_powertools"
)

fake_utilities = types.ModuleType(
    "aws_lambda_powertools.utilities"
)

fake_parameters = types.ModuleType(
    "aws_lambda_powertools.utilities.parameters"
)

fake_parameters.get_parameter = MagicMock(
    return_value=json.dumps(
        {
            "DATABASE NAME": "test_db",
            "HOST": "localhost",
            "USERNAME": "test",
            "PASSWORD": "test",
            "PORT": 5432,
        }
    )
)

fake_utilities.parameters = fake_parameters
fake_powertools.utilities = fake_utilities

sys.modules[
    "aws_lambda_powertools"
] = fake_powertools

sys.modules[
    "aws_lambda_powertools.utilities"
] = fake_utilities

sys.modules[
    "aws_lambda_powertools.utilities.parameters"
] = fake_parameters


# Stub psycopg2 connection.
fake_psycopg2 = types.ModuleType(
    "psycopg2"
)

fake_connection = MagicMock()

fake_psycopg2.connect = MagicMock(
    return_value=fake_connection
)

fake_psycopg2.DatabaseError = Exception

sys.modules["psycopg2"] = fake_psycopg2


spec = importlib.util.spec_from_file_location(
    "org_helpers",
    HELPERS_PATH,
)

helpers = importlib.util.module_from_spec(
    spec
)

spec.loader.exec_module(
    helpers
)


def test_contributor_follows_collaborator_in_response_columns():
    collaborator_index = (
        helpers.ORG_COLUMNS.index(
            "collaborator"
        )
    )

    contributor_index = (
        helpers.ORG_COLUMNS.index(
            "contributor"
        )
    )

    assert contributor_index == (
        collaborator_index + 1
    )


def test_db_contributor_true_and_false_are_preserved():
    db_orgs = pd.DataFrame(
        [
            {
                "org_name": "Org One",
                "org_type": "Non-Profit",
                "is_collaborator": True,
                "is_contributor": True,
            },
            {
                "org_name": "Org Two",
                "org_type": "Non-Profit",
                "is_collaborator": False,
                "is_contributor": False,
            },
        ]
    )

    result = helpers.merge_organizations(
        db_orgs,
        pd.DataFrame(),
    )

    assert result.iloc[0][
        "contributor"
    ] is True

    assert result.iloc[1][
        "contributor"
    ] is False


def test_missing_db_contributor_column_returns_null():
    db_orgs = pd.DataFrame(
        [
            {
                "org_name": "Legacy Org",
                "org_type": "Non-Profit",
                "is_collaborator": True,
            }
        ]
    )

    result = helpers.merge_organizations(
        db_orgs,
        pd.DataFrame(),
    )

    assert result.iloc[0][
        "contributor"
    ] is None


def test_numeric_boolean_values_are_normalized():
    db_orgs = pd.DataFrame(
        [
            {
                "org_name": "Zero Org",
                "is_collaborator": 0,
                "is_contributor": 0.0,
            },
            {
                "org_name": "One Org",
                "is_collaborator": 1,
                "is_contributor": 1.0,
            },
        ]
    )

    result = helpers.merge_organizations(
        db_orgs,
        pd.DataFrame(),
    )

    assert result.iloc[0][
        "collaborator"
    ] is False

    assert result.iloc[0][
        "contributor"
    ] is False

    assert result.iloc[1][
        "collaborator"
    ] is True

    assert result.iloc[1][
        "contributor"
    ] is True


def test_nan_becomes_null():
    db_orgs = pd.DataFrame(
        [
            {
                "org_name": "Unknown Org",
                "is_collaborator": float("nan"),
                "is_contributor": float("nan"),
            }
        ]
    )

    result = helpers.merge_organizations(
        db_orgs,
        pd.DataFrame(),
    )

    assert result.iloc[0][
        "collaborator"
    ] is None

    assert result.iloc[0][
        "contributor"
    ] is None


def test_ai_orgs_receive_contributor_false(
    monkeypatch,
):
    payload = {
        "statusCode": 200,
        "body": json.dumps(
            {
                "organizations": [
                    {
                        "organization_name": (
                            "AI Organization"
                        ),
                        "org_type": (
                            "Non-Profit"
                        ),
                    }
                ]
            }
        ),
    }

    fake_payload = MagicMock()
    fake_payload.read.return_value = (
        json.dumps(payload)
    )

    fake_response = {
        "Payload": fake_payload
    }

    monkeypatch.setattr(
        helpers.lambda_client,
        "invoke",
        MagicMock(
            return_value=fake_response
        ),
    )

    result = helpers.get_ai_orgs(
        "Need help",
        "Description",
        "Syracuse",
        "Food",
    )

    # Raw pandas DataFrame may represent False as numpy.False_.
    assert bool(
        result.iloc[0]["is_contributor"]
    ) is False

    merged = helpers.merge_organizations(
        pd.DataFrame(),
        result,
    )

    # Final API-normalized field must be built-in bool False.
    assert merged.iloc[0][
        "contributor"
    ] is False


def test_response_contains_only_boolean_or_null_values():
    db_orgs = pd.DataFrame(
        [
            {
                "org_name": "False Org",
                "is_collaborator": 0.0,
                "is_contributor": 0.0,
            },
            {
                "org_name": "Null Org",
                "is_collaborator": float(
                    "nan"
                ),
                "is_contributor": float(
                    "nan"
                ),
            },
        ]
    )

    result = helpers.merge_organizations(
        db_orgs,
        pd.DataFrame(),
    )

    for value in result[
        "collaborator"
    ].tolist():
        assert (
            value is True
            or value is False
            or value is None
        )

    for value in result[
        "contributor"
    ].tolist():
        assert (
            value is True
            or value is False
            or value is None
        )