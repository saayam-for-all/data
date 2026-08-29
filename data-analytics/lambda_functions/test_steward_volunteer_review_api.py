import importlib.util
import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch


MODULE_PATH = (
    Path(__file__).parent
    / "steward_volunteer_review_api.py"
)

spec = importlib.util.spec_from_file_location(
    "steward_volunteer_review_api",
    MODULE_PATH,
)

api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class TestStewardVolunteerReviewApi(unittest.TestCase):

    def test_parse_direct_event(self):
        event = {
            "page": 2,
            "page_size": 10,
        }

        result = api.parse_event_body(event)

        self.assertEqual(result["page"], 2)
        self.assertEqual(result["page_size"], 10)

    def test_parse_api_gateway_body(self):
        event = {
            "body": json.dumps(
                {
                    "page": 3,
                    "page_size": 20,
                }
            )
        }

        result = api.parse_event_body(event)

        self.assertEqual(result["page"], 3)
        self.assertEqual(result["page_size"], 20)

    def test_default_pagination(self):
        page, page_size = api.get_pagination_params({})

        self.assertEqual(page, 1)
        self.assertEqual(page_size, 5)

    def test_invalid_pagination_uses_defaults(self):
        page, page_size = api.get_pagination_params(
            {
                "page": -2,
                "page_size": 0,
            }
        )

        self.assertEqual(page, 1)
        self.assertEqual(page_size, 5)

    def test_page_size_is_capped(self):
        page, page_size = api.get_pagination_params(
            {
                "page": 1,
                "page_size": 1000,
            }
        )

        self.assertEqual(page, 1)
        self.assertEqual(page_size, 100)

    def test_fetch_review_requests_uses_correct_filter(self):
        cursor = MagicMock()

        expected_rows = [
            (
                "SID-00-000-000-001",
                datetime(
                    2026,
                    5,
                    12,
                    7,
                    15,
                    tzinfo=timezone.utc,
                ),
            )
        ]

        cursor.fetchall.return_value = expected_rows

        result = api.fetch_review_requests(
            cursor,
            "virginia_dev_saayam_rdbms",
        )

        self.assertEqual(result, expected_rows)

        query, parameters = cursor.execute.call_args.args

        self.assertIn(
            "volunteer_applications",
            query,
        )

        self.assertIn(
            "JOIN",
            query,
        )

        self.assertIn(
            "application_status = %s",
            query,
        )

        self.assertIn(
            "ORDER BY va.last_updated_at DESC",
            query,
        )

        self.assertEqual(
            parameters,
            ("IN_REVIEW",),
        )

    def test_paginate_records(self):
        records = [
            (
                "user-1",
                datetime(
                    2026,
                    8,
                    20,
                    tzinfo=timezone.utc,
                ),
            ),
            (
                "user-2",
                datetime(
                    2026,
                    8,
                    19,
                    tzinfo=timezone.utc,
                ),
            ),
            (
                "user-3",
                datetime(
                    2026,
                    8,
                    18,
                    tzinfo=timezone.utc,
                ),
            ),
        ]

        data, pagination = api.paginate_records(
            records,
            page=1,
            page_size=2,
        )

        self.assertEqual(len(data), 2)

        self.assertEqual(
            data[0]["user_id"],
            "user-1",
        )

        self.assertEqual(
            data[0]["volunteer_review"],
            "Review",
        )

        self.assertEqual(
            pagination["total_records"],
            3,
        )

        self.assertEqual(
            pagination["total_pages"],
            2,
        )

    def test_empty_results(self):
        data, pagination = api.paginate_records(
            [],
            page=1,
            page_size=5,
        )

        self.assertEqual(data, [])
        self.assertEqual(
            pagination["total_records"],
            0,
        )
        self.assertEqual(
            pagination["total_pages"],
            0,
        )

    @patch.object(api, "connect_to_region")
    def test_lambda_success(self, mock_connect):
        connection = MagicMock()
        cursor = MagicMock()

        connection.cursor.return_value = cursor

        cursor.fetchall.return_value = [
            (
                "SID-00-000-000-001",
                datetime(
                    2026,
                    5,
                    12,
                    7,
                    15,
                    tzinfo=timezone.utc,
                ),
            )
        ]

        # Only one region configured for this test.
        mock_connect.side_effect = [
            connection,
            None,
        ]

        event = {
            "page": 1,
            "page_size": 5,
        }

        response = api.lambda_handler(
            event,
            None,
        )

        self.assertEqual(
            response["statusCode"],
            200,
        )

        body = json.loads(response["body"])

        self.assertEqual(
            len(body["data"]),
            1,
        )

        self.assertEqual(
            body["data"][0]["user_id"],
            "SID-00-000-000-001",
        )

        self.assertEqual(
            body["data"][0]["volunteer_review"],
            "Review",
        )

        cursor.close.assert_called_once()
        connection.close.assert_called_once()

    @patch.object(api, "connect_to_region")
    def test_lambda_empty_results(self, mock_connect):
        connection = MagicMock()
        cursor = MagicMock()

        connection.cursor.return_value = cursor
        cursor.fetchall.return_value = []

        mock_connect.side_effect = [
            connection,
            None,
        ]

        response = api.lambda_handler(
            {
                "page": 1,
                "page_size": 5,
            },
            None,
        )

        body = json.loads(response["body"])

        self.assertEqual(
            response["statusCode"],
            200,
        )

        self.assertEqual(
            body["data"],
            [],
        )

        self.assertEqual(
            body["pagination"]["total_records"],
            0,
        )

    @patch.object(api, "connect_to_region")
    def test_database_error_returns_safe_response(
        self,
        mock_connect,
    ):
        mock_connect.side_effect = Exception(
            "sensitive database error"
        )

        response = api.lambda_handler(
            {
                "page": 1,
                "page_size": 5,
            },
            None,
        )

        body = json.loads(response["body"])

        self.assertEqual(
            response["statusCode"],
            500,
        )

        self.assertEqual(
            body["data"],
            [],
        )

        self.assertNotIn(
            "sensitive database error",
            response["body"],
        )

    def test_options_request(self):
        response = api.lambda_handler(
            {
                "requestContext": {
                    "http": {
                        "method": "OPTIONS",
                    }
                }
            },
            None,
        )

        self.assertEqual(
            response["statusCode"],
            200,
        )


