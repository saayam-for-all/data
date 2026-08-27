"""Tests for the Steward Dashboard volunteer review Lambda API."""

from __future__ import annotations

import builtins
import importlib.util
import json
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "steward_volunteer_review_api.py"
MODULE_NAME = "issue_273_steward_volunteer_review_api"
MODULE_SPEC = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("Unable to load the Lambda module for testing.")

MODULE = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_NAME] = MODULE
MODULE_SPEC.loader.exec_module(MODULE)


class FakeSsmClient:
    """Minimal SSM test double that records parameter requests."""

    def __init__(self, value: str) -> None:
        self.value = value
        self.calls: list[dict[str, object]] = []

    def get_parameter(self, **kwargs: object) -> dict[str, object]:
        """Return one configured SecureString-shaped response."""

        self.calls.append(dict(kwargs))
        return {"Parameter": {"Value": self.value}}


class FakeCursor:
    """Tuple-cursor test double for query and cleanup assertions."""

    def __init__(
        self,
        rows: list[tuple[object, ...]] | None = None,
        execute_error: Exception | None = None,
    ) -> None:
        self.rows = list(rows or [])
        self.execute_error = execute_error
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.closed = False

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        """Record an execution or raise the configured error."""

        self.executions.append((query, params))
        if self.execute_error is not None:
            raise self.execute_error

    def fetchall(self) -> list[tuple[object, ...]]:
        """Return configured tuple rows."""

        return list(self.rows)

    def close(self) -> None:
        """Record cursor closure."""

        self.closed = True


class FakeConnection:
    """Connection test double for read-only and cleanup assertions."""

    def __init__(
        self,
        cursor: FakeCursor | None = None,
        set_session_error: Exception | None = None,
    ) -> None:
        self.test_cursor = cursor or FakeCursor()
        self.set_session_error = set_session_error
        self.session_calls: list[dict[str, object]] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        """Return the configured cursor."""

        return self.test_cursor

    def set_session(self, **kwargs: object) -> None:
        """Record read-only session configuration."""

        self.session_calls.append(dict(kwargs))
        if self.set_session_error is not None:
            raise self.set_session_error

    def close(self) -> None:
        """Record connection closure."""

        self.closed = True


def decode_response(response: dict[str, object]) -> dict[str, object]:
    """Decode a Lambda proxy response body for assertions."""

    return json.loads(str(response["body"]))


class UnitImportTests(unittest.TestCase):
    """Verify the module has no import-time AWS or database dependency."""

    def test_import_does_not_require_boto3_or_psycopg2(self) -> None:
        """Loading the module must not import cloud or database clients."""

        guarded_name = f"{MODULE_NAME}_{uuid.uuid4().hex}"
        guarded_spec = importlib.util.spec_from_file_location(guarded_name, MODULE_PATH)
        self.assertIsNotNone(guarded_spec)
        self.assertIsNotNone(guarded_spec.loader)
        guarded_module = importlib.util.module_from_spec(guarded_spec)
        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object) -> object:
            if name.split(".", maxsplit=1)[0] in {"boto3", "psycopg2"}:
                raise AssertionError(f"Unexpected import-time dependency: {name}")
            return original_import(name, *args, **kwargs)

        sys.modules[guarded_name] = guarded_module
        try:
            with mock.patch("builtins.__import__", side_effect=guarded_import):
                guarded_spec.loader.exec_module(guarded_module)
        finally:
            sys.modules.pop(guarded_name, None)


class UnitEventParsingTests(unittest.TestCase):
    """Test direct invocation and API Gateway request parsing."""

    def test_none_event_uses_empty_payload(self) -> None:
        self.assertEqual(MODULE.parse_event_body(None), {})

    def test_direct_event_is_returned_as_payload(self) -> None:
        self.assertEqual(
            MODULE.parse_event_body({"page": 2, "page_size": 10}),
            {"page": 2, "page_size": 10},
        )

    def test_json_string_body_is_parsed(self) -> None:
        self.assertEqual(
            MODULE.parse_event_body({"body": '{"page": 3, "page_size": 4}'}),
            {"page": 3, "page_size": 4},
        )

    def test_mapping_body_is_copied(self) -> None:
        body = {"page": 4}
        parsed = MODULE.parse_event_body({"body": body})
        self.assertEqual(parsed, body)
        self.assertIsNot(parsed, body)

    def test_empty_body_uses_defaults_payload(self) -> None:
        self.assertEqual(MODULE.parse_event_body({"body": ""}), {})
        self.assertEqual(MODULE.parse_event_body({"body": None}), {})

    def test_malformed_json_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "invalid JSON",
        ):
            MODULE.parse_event_body({"body": "{"})

    def test_json_array_body_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "JSON object",
        ):
            MODULE.parse_event_body({"body": "[]"})

    def test_non_string_non_mapping_body_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "JSON object",
        ):
            MODULE.parse_event_body({"body": [1, 2]})

    def test_non_mapping_event_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "JSON object",
        ):
            MODULE.parse_event_body([1, 2])

    def test_options_detection_supports_api_gateway_v1_and_v2(self) -> None:
        self.assertTrue(MODULE.is_options_request({"httpMethod": "OPTIONS"}))
        self.assertTrue(
            MODULE.is_options_request(
                {"requestContext": {"http": {"method": "options"}}}
            )
        )
        self.assertFalse(MODULE.is_options_request({"httpMethod": "POST"}))


