"""Response contract checks for organization contributor status (issue #673)."""

import importlib.util
import io
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import pandas as pd


SOURCE = Path(__file__).resolve().parents[1] / "src" / "saayam-org-aggregator"


def load_helpers():
    """Import the Lambda module without contacting AWS or a database."""
    boto3 = ModuleType("boto3")
    boto3.client = Mock(return_value=Mock())
    boto3.exceptions = Mock(Boto3Error=RuntimeError)
    psycopg2 = ModuleType("psycopg2")
    psycopg2.connect = Mock(return_value=Mock())
    utilities = ModuleType("aws_lambda_powertools.utilities")
    utilities.parameters = Mock()
    utilities.parameters.get_parameter.return_value = json.dumps(
        {key: "unused" for key in (
            "DATABASE NAME", "HOST", "USERNAME", "PASSWORD", "PORT"
        )}
    )
    modules = {
        "boto3": boto3,
        "psycopg2": psycopg2,
        "aws_lambda_powertools": ModuleType("aws_lambda_powertools"),
        "aws_lambda_powertools.utilities": utilities,
    }
    spec = importlib.util.spec_from_file_location("org_helpers_under_test", SOURCE / "helpers.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules), patch.object(sys, "path", [str(SOURCE)] + sys.path):
        spec.loader.exec_module(module)
    return module


class ContributorResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helpers = load_helpers()

    def test_db_and_ai_values_are_ordered_json_booleans(self):
        db = pd.DataFrame({
            "org_name": ["DB true", "DB false", "DB unknown"],
            "is_collaborator": [True, 0, None],
            "is_contributor": [True, 0, pd.NA],
        })
        ai = pd.DataFrame({
            "organization_name": ["AI"],
            "is_collaborator": [False],
            "is_contributor": [False],
        })
        records = self.helpers.merge_organizations(db, ai).to_dict(orient="records")
        self.assertEqual([r["contributor"] for r in records], [True, False, None, False])
        self.assertEqual([r["collaborator"] for r in records], [True, False, None, False])
        for record in records:
            keys = list(record)
            self.assertEqual(keys[keys.index("collaborator") + 1], "contributor")
            for flag in ("collaborator", "contributor"):
                self.assertTrue(record[flag] is None or type(record[flag]) is bool)
        json.dumps(
            [[r["collaborator"], r["contributor"]] for r in records],
            allow_nan=False,
        )

    def test_missing_db_column_stays_null_even_with_ai_results(self):
        db = pd.DataFrame({"org_name": ["DB"], "is_collaborator": [False]})
        ai = pd.DataFrame({
            "organization_name": ["AI"],
            "is_collaborator": [False],
            "is_contributor": [False],
        })
        records = self.helpers.merge_organizations(db, ai).to_dict(orient="records")
        self.assertEqual([r["contributor"] for r in records], [None, False])
        self.assertEqual([r["collaborator"] for r in records], [False, False])
        json.dumps(
            [[r["collaborator"], r["contributor"]] for r in records],
            allow_nan=False,
        )

    def test_ai_payload_cannot_claim_contributor_status(self):
        payload = {"statusCode": 200, "body": {"organizations": [{
            "organization_name": "AI", "is_collaborator": True,
            "is_contributor": True,
        }]}}
        self.helpers.lambda_client.invoke.return_value = {
            "Payload": io.BytesIO(json.dumps(payload).encode())
        }
        ai = self.helpers.get_ai_orgs("subject", "description", "city", "category")
        record = self.helpers.merge_organizations(None, ai).to_dict(orient="records")[0]
        self.assertIs(record["collaborator"], False)
        self.assertIs(record["contributor"], False)

    def test_empty_response_retains_field_order(self):
        merged = self.helpers.merge_organizations(pd.DataFrame(), None)
        columns = list(merged)
        self.assertEqual(columns[columns.index("collaborator") + 1], "contributor")
        self.assertEqual(merged.to_dict(orient="records"), [])


if __name__ == "__main__":
    unittest.main()
