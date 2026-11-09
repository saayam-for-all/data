"""AWS Lambda API for the Steward Dashboard - Review Volunteers (issue #273).

Retrieves the volunteer applications that are waiting on a steward review by
joining the ``users`` and ``volunteers`` tables. The ``volunteers`` review
queue is backed by the ``volunteer_applications`` table, whose
``application_status`` enum carries the ``IN_REVIEW`` state a steward acts on.

Only the fields the Steward Dashboard needs are returned:
    * user_id           - used by the frontend for the "Review" action
    * updated_time      - last time the application changed (ISO-8601 UTC)
    * volunteer_review  - the review action label ("Review")

Results are sorted by the latest updated time, paginated, and returned with
pagination metadata. Follows the existing lambda coding standards in this
package (parse_event_body, psycopg2, boto3 SSM config, CORS headers, safe
error response). Supports the Virginia and Ireland databases and merges them.

Configuration is read from AWS SSM Parameter Store. The parameter *paths* are
supplied through environment variables so nothing (neither credentials nor
Parameter Store paths) is hardcoded:

    VIRGINIA_DB_PARAM   e.g. /dev/saayam/db/Virginia/Analytics/user
    IRELAND_DB_PARAM    e.g. /dev/saayam/db/Ireland/Analytics/user
    AWS_REGION          e.g. us-east-1 (falls back to us-east-1)

A region is queried only when its parameter path env var is set, so the
function works with one or both regions configured.
"""

import json
import math
import os

import boto3
import psycopg2

# --- Schemas / tables per region -------------------------------------------
SCHEMA_VIRGINIA = "virginia_dev_saayam_rdbms"
SCHEMA_IRELAND = "ireland_dev_saayam_rdbms"

REAL_TABLE_USERS_VIRGINIA = f"{SCHEMA_VIRGINIA}.users"
REAL_TABLE_VOLUNTEERS_VIRGINIA = f"{SCHEMA_VIRGINIA}.volunteer_applications"

REAL_TABLE_USERS_IRELAND = f"{SCHEMA_IRELAND}.users"
REAL_TABLE_VOLUNTEERS_IRELAND = f"{SCHEMA_IRELAND}.volunteer_applications"

# Application status that requires a steward review, and the action label the
# frontend renders for each row.
REVIEW_STATUS = "IN_REVIEW"
REVIEW_ACTION = "Review"

# Pagination defaults / guard rails.
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 5
MAX_PAGE_SIZE = 100

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def parse_event_body(event):
    """Return the request payload as a dict regardless of invocation style."""
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


def get_pagination_params(request_body):
    """Extract and validate ``page`` and ``page_size`` from the payload.

    Falls back to the defaults and clamps to safe bounds so a bad client value
    can never produce a negative OFFSET or an unbounded page size.
    """
    def _as_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    page = _as_int(request_body.get("page", DEFAULT_PAGE), DEFAULT_PAGE)
    page_size = _as_int(request_body.get("page_size", DEFAULT_PAGE_SIZE), DEFAULT_PAGE_SIZE)

    if page < 1:
        page = DEFAULT_PAGE
    if page_size < 1:
        page_size = DEFAULT_PAGE_SIZE
    if page_size > MAX_PAGE_SIZE:
        page_size = MAX_PAGE_SIZE

    return page, page_size


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


def format_updated_time(value):
    """Format a DB timestamp as ISO-8601 UTC (e.g. 2026-05-12T07:15:00Z)."""
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def fetch_review_requests(cursor, users_table, volunteers_table):
    """Fetch every volunteer application awaiting steward review for one region.

    Uses a parameterized query for the status filter. Returns a list of
    ``(user_id, updated_datetime)`` tuples ordered newest-first. Pagination is
    applied after merging regions so the combined order stays correct.
    """
    query = f"""
        SELECT u.user_id, va.last_updated_at
        FROM {users_table} u
        JOIN {volunteers_table} va ON u.user_id = va.user_id
        WHERE va.application_status = %s
        ORDER BY va.last_updated_at DESC
    """
    cursor.execute(query, (REVIEW_STATUS,))
    return cursor.fetchall()