class UnitPaginationValidationTests(unittest.TestCase):
    """Test strict and bounded pagination validation."""

    def test_defaults_match_issue_contract(self) -> None:
        self.assertEqual(MODULE.validate_pagination({}), (1, 5))

    def test_valid_boundary_values_are_accepted(self) -> None:
        self.assertEqual(
            MODULE.validate_pagination({"page": 10, "page_size": 100}),
            (10, 100),
        )

    def test_boolean_page_is_rejected(self) -> None:
        with self.assertRaises(MODULE.RequestValidationError):
            MODULE.validate_pagination({"page": True})

    def test_string_page_is_rejected(self) -> None:
        with self.assertRaises(MODULE.RequestValidationError):
            MODULE.validate_pagination({"page": "1"})

    def test_zero_page_is_rejected(self) -> None:
        with self.assertRaises(MODULE.RequestValidationError):
            MODULE.validate_pagination({"page": 0})

    def test_negative_page_is_rejected(self) -> None:
        with self.assertRaises(MODULE.RequestValidationError):
            MODULE.validate_pagination({"page": -1})

    def test_boolean_page_size_is_rejected(self) -> None:
        with self.assertRaises(MODULE.RequestValidationError):
            MODULE.validate_pagination({"page_size": False})

    def test_string_page_size_is_rejected(self) -> None:
        with self.assertRaises(MODULE.RequestValidationError):
            MODULE.validate_pagination({"page_size": "5"})

    def test_zero_page_size_is_rejected(self) -> None:
        with self.assertRaises(MODULE.RequestValidationError):
            MODULE.validate_pagination({"page_size": 0})

    def test_page_size_over_maximum_is_rejected(self) -> None:
        with self.assertRaises(MODULE.RequestValidationError):
            MODULE.validate_pagination({"page_size": 101})

    def test_result_window_over_maximum_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "must not exceed 1000",
        ):
            MODULE.validate_pagination({"page": 11, "page_size": 100})


