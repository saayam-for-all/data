"""AWS Lambda API for the Steward Dashboard - Review Volunteers (issue #273).

Returns the volunteer applications that are waiting on a steward review by
joining ``users`` with ``volunteer_applications`` and filtering on the
``application_status`` enum. Results are sorted newest-first, paginated, and
returned in the shape the Steward Dashboard expects.

Follows the existing ``data-analytics/lambda_functions`` conventions
(``volunteer_application_analytics.py``): psycopg2 + boto3, credentials from
AWS SSM Parameter Store, Virginia + Ireland regions queried and merged, CORS
headers on every response, and a local ``__main__`` test block.

CONFIRM WITH SANA-DESAI before merging:
  * Table + status literal. The issue text says ``volunteers_details``, but the
    review signal lives in ``volunteer_applications.application_status``. Data
    shows the enum values DRAFT / SUBMITTED / UNDER_REVIEW / APPROVED /
    REJECTED, so ``UNDER_REVIEW`` is the state a steward acts on.
  * Base branch for the PR (main vs dev).
"""

import json
import os
from typing import Any, Optional

import boto3
import psycopg2

# --- Schema / table references -------------------------------------------------
SCHEMA_VIRGINIA = "virginia_dev_saayam_rdbms"
SCHEMA_IRELAND = "ireland_dev_saayam_rdbms"

TABLE_USERS_VIRGINIA = f"{SCHEMA_VIRGINIA}.users"
TABLE_APPLICATIONS_VIRGINIA = f"{SCHEMA_VIRGINIA}.volunteer_applications"
TABLE_USERS_IRELAND = f"{SCHEMA_IRELAND}.users"
TABLE_APPLICATIONS_IRELAND = f"{SCHEMA_IRELAND}.volunteer_applications"

# Application status that requires a steward review, and the action label the
# frontend renders as a button.
REVIEW_STATUS = "UNDER_REVIEW"
REVIEW_ACTION = "Review"

# SSM parameter PATHS come from the environment so nothing is hardcoded. The
# defaults match the existing analytics Lambdas and are safe to read.
SSM_PARAM_VIRGINIA = os.environ.get(
    "SSM_PARAM_VIRGINIA", "/dev/saayam/db/Virginia/Analytics/user"
)
SSM_PARAM_IRELAND = os.environ.get(
    "SSM_PARAM_IRELAND", "/dev/saayam/db/Ireland/Analytics/user"
)
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 5
MAX_PAGE_SIZE = 100

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def parse_event_body(event: Optional[dict]) -> dict:
    """Return the request payload whether invoked via API Gateway or directly."""
    if not event:
        return {}
    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body, dict):
        return body
    return {}


def get_pagination_params(request_body: dict) -> tuple[int, int]:
    """Extract and clamp ``page`` and ``page_size`` so a bad client value can
    never produce a negative offset or an unbounded page size."""

    def _as_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    page = max(1, _as_int(request_body.get("page"), DEFAULT_PAGE))
    page_size = _as_int(request_body.get("page_size"), DEFAULT_PAGE_SIZE)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    return page, page_size


def format_updated_time(value: Any) -> Optional[str]:
    """Render a DB timestamp as ISO-8601 UTC (``2026-05-12T07:15:00Z``)."""
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def build_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


def fetch_review_requests(cursor, users_table: str, applications_table: str) -> list:
    """Fetch every volunteer application awaiting steward review for one region.

    Uses a parameterized query for the status filter. Returns a list of
    ``(user_id, last_updated_at)`` tuples ordered newest-first. Global
    pagination is applied after merging regions so combined order stays correct.
    """
    query = f"""
        SELECT u.user_id, va.last_updated_at
        FROM {users_table} u
        JOIN {applications_table} va ON u.user_id = va.user_id
        WHERE va.application_status = %s
        ORDER BY va.last_updated_at DESC
    """
    cursor.execute(query, (REVIEW_STATUS,))
    return cursor.fetchall()


def paginate(records: list, page: int, page_size: int) -> dict:
    """Slice merged records and build the data + pagination metadata block."""
    total_records = len(records)
    total_pages = (total_records + page_size - 1) // page_size if total_records else 0

    start = (page - 1) * page_size
    page_rows = records[start : start + page_size]

    data = [
        {
            "user_id": user_id,
            "updated_time": format_updated_time(updated_at),
            "volunteer_review": REVIEW_ACTION,
        }
        for user_id, updated_at in page_rows
    ]

    return {
        "data": data,
        "pagination": {
            "current_page": page,
            "page_size": page_size,
            "total_records": total_records,
            "total_pages": total_pages,
        },
    }


def get_db_config(param_name: str) -> dict:
    """Load psycopg2 connection kwargs from an SSM SecureString parameter.

    Parsing mirrors the existing analytics Lambdas so it stays compatible with
    how the secret is currently stored.
    """
    ssm = boto3.client("ssm", region_name=AWS_REGION)
    response = ssm.get_parameter(Name=param_name, WithDecryption=True)

    config = response["Parameter"]["Value"]
    config_list = [line.strip() for line in config.splitlines()]

    host = config_list[1].split()[1][1:-2]
    port = int(config_list[5].split()[1][:-1])
    dbname = config_list[4].split()[2][1:-2]
    user = config_list[2].split()[1][1:-2]
    password = config_list[3].split()[1][1:-2]

    return {
        "host": host,
        "port": port,
        "dbname": dbname,
        "user": user,
        "password": password,
    }


def _empty_body(page: int, page_size: int) -> dict:
    return {
        "data": [],
        "pagination": {
            "current_page": page,
            "page_size": page_size,
            "total_records": 0,
            "total_pages": 0,
        },
    }


def lambda_handler(event, context):
    request_body = parse_event_body(event)
    page, page_size = get_pagination_params(request_body)

    regions = [
        (SSM_PARAM_VIRGINIA, TABLE_USERS_VIRGINIA, TABLE_APPLICATIONS_VIRGINIA),
        (SSM_PARAM_IRELAND, TABLE_USERS_IRELAND, TABLE_APPLICATIONS_IRELAND),
    ]

    merged: list = []
    try:
        for param_name, users_table, applications_table in regions:
            conn = None
            cursor = None
            try:
                conn = psycopg2.connect(**get_db_config(param_name))
                cursor = conn.cursor()
                merged.extend(
                    fetch_review_requests(cursor, users_table, applications_table)
                )
            finally:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()

        # Sort the merged set newest-first; None timestamps sort last.
        merged.sort(key=lambda row: (row[1] is not None, row[1]), reverse=True)

        return build_response(200, paginate(merged, page, page_size))

    except Exception as exc:  # noqa: BLE001 - return a safe response, never leak
        print("ERROR in steward_volunteer_review_api:", str(exc))
        return build_response(500, _empty_body(page, page_size))


if __name__ == "__main__":
    # Local smoke test against the real handler is not possible without AWS.
    # See test_steward_volunteer_review_api.py for cursor-based unit tests.
    print(json.dumps(paginate([], DEFAULT_PAGE, DEFAULT_PAGE_SIZE), indent=2))
