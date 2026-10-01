"""Local unit tests for issue #273's volunteer-review Lambda."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "steward_volunteer_review_api.py"
SPEC = importlib.util.spec_from_file_location("steward_volunteer_review_api", MODULE_PATH)
assert SPEC and SPEC.loader
API = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = API
SPEC.loader.exec_module(API)


class FakeCursor:
    def __init__(self, rows=None, error=None):
        self.rows = list(rows or [])
        self.error = error
        self.executions = []
        self.closed = False

    def execute(self, query, params):
        self.executions.append((query, params))
        if self.error:
            raise self.error

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def close(self):
        self.closed = True


VIRGINIA = API.ConfiguredRegion(
    name="Virginia",
    parameter_name="/configured/outside/source/code",
    schema="virginia_dev_saayam_rdbms",
    rank=0,
)
IRELAND = API.ConfiguredRegion(
    name="Ireland",
    parameter_name="/another/configured/path",
    schema="ireland_dev_saayam_rdbms",
    rank=1,
)


class RequestTests(unittest.TestCase):
    def test_direct_payload_and_defaults(self):
        self.assertEqual(API.parse_payload({"page": 2}), {"page": 2})
        self.assertEqual(API.validate_pagination({}), (1, 5))

    def test_api_gateway_body_is_parsed(self):
        event = {"body": json.dumps({"page": 3, "page_size": 10})}
        self.assertEqual(API.parse_payload(event), {"page": 3, "page_size": 10})

    def test_invalid_json_is_rejected(self):
        with self.assertRaises(API.RequestValidationError):
            API.parse_payload({"body": "{"})

    def test_invalid_pagination_is_rejected(self):
        invalid_payloads = (
            {"page": 0},
            {"page": True},
            {"page": "1"},
            {"page_size": 0},
            {"page_size": 101},
            {"page_size": False},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(API.RequestValidationError):
                    API.validate_pagination(payload)

    def test_options_request_is_detected(self):
        self.assertTrue(API.is_options_request({"httpMethod": "OPTIONS"}))
        self.assertTrue(
            API.is_options_request(
                {"requestContext": {"http": {"method": "OPTIONS"}}}
            )
        )


class ConfigurationTests(unittest.TestCase):
    def test_regions_require_environment_supplied_parameter_paths(self):
        regions = API.resolve_regions(
            {
                "VIRGINIA_DB_SSM_PARAMETER": "/runtime/virginia/path",
                "VIRGINIA_DB_SCHEMA": "virginia_test",
            }
        )
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].parameter_name, "/runtime/virginia/path")
        self.assertEqual(regions[0].schema, "virginia_test")

    def test_no_configured_region_is_rejected(self):
        with self.assertRaises(API.ConfigurationError):
            API.resolve_regions({})

    def test_unsafe_schema_is_rejected(self):
        with self.assertRaises(API.ConfigurationError):
            API.resolve_regions(
                {
                    "VIRGINIA_DB_SSM_PARAMETER": "/runtime/path",
                    "VIRGINIA_DB_SCHEMA": "safe; DROP TABLE users",
                }
            )

    def test_ssm_json_is_parsed(self):
        class SsmClient:
            def get_parameter(self, **kwargs):
                self.kwargs = kwargs
                return {
                    "Parameter": {
                        "Value": json.dumps(
                            {
                                "HOST": "db.internal",
                                "DATABASE NAME": "saayam",
                                "USERNAME": "reader",
                                "PASSWORD": "secret",
                                "PORT": "5432",
                            }
                        )
                    }
                }

        client = SsmClient()
        config = API.load_database_config("/runtime/path", client)
        self.assertEqual(config["database"], "saayam")
        self.assertEqual(config["port"], 5432)
        self.assertEqual(
            client.kwargs,
            {"Name": "/runtime/path", "WithDecryption": True},
        )

    def test_malformed_ssm_json_returns_configuration_error(self):
        class SsmClient:
            def get_parameter(self, **kwargs):
                return {"Parameter": {"Value": "not-json"}}

        with self.assertRaises(API.ConfigurationError):
            API.load_database_config("/runtime/path", SsmClient())


class QueryTests(unittest.TestCase):
    def test_query_uses_confirmed_schema_contract(self):
        query = " ".join(API.build_review_query(VIRGINIA.schema).split())
        self.assertIn("virginia_dev_saayam_rdbms.users AS u", query)
        self.assertIn("virginia_dev_saayam_rdbms.volunteer_applications AS va", query)
        self.assertIn("ON u.user_id = va.user_id", query)
        self.assertIn("WHERE va.application_status = %s", query)
        self.assertIn("ORDER BY va.last_updated_at DESC NULLS LAST", query)
        self.assertNotIn("IN_REVIEW", query)

    def test_status_and_limit_are_bound_parameters(self):
        rows = [("SID-1", datetime(2026, 5, 12, 7, 15), 1)]
        cursor = FakeCursor(rows)
        connection = FakeConnection(cursor)

        candidates, total = API.fetch_region_candidates(
            connection,
            VIRGINIA,
            fetch_limit=5,
        )

        self.assertEqual(total, 1)
        self.assertEqual(candidates[0].user_id, "SID-1")
        self.assertEqual(cursor.executions[0][1], ("IN_REVIEW", 5))
        self.assertTrue(cursor.closed)

    def test_empty_query_result_returns_zero(self):
        cursor = FakeCursor([])
        candidates, total = API.fetch_region_candidates(
            FakeConnection(cursor),
            VIRGINIA,
            fetch_limit=5,
        )
        self.assertEqual(candidates, [])
        self.assertEqual(total, 0)
        self.assertTrue(cursor.closed)

    def test_cursor_closes_after_database_error(self):
        cursor = FakeCursor(error=RuntimeError("database unavailable"))
        with self.assertRaises(RuntimeError):
            API.fetch_region_candidates(
                FakeConnection(cursor),
                VIRGINIA,
                fetch_limit=5,
            )
        self.assertTrue(cursor.closed)


class PaginationAndMergeTests(unittest.TestCase):
    def test_regions_are_globally_sorted_and_paginated(self):
        virginia_cursor = FakeCursor(
            [
                ("SID-V1", datetime(2026, 5, 12, 7, 15), 2),
                ("SID-V2", datetime(2026, 5, 10, 7, 15), 2),
            ]
        )
        ireland_cursor = FakeCursor(
            [
                ("SID-I1", datetime(2026, 5, 13, 7, 15), 2),
                ("SID-I2", datetime(2026, 5, 11, 7, 15), 2),
            ]
        )
        connections = {
            "Virginia": FakeConnection(virginia_cursor),
            "Ireland": FakeConnection(ireland_cursor),
        }

        payload = API.process_request(
            {"page": 2, "page_size": 2},
            regions=(VIRGINIA, IRELAND),
            connection_factory=lambda region: connections[region.name],
        )

        self.assertEqual(
            [row["user_id"] for row in payload["data"]],
            ["SID-I2", "SID-V2"],
        )
        self.assertEqual(
            payload["pagination"],
            {
                "current_page": 2,
                "page_size": 2,
                "total_records": 4,
                "total_pages": 2,
            },
        )
        self.assertTrue(all(connection.closed for connection in connections.values()))

    def test_timestamp_is_formatted_as_utc_z(self):
        eastern = timezone(timedelta(hours=-4))
        candidate = API.ReviewCandidate(
            user_id="SID-1",
            updated_time=API.normalize_timestamp(
                datetime(2026, 5, 12, 3, 15, tzinfo=eastern)
            ),
            region_rank=0,
        )
        payload = API.build_success_payload(1, 5, [candidate], 1)
        self.assertEqual(payload["data"][0]["updated_time"], "2026-05-12T07:15:00Z")

    def test_empty_results_return_success_shape(self):
        payload = API.build_success_payload(1, 5, [], 0)
        self.assertEqual(payload["data"], [])
        self.assertEqual(payload["pagination"]["total_records"], 0)
        self.assertEqual(payload["pagination"]["total_pages"], 0)

    def test_out_of_range_page_returns_empty_array(self):
        candidate = API.ReviewCandidate(
            user_id="SID-1",
            updated_time=datetime(2026, 5, 12, tzinfo=timezone.utc),
            region_rank=0,
        )
        payload = API.build_success_payload(3, 5, [candidate], 1)
        self.assertEqual(payload["data"], [])
        self.assertEqual(payload["pagination"]["current_page"], 3)


class HandlerTests(unittest.TestCase):
    def test_handler_success(self):
        success_payload = {
            "data": [],
            "pagination": {
                "current_page": 1,
                "page_size": 5,
                "total_records": 0,
                "total_pages": 0,
            },
        }
        with patch.object(API, "process_request", return_value=success_payload):
            response = API.lambda_handler({"page": 1, "page_size": 5}, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"]), success_payload)

    def test_handler_validation_error_is_400(self):
        response = API.lambda_handler({"page": 0}, None)
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("positive integer", json.loads(response["body"])["error"])

    def test_handler_database_error_is_safe_500(self):
        with patch.object(API, "process_request", side_effect=RuntimeError("host secret")):
            response = API.lambda_handler({}, None)

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(
            body,
            {"error": "Unable to retrieve volunteer review requests."},
        )
        self.assertNotIn("host secret", response["body"])

    def test_options_does_not_query_database(self):
        with patch.object(API, "process_request") as process_request:
            response = API.lambda_handler({"httpMethod": "OPTIONS"}, None)
        self.assertEqual(response["statusCode"], 200)
        process_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()