class UnitConfigurationTests(unittest.TestCase):
    """Test SSM parsing and bounded read-only connections."""

    def setUp(self) -> None:
        self.region = MODULE.REGIONS[0]
        self.parameter_environment = {
            self.region.parameter_environment_variable: "/test/database/config"
        }

    def test_uppercase_ssm_json_is_parsed(self) -> None:
        client = FakeSsmClient(
            json.dumps(
                {
                    "HOST": "db.internal",
                    "PORT": "5432",
                    "DATABASE NAME": "saayam",
                    "USERNAME": "analytics",
                    "PASSWORD": "test-password",
                }
            )
        )
        with mock.patch.dict(os.environ, self.parameter_environment, clear=True):
            config = MODULE.get_database_config(self.region, client)

        self.assertEqual(
            config,
            {
                "host": "db.internal",
                "port": 5432,
                "dbname": "saayam",
                "user": "analytics",
                "password": "test-password",
            },
        )
        self.assertEqual(
            client.calls,
            [{"Name": "/test/database/config", "WithDecryption": True}],
        )

    def test_lowercase_ssm_aliases_are_parsed(self) -> None:
        client = FakeSsmClient(
            json.dumps(
                {
                    "host": "localhost",
                    "port": 5432,
                    "dbname": "saayam",
                    "user": "reader",
                    "password": "test-password",
                }
            )
        )
        with mock.patch.dict(os.environ, self.parameter_environment, clear=True):
            config = MODULE.get_database_config(self.region, client)
        self.assertEqual(config["dbname"], "saayam")
        self.assertEqual(config["port"], 5432)

    def test_missing_parameter_environment_variable_fails_closed(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(MODULE.ConfigurationError, "missing"):
                MODULE.get_database_config(self.region, FakeSsmClient("{}"))

    def test_malformed_ssm_json_is_rejected(self) -> None:
        with mock.patch.dict(os.environ, self.parameter_environment, clear=True):
            with self.assertRaisesRegex(MODULE.ConfigurationError, "malformed"):
                MODULE.get_database_config(self.region, FakeSsmClient("{"))

    def test_non_mapping_ssm_json_is_rejected(self) -> None:
        with mock.patch.dict(os.environ, self.parameter_environment, clear=True):
            with self.assertRaisesRegex(MODULE.ConfigurationError, "malformed"):
                MODULE.get_database_config(self.region, FakeSsmClient("[]"))

    def test_incomplete_ssm_json_is_rejected(self) -> None:
        with mock.patch.dict(os.environ, self.parameter_environment, clear=True):
            with self.assertRaisesRegex(MODULE.ConfigurationError, "incomplete"):
                MODULE.get_database_config(
                    self.region,
                    FakeSsmClient(json.dumps({"HOST": "db.internal"})),
                )

    def test_invalid_database_port_is_rejected(self) -> None:
        payload = {
            "HOST": "db.internal",
            "PORT": "invalid",
            "DATABASE NAME": "saayam",
            "USERNAME": "reader",
            "PASSWORD": "test-password",
        }
        with mock.patch.dict(os.environ, self.parameter_environment, clear=True):
            with self.assertRaisesRegex(MODULE.ConfigurationError, "malformed"):
                MODULE.get_database_config(
                    self.region,
                    FakeSsmClient(json.dumps(payload)),
                )

    def test_out_of_range_database_port_is_rejected(self) -> None:
        payload = {
            "HOST": "db.internal",
            "PORT": 70_000,
            "DATABASE NAME": "saayam",
            "USERNAME": "reader",
            "PASSWORD": "test-password",
        }
        with mock.patch.dict(os.environ, self.parameter_environment, clear=True):
            with self.assertRaisesRegex(MODULE.ConfigurationError, "malformed"):
                MODULE.get_database_config(
                    self.region,
                    FakeSsmClient(json.dumps(payload)),
                )

    def test_connection_is_read_only_and_has_timeouts(self) -> None:
        connection = FakeConnection()
        connect = mock.Mock(return_value=connection)
        fake_psycopg2 = SimpleNamespace(connect=connect)
        database_config = {
            "host": "db.internal",
            "port": 5432,
            "dbname": "saayam",
            "user": "reader",
            "password": "test-password",
        }

        with mock.patch.dict(sys.modules, {"psycopg2": fake_psycopg2}):
            with mock.patch.object(
                MODULE,
                "get_database_config",
                return_value=database_config,
            ):
                returned = MODULE.open_database_connection(self.region, object())

        self.assertIs(returned, connection)
        connect.assert_called_once_with(
            **database_config,
            sslmode="require",
            connect_timeout=5,
            options="-c statement_timeout=10000",
        )
        self.assertEqual(
            connection.session_calls,
            [{"readonly": True, "autocommit": True}],
        )

    def test_connection_closes_if_read_only_setup_fails(self) -> None:
        connection = FakeConnection(set_session_error=RuntimeError("failed"))
        fake_psycopg2 = SimpleNamespace(connect=mock.Mock(return_value=connection))
        with mock.patch.dict(sys.modules, {"psycopg2": fake_psycopg2}):
            with mock.patch.object(
                MODULE,
                "get_database_config",
                return_value={
                    "host": "db.internal",
                    "port": 5432,
                    "dbname": "saayam",
                    "user": "reader",
                    "password": "test-password",
                },
            ):
                with self.assertRaises(RuntimeError):
                    MODULE.open_database_connection(self.region, object())
        self.assertTrue(connection.closed)


class UnitQueryTests(unittest.TestCase):
    """Test canonical, parameterized SQL and cursor behavior."""

    def test_query_uses_canonical_tables_filter_and_order(self) -> None:
        query = MODULE.build_review_query("virginia_dev_saayam_rdbms")
        normalized = " ".join(query.split())
        self.assertIn("virginia_dev_saayam_rdbms.users AS u", normalized)
        self.assertIn(
            "virginia_dev_saayam_rdbms.volunteer_applications AS va",
            normalized,
        )
        self.assertIn("u.user_id = va.user_id", normalized)
        self.assertIn("va.application_status = %s", normalized)
        self.assertIn("COUNT(*) OVER () AS total_records", normalized)
        self.assertIn("last_updated_at DESC NULLS LAST", normalized)
        self.assertIn("u.user_id ASC", normalized)
        self.assertIn("LIMIT %s", normalized)
        self.assertNotIn("OFFSET", normalized)
        self.assertNotIn("IN_REVIEW", normalized)
        self.assertNotIn("volunteer_details", normalized)

    def test_invalid_schema_identifier_is_rejected(self) -> None:
        with self.assertRaisesRegex(MODULE.ConfigurationError, "schema"):
            MODULE.build_review_query("public; DROP TABLE users")

    def test_fetch_binds_status_and_limit_and_closes_cursor(self) -> None:
        timestamp = datetime(2026, 5, 12, 7, 15)
        cursor = FakeCursor([("SID-00-000-000-001", timestamp, 7)])
        candidates, total = MODULE.fetch_region_candidates(
            FakeConnection(cursor),
            MODULE.REGIONS[0],
            25,
        )

        self.assertEqual(total, 7)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].user_id, "SID-00-000-000-001")
        self.assertEqual(candidates[0].updated_time.tzinfo, timezone.utc)
        self.assertEqual(
            cursor.executions[0][1],
            ("IN_REVIEW", 25),
        )
        self.assertTrue(cursor.closed)

    def test_empty_region_returns_zero_total(self) -> None:
        cursor = FakeCursor([])
        candidates, total = MODULE.fetch_region_candidates(
            FakeConnection(cursor),
            MODULE.REGIONS[0],
            5,
        )
        self.assertEqual(candidates, [])
        self.assertEqual(total, 0)
        self.assertTrue(cursor.closed)

    def test_query_error_still_closes_cursor(self) -> None:
        cursor = FakeCursor(execute_error=RuntimeError("query failed"))
        with self.assertRaises(RuntimeError):
            MODULE.fetch_region_candidates(
                FakeConnection(cursor),
                MODULE.REGIONS[0],
                5,
            )
        self.assertTrue(cursor.closed)

    def test_invalid_database_timestamp_is_rejected_after_cleanup(self) -> None:
        cursor = FakeCursor([("SID-00-000-000-001", "not-a-timestamp", 1)])
        with self.assertRaisesRegex(ValueError, "timestamp"):
            MODULE.fetch_region_candidates(
                FakeConnection(cursor),
                MODULE.REGIONS[0],
                5,
            )
        self.assertTrue(cursor.closed)