class TestDatabaseConfiguration(unittest.TestCase):

    @patch.object(api.boto3, "client")
    def test_get_db_config(self, mock_boto_client):
        ssm = MagicMock()

        mock_boto_client.return_value = ssm

        ssm.get_parameter.return_value = {
            "Parameter": {
                "Value": json.dumps(
                    {
                        "HOST": "localhost",
                        "DATABASE NAME": "saayam",
                        "USERNAME": "test_user",
                        "PASSWORD": "test_password",
                        "PORT": 5432,
                    }
                )
            }
        }

        config = api.get_db_config(
            "/test/database/config"
        )

        self.assertEqual(
            config["host"],
            "localhost",
        )

        self.assertEqual(
            config["dbname"],
            "saayam",
        )

        self.assertEqual(
            config["port"],
            5432,
        )

        self.assertEqual(
            config["sslmode"],
            "require",
        )

        ssm.get_parameter.assert_called_once_with(
            Name="/test/database/config",
            WithDecryption=True,
        )

    @patch.object(api.psycopg2, "connect")
    @patch.object(api, "get_db_config")
    def test_connect_to_region(
        self,
        mock_get_config,
        mock_connect,
    ):
        mock_get_config.return_value = {
            "host": "localhost",
            "dbname": "saayam",
            "user": "test",
            "password": "test",
            "port": 5432,
        }

        with patch.dict(
            os.environ,
            {
                "TEST_DB_PARAMETER": "/test/db"
            },
        ):
            api.connect_to_region(
                "TEST_DB_PARAMETER"
            )

        mock_get_config.assert_called_once_with(
            "/test/db"
        )

        mock_connect.assert_called_once()


if __name__ == "__main__":
    unittest.main()