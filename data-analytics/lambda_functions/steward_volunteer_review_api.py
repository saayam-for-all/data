"""Lambda API for the Steward Dashboard's volunteer review queue (Issue #273).

The function reads review-ready volunteer applications from the configured
regional databases, merges them, orders them by last update, and returns a
page suitable for the Steward Dashboard. Database credentials and SSM parameter
paths are supplied only through environment variables.
"""

import json
import math
import os
from datetime import date, datetime, timezone
from typing import Any, Iterable

try:  # AWS Lambda provides boto3; retaining an optional import keeps unit tests local.
    import boto3
except ImportError:  # pragma: no cover - exercised only in dependency-light local runs
    boto3 = None

try:
    import psycopg2
except ImportError:  # pragma: no cover - exercised only in dependency-light local runs
    psycopg2 = None


DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 5
MAX_PAGE_SIZE = 100
DEFAULT_REVIEW_STATUS = "UNDER_REVIEW"
REVIEW_ACTION = "Review"

REGION_TABLES = {
    "VIRGINIA_DB_PARAM": (
        "virginia_dev_saayam_rdbms.users",
        "virginia_dev_saayam_rdbms.volunteer_applications",
    ),
    "IRELAND_DB_PARAM": (
        "ireland_dev_saayam_rdbms.users",
        "ireland_dev_saayam_rdbms.volunteer_applications",
    ),
}

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def parse_event_body(event: dict[str, Any] | None) -> dict[str, Any]:
    """Extract an object payload from a direct or API Gateway Lambda event."""
    if not event:
        return {}

    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def get_pagination_params(payload: dict[str, Any]) -> tuple[int, int]:
    """Validate pagination input and apply API guardrails."""
    def as_positive_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    page = as_positive_int(payload.get("page"), DEFAULT_PAGE)
    page_size = as_positive_int(payload.get("page_size"), DEFAULT_PAGE_SIZE)
    return page, min(page_size, MAX_PAGE_SIZE)


def get_review_status() -> str:
    """Return the confirmed queue status, with a safe local-data default.

    The repository's local mock data uses ``UNDER_REVIEW``. Set
    ``VOLUNTEER_REVIEW_STATUS`` in Lambda configuration if the target database
    reports a different value from ``SELECT DISTINCT application_status ...``.
    """
    return os.environ.get("VOLUNTEER_REVIEW_STATUS", DEFAULT_REVIEW_STATUS)


def build_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """Build an API Gateway-compatible JSON response."""
    return {"statusCode": status_code, "headers": CORS_HEADERS, "body": json.dumps(body)}


def empty_pagination(page: int, page_size: int) -> dict[str, int]:
    """Return the pagination shape used by success and safe-error responses."""
    return {
        "current_page": page,
        "page_size": page_size,
        "total_records": 0,
        "total_pages": 0,
    }


def get_db_config(parameter_name: str) -> dict[str, Any]:
    """Read one database connection configuration from AWS Parameter Store."""
    if boto3 is None:
        raise RuntimeError("boto3 is required to retrieve database configuration")

    ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    parameter = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
    credentials = json.loads(parameter["Parameter"]["Value"])
    return {
        "host": credentials["HOST"],
        "dbname": credentials["DATABASE NAME"],
        "user": credentials["USERNAME"],
        "password": credentials["PASSWORD"],
        "port": credentials["PORT"],
        "sslmode": "require",
    }


def connect_region(parameter_env_var: str):
    """Open a configured regional database connection, or skip an unset region."""
    parameter_name = os.environ.get(parameter_env_var)
    if not parameter_name:
        return None
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required to connect to the database")
    return psycopg2.connect(**get_db_config(parameter_name))


def fetch_review_records(cursor: Any, users_table: str, applications_table: str, review_status: str) -> list[tuple[Any, Any]]:
    """Fetch one region's review queue with a parameterized status predicate."""
    query = f"""
        SELECT u.user_id, va.last_updated_at
        FROM {users_table} AS u
        INNER JOIN {applications_table} AS va ON va.user_id = u.user_id
        WHERE va.application_status = %s
        ORDER BY va.last_updated_at DESC
    """
    cursor.execute(query, (review_status,))
    return list(cursor.fetchall())


def record_sort_key(record: tuple[Any, Any]) -> tuple[bool, Any]:
    """Sort null timestamps last without comparing null to datetime values."""
    updated_time = record[1]
    return updated_time is not None, updated_time


def format_updated_time(value: Any) -> str | None:
    """Represent a database timestamp as an ISO-8601 UTC value."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def paginate(records: Iterable[tuple[Any, Any]], page: int, page_size: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build page rows and accompanying pagination metadata from sorted records."""
    all_records = list(records)
    total_records = len(all_records)
    total_pages = math.ceil(total_records / page_size) if total_records else 0
    start = (page - 1) * page_size
    selected_records = all_records[start:start + page_size]
    data = [
        {
            "user_id": user_id,
            "updated_time": format_updated_time(updated_time),
            "volunteer_review": REVIEW_ACTION,
        }
        for user_id, updated_time in selected_records
    ]
    return data, {
        "current_page": page,
        "page_size": page_size,
        "total_records": total_records,
        "total_pages": total_pages,
    }


def lambda_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    """Return volunteer applications awaiting steward review without exposing DB errors."""
    payload = parse_event_body(event)
    page, page_size = get_pagination_params(payload)
    connections = []

    try:
        records = []
        configured_regions = 0
        review_status = get_review_status()

        for parameter_env_var, (users_table, applications_table) in REGION_TABLES.items():
            connection = connect_region(parameter_env_var)
            if connection is None:
                continue
            configured_regions += 1
            connections.append(connection)
            cursor = connection.cursor()
            try:
                records.extend(fetch_review_records(cursor, users_table, applications_table, review_status))
            finally:
                cursor.close()

        if not configured_regions:
            raise RuntimeError("No regional database configuration is available")

        records.sort(key=record_sort_key, reverse=True)
        data, pagination = paginate(records, page, page_size)
        return build_response(200, {"data": data, "pagination": pagination})
    except Exception as error:  # Never return database or infrastructure details to callers.
        print(f"steward_volunteer_review_api failed: {error}")
        return build_response(
            500,
            {
                "data": [],
                "pagination": empty_pagination(page, page_size),
                "error": "Unable to retrieve volunteer review requests.",
            },
        )
    finally:
        for connection in connections:
            connection.close()