class UnitMergeAndPaginationTests(unittest.TestCase):
    """Test regional cleanup, deterministic merge, and response pagination."""

    def test_query_regions_closes_connections_and_sums_totals(self) -> None:
        virginia = FakeConnection(
            FakeCursor([("SID-00-000-000-001", datetime(2026, 5, 12), 3)])
        )
        ireland = FakeConnection(
            FakeCursor([("SID-EU-000-000-001", datetime(2026, 5, 13), 2)])
        )
        connections = {"Virginia": virginia, "Ireland": ireland}

        candidates, total = MODULE.query_regions(
            5,
            lambda region: connections[region.name],
        )

        self.assertEqual(total, 5)
        self.assertEqual(
            [candidate.user_id for candidate in candidates],
            ["SID-EU-000-000-001", "SID-00-000-000-001"],
        )
        self.assertTrue(virginia.closed)
        self.assertTrue(ireland.closed)

    def test_partial_region_failure_closes_prior_connection(self) -> None:
        virginia = FakeConnection(FakeCursor([]))

        def factory(region: object) -> FakeConnection:
            if region.name == "Virginia":
                return virginia
            raise RuntimeError("Ireland unavailable")

        with self.assertRaises(RuntimeError):
            MODULE.query_regions(5, factory)
        self.assertTrue(virginia.closed)

    def test_region_query_failure_closes_cursor_and_connection(self) -> None:
        cursor = FakeCursor(execute_error=RuntimeError("query failed"))
        connection = FakeConnection(cursor)
        with self.assertRaises(RuntimeError):
            MODULE.query_regions(5, lambda region: connection)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_global_order_is_timestamp_user_and_region_deterministic(self) -> None:
        timestamp = datetime(2026, 5, 12, tzinfo=timezone.utc)
        candidates = [
            MODULE.ReviewCandidate("SID-B", timestamp, 0),
            MODULE.ReviewCandidate("SID-A", None, 0),
            MODULE.ReviewCandidate("SID-A", timestamp, 1),
            MODULE.ReviewCandidate("SID-A", timestamp, 0),
            MODULE.ReviewCandidate(
                "SID-C",
                timestamp + timedelta(days=1),
                1,
            ),
        ]
        candidates.sort(key=MODULE._candidate_sort_key)
        self.assertEqual(
            [(candidate.user_id, candidate.region_rank) for candidate in candidates],
            [("SID-C", 1), ("SID-A", 0), ("SID-A", 1), ("SID-B", 0), ("SID-A", 0)],
        )

    def test_aware_timestamp_is_converted_to_utc(self) -> None:
        eastern = timezone(timedelta(hours=-4))
        value = datetime(2026, 5, 12, 3, 15, tzinfo=eastern)
        normalized = MODULE.normalize_datetime(value)
        self.assertEqual(normalized, datetime(2026, 5, 12, 7, 15, tzinfo=timezone.utc))
        self.assertEqual(MODULE.format_timestamp(normalized), "2026-05-12T07:15:00Z")

    def test_null_timestamp_is_preserved(self) -> None:
        self.assertIsNone(MODULE.normalize_datetime(None))
        self.assertIsNone(MODULE.format_timestamp(None))

    def test_page_two_payload_has_exact_contract(self) -> None:
        candidates = [
            MODULE.ReviewCandidate(
                f"SID-{index}",
                datetime(2026, 5, 12 - index, tzinfo=timezone.utc),
                0,
            )
            for index in range(5)
        ]
        payload = MODULE.build_success_payload(2, 2, candidates, 5)
        self.assertEqual(
            payload,
            {
                "data": [
                    {
                        "user_id": "SID-2",
                        "updated_time": "2026-05-10T00:00:00Z",
                        "volunteer_review": "Review",
                    },
                    {
                        "user_id": "SID-3",
                        "updated_time": "2026-05-09T00:00:00Z",
                        "volunteer_review": "Review",
                    },
                ],
                "pagination": {
                    "current_page": 2,
                    "page_size": 2,
                    "total_records": 5,
                    "total_pages": 3,
                },
            },
        )

    def test_out_of_range_page_returns_empty_data(self) -> None:
        payload = MODULE.build_success_payload(3, 5, [], 2)
        self.assertEqual(payload["data"], [])
        self.assertEqual(payload["pagination"]["total_pages"], 1)

    def test_empty_queue_has_zero_pages(self) -> None:
        payload = MODULE.build_success_payload(1, 5, [], 0)
        self.assertEqual(payload["data"], [])
        self.assertEqual(payload["pagination"]["total_records"], 0)
        self.assertEqual(payload["pagination"]["total_pages"], 0)

    def test_process_request_uses_bounded_candidate_window(self) -> None:
        with mock.patch.object(
            MODULE,
            "query_regions",
            return_value=([], 0),
        ) as query_regions:
            payload = MODULE.process_request({"page": 4, "page_size": 25})
        query_regions.assert_called_once_with(100, None)
        self.assertEqual(payload["pagination"]["current_page"], 4)


