import json
import os
import re

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"
DATE_TIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, default=str)
    }


def get_event_body(event):
    if not event:
        return {}

    if "body" in event:
        body = event.get("body")

        if isinstance(body, str):
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {}

        if isinstance(body, dict):
            return body

    return event


def get_ssm_parameter(parameter_name):
    ssm_client = boto3.client("ssm")
    response = ssm_client.get_parameter(
        Name=parameter_name,
        WithDecryption=True
    )
    return response["Parameter"]["Value"]


def get_db_value(env_name, default_value=None):
    """
    Supports SSM Parameter Store first.

    Example:
        DB_HOST_PARAM=/saayam/virginia/db/host

    Fallback:
        DB_HOST=localhost

    This fallback helps local testing and keeps the file similar to
    kpi_api_analytics.py, but Lambda should use *_PARAM env vars.
    """
    param_name = os.getenv(f"{env_name}_PARAM")

    if param_name:
        return get_ssm_parameter(param_name)

    return os.getenv(env_name, default_value)


def get_db_connection():
    return psycopg2.connect(
        host=get_db_value("DB_HOST", "localhost"),
        database=get_db_value("DB_NAME"),
        user=get_db_value("DB_USER"),
        password=get_db_value("DB_PASSWORD"),
        port=get_db_value("DB_PORT", "5432")
    )


def normalize_db_value(value):
    if value is None:
        return None

    value = str(value).strip()

    if value.lower() in {"null", "[null]", "none"}:
        return None

    return value


def split_datetime_value(field_value):
    date_part, time_part = field_value.split("T", 1)

    time_part = time_part.replace("Z", "")

    if "." in time_part:
        time_part = time_part.split(".", 1)[0]

    return date_part, time_part


def add_datetime_field(additional_fields, field_id, item_id, field_value):
    date_value, time_value = split_datetime_value(field_value)

    if field_id not in additional_fields or not isinstance(additional_fields[field_id], dict):
        additional_fields[field_id] = {}

    key_prefix = item_id if item_id else field_id

    additional_fields[field_id][f"{key_prefix}_date"] = date_value
    additional_fields[field_id][f"{key_prefix}_time"] = time_value


def transform_rows_to_additional_fields(rows):
    additional_fields = {}

    for row in rows:
        field_id = normalize_db_value(row.get("field_id"))
        item_id = normalize_db_value(row.get("item_id"))
        field_value = normalize_db_value(row.get("field_value"))

        if not field_id:
            continue

        # Date/time fields are detected dynamically using the field_value pattern.
        if field_value and DATE_TIME_PATTERN.match(field_value):
            add_datetime_field(additional_fields, field_id, item_id, field_value)
            continue

        # item_id not null + field_value null:
        # Radio/checkbox selection -> "field_id": ["item_id1", "item_id2"]
        if item_id and field_value is None:
            if field_id not in additional_fields:
                additional_fields[field_id] = []

            if not isinstance(additional_fields[field_id], list):
                additional_fields[field_id] = []

            additional_fields[field_id].append(item_id)
            continue

        # item_id not null + field_value not null:
        # Object/list style -> "field_id": {"item_id1": "val1"}
        if item_id and field_value is not None:
            if field_id not in additional_fields:
                additional_fields[field_id] = {}

            if not isinstance(additional_fields[field_id], dict):
                additional_fields[field_id] = {}

            additional_fields[field_id][item_id] = field_value
            continue

        # item_id null + field_value not null:
        # Textbox/integer field -> "field_id": "field_value"
        if item_id is None and field_value is not None:
            additional_fields[field_id] = field_value
            continue

    return additional_fields


def fetch_additional_request_details(cursor, request_id):
    query = f"""
        SELECT field_id, item_id, field_value
        FROM {SCHEMA_NAME}.req_add_info
        WHERE req_id = %s;
    """

    cursor.execute(query, (request_id,))
    return cursor.fetchall()


def lambda_handler(event, context):
    conn = None
    cursor = None

    body = get_event_body(event)
    request_id = body.get("request_id")

    if not request_id:
        return build_response(
            400,
            {"error": "DE 1002: Internal Server Error"}
        )

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

    except Exception as error:
        print(f"DB connection failed: {error}")
        return build_response(
            500,
            {"error": "DE 1000: Internal Server Error"}
        )

    try:
        rows = fetch_additional_request_details(cursor, request_id)
        additional_fields = transform_rows_to_additional_fields(rows)

        return build_response(
            200,
            {
                "requestId": request_id,
                "additionalFields": additional_fields
            }
        )

    except Exception as error:
        print(f"Query execution failed: {error}")
        return build_response(
            500,
            {"error": "DE 1001: Internal Server Error"}
        )

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    sample_rows = [
        {
            "field_id": "1.1.B",
            "item_id": "1.1.B.1",
            "field_value": None
        },
        {
            "field_id": "1.1.B",
            "item_id": "1.1.B.2",
            "field_value": None
        },
        {
            "field_id": "1.2.A",
            "item_id": None,
            "field_value": "some typed response from user"
        },
        {
            "field_id": "1.2.B",
            "item_id": "1.2.B.2",
            "field_value": None
        },
        {
            "field_id": "2.1.C",
            "item_id": "2.1.C.1",
            "field_value": "3"
        },
        {
            "field_id": "2.1.C",
            "item_id": "2.1.C.3",
            "field_value": "9"
        },
        {
            "field_id": "6.1.B",
            "item_id": "6.1.B.1",
            "field_value": "2026-03-24T14:30:00"
        },
        {
            "field_id": "6.1.B",
            "item_id": "6.1.B.2",
            "field_value": "2026-03-28T14:10:00"
        },
        {
            "field_id": "6.8.C",
            "item_id": None,
            "field_value": "2026-04-15T17:09:00Z"
        }
    ]

    result = {
        "requestId": "REQ-123",
        "additionalFields": transform_rows_to_additional_fields(sample_rows)
    }

    expected = {
        "requestId": "REQ-123",
        "additionalFields": {
            "1.1.B": ["1.1.B.1", "1.1.B.2"],
            "1.2.A": "some typed response from user",
            "1.2.B": ["1.2.B.2"],
            "2.1.C": {
                "2.1.C.1": "3",
                "2.1.C.3": "9"
            },
            "6.1.B": {
                "6.1.B.1_date": "2026-03-24",
                "6.1.B.1_time": "14:30:00",
                "6.1.B.2_date": "2026-03-28",
                "6.1.B.2_time": "14:10:00"
            },
            "6.8.C": {
                "6.8.C_date": "2026-04-15",
                "6.8.C_time": "17:09:00"
            }
        }
    }

    assert result == expected

    print("All assertions passed")
    print(json.dumps(result, indent=2))