def paginate(records, page, page_size):
    """Slice merged records and build the pagination metadata block."""
    total_records = len(records)
    total_pages = math.ceil(total_records / page_size) if total_records else 0

    start = (page - 1) * page_size
    end = start + page_size
    page_records = records[start:end]

    data = [
        {
            "user_id": user_id,
            "updated_time": format_updated_time(updated_time),
            "volunteer_review": REVIEW_ACTION,
        }
        for user_id, updated_time in page_records
    ]

    pagination = {
        "current_page": page,
        "page_size": page_size,
        "total_records": total_records,
        "total_pages": total_pages,
    }
    return data, pagination


def get_db_config(param_name):
    """Load a psycopg2 connection kwargs dict from an SSM parameter.

    The parameter value is expected to be JSON with HOST / DATABASE NAME /
    USERNAME / PASSWORD / PORT keys (same shape kpi_api_analytics.py uses).
    """
    region = os.environ.get("AWS_REGION", "us-east-1")
    ssm = boto3.client("ssm", region_name=region)

    response = ssm.get_parameter(Name=param_name, WithDecryption=True)
    creds = json.loads(response["Parameter"]["Value"])

    return {
        "host": creds["HOST"],
        "dbname": creds["DATABASE NAME"],
        "user": creds["USERNAME"],
        "password": creds["PASSWORD"],
        "port": creds["PORT"],
        "sslmode": "require",
    }


def connect_region(param_env_var):
    """Connect to a region's DB when its parameter path env var is configured.

    Returns ``None`` (region skipped) when the env var is unset. Raising here
    is intentional if the var is set but the connection fails, so the handler
    surfaces a safe error rather than silently dropping a region's queue.
    """
    param_name = os.environ.get(param_env_var)
    if not param_name:
        return None
    return psycopg2.connect(**get_db_config(param_name))


REGION_TABLES = {
    "VIRGINIA_DB_PARAM": (REAL_TABLE_USERS_VIRGINIA, REAL_TABLE_VOLUNTEERS_VIRGINIA),
    "IRELAND_DB_PARAM": (REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEERS_IRELAND),
}


def lambda_handler(event, context):
    request_body = parse_event_body(event)
    page, page_size = get_pagination_params(request_body)

    connections = []
    try:
        merged = []
        for param_env_var, (users_table, volunteers_table) in REGION_TABLES.items():
            conn = connect_region(param_env_var)
            if conn is None:
                continue
            connections.append(conn)
            cursor = conn.cursor()
            try:
                merged.extend(fetch_review_requests(cursor, users_table, volunteers_table))
            finally:
                cursor.close()

        # Newest first across all regions. sort() is stable so ties keep their
        # per-region DESC order; None timestamps sort last.
        merged.sort(key=lambda row: (row[1] is not None, row[1]), reverse=True)

        data, pagination = paginate(merged, page, page_size)
        return build_response(200, {"data": data, "pagination": pagination})

    except Exception as exc:  # noqa: BLE001 - return a safe response, never leak internals
        print("ERROR in steward_volunteer_review_api:", str(exc))
        return build_response(
            500,
            {
                "data": [],
                "pagination": {
                    "current_page": page,
                    "page_size": page_size,
                    "total_records": 0,
                    "total_pages": 0,
                },
                "error": "Unable to retrieve volunteer review requests.",
            },
        )
    finally:
        for conn in connections:
            conn.close()


if __name__ == "__main__":
    # Local smoke run. Without AWS configured this exercises the error path and
    # returns the safe response; the real coverage lives in the unit tests.
    print(lambda_handler({"page": 1, "page_size": 5}, None))