class UnitHandlerTests(unittest.TestCase):
    """Test public Lambda proxy responses and safe failure behavior."""

    def test_success_response_is_json_encoded_with_cors(self) -> None:
        success_payload = {
            "data": [],
            "pagination": {
                "current_page": 1,
                "page_size": 5,
                "total_records": 0,
                "total_pages": 0,
            },
        }
        with mock.patch.object(
            MODULE,
            "process_request",
            return_value=success_payload,
        ) as process_request:
            response = MODULE.lambda_handler({"body": '{"page": 1}'}, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(decode_response(response), success_payload)
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        self.assertEqual(response["headers"]["Access-Control-Allow-Origin"], "*")
        process_request.assert_called_once_with({"page": 1})

    def test_invalid_json_returns_400_without_querying(self) -> None:
        with mock.patch.object(MODULE, "process_request") as process_request:
            response = MODULE.lambda_handler({"body": "{"}, None)
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("invalid JSON", decode_response(response)["error"])
        process_request.assert_not_called()

    def test_options_preflight_returns_without_cloud_access(self) -> None:
        with mock.patch.object(MODULE, "process_request") as process_request:
            response = MODULE.lambda_handler(
                {"httpMethod": "OPTIONS", "body": "{"},
                None,
            )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(decode_response(response), {})
        process_request.assert_not_called()

    def test_invalid_pagination_returns_400_without_cloud_access(self) -> None:
        with mock.patch.object(MODULE, "create_ssm_client") as create_ssm_client:
            response = MODULE.lambda_handler({"page": 0}, None)
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("positive integer", decode_response(response)["error"])
        create_ssm_client.assert_not_called()

    def test_internal_error_returns_generic_500(self) -> None:
        with mock.patch.object(
            MODULE,
            "process_request",
            side_effect=RuntimeError("secret-host.internal"),
        ):
            response = MODULE.lambda_handler({}, None)
        decoded = decode_response(response)
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(
            decoded,
            {"error": "Unable to retrieve volunteer review requests."},
        )
        self.assertNotIn("secret-host", str(response))

    def test_missing_regional_configuration_returns_500_not_partial_200(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(MODULE, "create_ssm_client", return_value=object()):
                response = MODULE.lambda_handler({}, None)
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(
            decode_response(response),
            {"error": "Unable to retrieve volunteer review requests."},
        )


RUN_POSTGRES_INTEGRATION = os.environ.get("RUN_POSTGRES_INTEGRATION") == "1"


@unittest.skipUnless(
    RUN_POSTGRES_INTEGRATION,
    "Set RUN_POSTGRES_INTEGRATION=1 to run real PostgreSQL tests.",
)
class PostgresIntegrationAndAcceptanceTests(unittest.TestCase):
    """Exercise actual PostgreSQL SQL and handler-level local acceptance."""

    @classmethod
    def setUpClass(cls) -> None:
        """Connect to PostgreSQL and create isolated regional schemas."""

        super().setUpClass()
        database_url = os.environ.get("TEST_DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "TEST_DATABASE_URL is required when PostgreSQL integration is enabled."
            )
        parsed_url = urlparse(database_url)
        if (
            parsed_url.scheme not in {"postgres", "postgresql"}
            or parsed_url.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed_url.port != 55_432
            or parsed_url.path != "/saayam_issue273"
        ):
            raise RuntimeError(
                "PostgreSQL integration requires the disposable local "
                "saayam_issue273 database on port 55432."
            )

        import psycopg2
        from psycopg2 import sql

        cls.psycopg2 = psycopg2
        cls.sql = sql
        cls.database_url = database_url
        suffix = uuid.uuid4().hex[:12]
        cls.virginia_schema = f"issue273_virginia_{suffix}"
        cls.ireland_schema = f"issue273_ireland_{suffix}"
        cls.test_regions = (
            MODULE.RegionConfig("Virginia", cls.virginia_schema, "UNUSED", 0),
            MODULE.RegionConfig("Ireland", cls.ireland_schema, "UNUSED", 1),
        )

        cls.admin_connection = psycopg2.connect(database_url)
        cls.admin_connection.autocommit = True
        created_schemas: list[str] = []
        try:
            with cls.admin_connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('server_version')")
                version = cursor.fetchone()[0]
                if not version:
                    raise RuntimeError(
                        "PostgreSQL server version was not available."
                    )
                for schema in (cls.virginia_schema, cls.ireland_schema):
                    cursor.execute(
                        sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
                    )
                    created_schemas.append(schema)
                    cursor.execute(
                        sql.SQL(
                            "CREATE TYPE {}.app_status_type AS ENUM "
                            "('STARTED', 'IN_REVIEW', 'ACCEPTED', 'REJECTED')"
                        ).format(sql.Identifier(schema))
                    )
                    cursor.execute(
                        sql.SQL(
                            "CREATE TABLE {}.users ("
                            "user_id VARCHAR(50) PRIMARY KEY"
                            ")"
                        ).format(sql.Identifier(schema))
                    )
                    cursor.execute(
                        sql.SQL(
                            "CREATE TABLE {}.volunteer_applications ("
                            "user_id VARCHAR(50) PRIMARY KEY REFERENCES "
                            "{}.users(user_id), "
                            "application_status {}.app_status_type NOT NULL, "
                            "last_updated_at TIMESTAMP NULL"
                            ")"
                        ).format(
                            sql.Identifier(schema),
                            sql.Identifier(schema),
                            sql.Identifier(schema),
                        )
                    )
        except Exception:
            with cls.admin_connection.cursor() as cursor:
                for schema in created_schemas:
                    cursor.execute(
                        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                            sql.Identifier(schema)
                        )
                    )
            cls.admin_connection.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        """Drop all isolated test schemas and close the admin connection."""

        if hasattr(cls, "admin_connection"):
            try:
                with cls.admin_connection.cursor() as cursor:
                    for schema in (cls.virginia_schema, cls.ireland_schema):
                        cursor.execute(
                            cls.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                                cls.sql.Identifier(schema)
                            )
                        )
            finally:
                cls.admin_connection.close()
        super().tearDownClass()

    def setUp(self) -> None:
        """Reset both regional tables before every PostgreSQL test."""

        with self.admin_connection.cursor() as cursor:
            for schema in (self.virginia_schema, self.ireland_schema):
                cursor.execute(
                    self.sql.SQL(
                        "TRUNCATE TABLE {}.volunteer_applications, {}.users"
                    ).format(
                        self.sql.Identifier(schema),
                        self.sql.Identifier(schema),
                    )
                )

    def connect(self) -> object:
        """Return a fresh production-configured read-only connection."""

        connection = self.psycopg2.connect(
            self.database_url,
            options="-c statement_timeout=10000",
        )
        MODULE.configure_database_connection(connection)
        return connection

    def insert_application(
        self,
        schema: str,
        user_id: str,
        status: str,
        updated_time: datetime | None,
    ) -> None:
        """Insert one canonical user/application pair into a test region."""

        with self.admin_connection.cursor() as cursor:
            cursor.execute(
                self.sql.SQL("INSERT INTO {}.users (user_id) VALUES (%s)").format(
                    self.sql.Identifier(schema)
                ),
                (user_id,),
            )
            cursor.execute(
                self.sql.SQL(
                    "INSERT INTO {}.volunteer_applications "
                    "(user_id, application_status, last_updated_at) "
                    "VALUES (%s, %s, %s)"
                ).format(self.sql.Identifier(schema)),
                (user_id, status, updated_time),
            )

    def connection_factory(self, region: object) -> object:
        """Return a real connection for the handler's regional boundary."""

        del region
        return self.connect()

    def test_real_connection_is_read_only_with_statement_timeout(self) -> None:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_read_only")
                self.assertEqual(cursor.fetchone()[0], "on")
                cursor.execute("SHOW statement_timeout")
                self.assertEqual(cursor.fetchone()[0], "10s")
                with self.assertRaises(self.psycopg2.errors.ReadOnlySqlTransaction):
                    cursor.execute(
                        self.sql.SQL(
                            "INSERT INTO {}.users (user_id) VALUES (%s)"
                        ).format(self.sql.Identifier(self.virginia_schema)),
                        ("READ-ONLY-PROBE",),
                    )
        finally:
            connection.close()

    def test_actual_sql_returns_only_in_review_rows(self) -> None:
        timestamp = datetime(2026, 5, 12, 7, 15)
        self.insert_application(
            self.virginia_schema,
            "SID-00-000-000-001",
            "IN_REVIEW",
            timestamp,
        )
        self.insert_application(
            self.virginia_schema,
            "SID-00-000-000-002",
            "STARTED",
            timestamp + timedelta(hours=1),
        )
        self.insert_application(
            self.virginia_schema,
            "SID-00-000-000-003",
            "ACCEPTED",
            timestamp + timedelta(hours=2),
        )

        connection = self.connect()
        try:
            candidates, total = MODULE.fetch_region_candidates(
                connection,
                self.test_regions[0],
                10,
            )
        finally:
            connection.close()

        self.assertEqual(total, 1)
        self.assertEqual(
            [candidate.user_id for candidate in candidates],
            ["SID-00-000-000-001"],
        )

    def test_actual_sql_count_and_limit_are_correct(self) -> None:
        base_time = datetime(2026, 5, 12, 12)
        for index in range(5):
            self.insert_application(
                self.virginia_schema,
                f"SID-00-000-000-00{index}",
                "IN_REVIEW",
                base_time - timedelta(hours=index),
            )

        connection = self.connect()
        try:
            candidates, total = MODULE.fetch_region_candidates(
                connection,
                self.test_regions[0],
                2,
            )
        finally:
            connection.close()

        self.assertEqual(total, 5)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(
            [candidate.user_id for candidate in candidates],
            ["SID-00-000-000-000", "SID-00-000-000-001"],
        )

    def test_actual_sql_orders_ties_and_nulls_deterministically(self) -> None:
        timestamp = datetime(2026, 5, 12, 12)
        self.insert_application(self.virginia_schema, "SID-B", "IN_REVIEW", timestamp)
        self.insert_application(self.virginia_schema, "SID-A", "IN_REVIEW", timestamp)
        self.insert_application(self.virginia_schema, "SID-C", "IN_REVIEW", None)

        connection = self.connect()
        try:
            candidates, total = MODULE.fetch_region_candidates(
                connection,
                self.test_regions[0],
                10,
            )
        finally:
            connection.close()

        self.assertEqual(total, 3)
        self.assertEqual(
            [candidate.user_id for candidate in candidates],
            ["SID-A", "SID-B", "SID-C"],
        )

    def test_actual_sql_empty_region_returns_empty_and_zero(self) -> None:
        connection = self.connect()
        try:
            candidates, total = MODULE.fetch_region_candidates(
                connection,
                self.test_regions[0],
                10,
            )
        finally:
            connection.close()
        self.assertEqual(candidates, [])
        self.assertEqual(total, 0)

    def test_actual_cross_region_query_merges_and_sums(self) -> None:
        self.insert_application(
            self.virginia_schema,
            "SID-00-000-000-001",
            "IN_REVIEW",
            datetime(2026, 5, 12, 8),
        )
        self.insert_application(
            self.ireland_schema,
            "SID-EU-000-000-001",
            "IN_REVIEW",
            datetime(2026, 5, 12, 9),
        )

        with mock.patch.object(MODULE, "REGIONS", self.test_regions):
            candidates, total = MODULE.query_regions(5, self.connection_factory)

        self.assertEqual(total, 2)
        self.assertEqual(
            [candidate.user_id for candidate in candidates],
            ["SID-EU-000-000-001", "SID-00-000-000-001"],
        )

    def test_local_e2e_page_one_and_page_two_are_exact(self) -> None:
        applications = (
            (self.virginia_schema, "SID-V-1", datetime(2026, 5, 12, 12)),
            (self.ireland_schema, "SID-I-1", datetime(2026, 5, 12, 11)),
            (self.virginia_schema, "SID-V-2", datetime(2026, 5, 12, 10)),
            (self.ireland_schema, "SID-I-2", datetime(2026, 5, 12, 9)),
        )
        for schema, user_id, updated_time in applications:
            self.insert_application(schema, user_id, "IN_REVIEW", updated_time)

        def open_connection(region: object, ssm_client: object) -> object:
            del region, ssm_client
            return self.connect()

        with mock.patch.object(MODULE, "REGIONS", self.test_regions):
            with mock.patch.object(MODULE, "create_ssm_client", return_value=object()):
                with mock.patch.object(
                    MODULE,
                    "open_database_connection",
                    side_effect=open_connection,
                ):
                    page_one = MODULE.lambda_handler(
                        {"body": json.dumps({"page": 1, "page_size": 2})},
                        None,
                    )
                    page_two = MODULE.lambda_handler(
                        {"body": json.dumps({"page": 2, "page_size": 2})},
                        None,
                    )

        self.assertEqual(page_one["statusCode"], 200)
        self.assertEqual(page_two["statusCode"], 200)
        self.assertEqual(
            [row["user_id"] for row in decode_response(page_one)["data"]],
            ["SID-V-1", "SID-I-1"],
        )
        self.assertEqual(
            [row["user_id"] for row in decode_response(page_two)["data"]],
            ["SID-V-2", "SID-I-2"],
        )
        self.assertEqual(
            decode_response(page_two)["pagination"],
            {
                "current_page": 2,
                "page_size": 2,
                "total_records": 4,
                "total_pages": 2,
            },
        )

    def test_local_e2e_empty_queue_returns_success(self) -> None:
        def open_connection(region: object, ssm_client: object) -> object:
            del region, ssm_client
            return self.connect()

        with mock.patch.object(MODULE, "REGIONS", self.test_regions):
            with mock.patch.object(MODULE, "create_ssm_client", return_value=object()):
                with mock.patch.object(
                    MODULE,
                    "open_database_connection",
                    side_effect=open_connection,
                ):
                    response = MODULE.lambda_handler(
                        {"body": json.dumps({"page": 1, "page_size": 5})},
                        None,
                    )

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(decode_response(response)["data"], [])
        self.assertEqual(decode_response(response)["pagination"]["total_pages"], 0)

    def test_local_e2e_invalid_input_returns_400_before_database(self) -> None:
        with mock.patch.object(MODULE, "open_database_connection") as open_connection:
            response = MODULE.lambda_handler(
                {"body": json.dumps({"page": 0, "page_size": 5})},
                None,
            )
        self.assertEqual(response["statusCode"], 400)
        open_connection.assert_not_called()

    def test_local_e2e_one_region_failure_returns_safe_500(self) -> None:
        def open_connection(region: object, ssm_client: object) -> object:
            del ssm_client
            if region.name == "Ireland":
                raise RuntimeError("postgresql://secret-host/private")
            return self.connect()

        with mock.patch.object(MODULE, "REGIONS", self.test_regions):
            with mock.patch.object(MODULE, "create_ssm_client", return_value=object()):
                with mock.patch.object(
                    MODULE,
                    "open_database_connection",
                    side_effect=open_connection,
                ):
                    response = MODULE.lambda_handler({}, None)

        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(
            decode_response(response),
            {"error": "Unable to retrieve volunteer review requests."},
        )
        self.assertNotIn("secret-host", str(response))


if __name__ == "__main__":
    unittest.main()
