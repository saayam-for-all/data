"""
Steward Dashboard - Review Volunteers AWS Lambda API (issue #273)

Retrieves paginated volunteer review requests for the Steward Dashboard by
joining the `users` and `volunteer_applications` tables. Each row surfaces
the reviewer-facing fields only: user id, when the application was last
updated, and the current review action (application status), sorted by the
most recently updated request first.

Request payload (event body or plain dict when invoked directly):
    {
        "page": 1,          # optional, defaults to 1
        "page_size": 10     # optional, defaults to 10, capped at 100
    }

Response body:
    {
        "data": [
            {
                "user_id": "SID-00-000-654-114",
                "last_updated_at": "2026-02-22T04:23:08",
                "review_action": "UNDER_REVIEW"
            },
            ...
        ],
        "pagination": {
            "page": 1,
            "page_size": 10,
            "total_records": 42,
            "total_pages": 5
        }
    }
"""
import json
import math
import os

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor

SCHEMA_NAME = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")
DB_SSM_PARAM = os.environ.get("DB_SSM_PARAM", "/dev/saayam/db/Virginia/Analytics/user")

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100


def parse_event_body(event):
    """
    Normalizes the incoming Lambda event so the handler reads parameters
    the same way whether it was invoked through API Gateway (JSON-encoded
    string body) or invoked directly with a plain dict (e.g. from tests).
    """
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
    """
    Reads and sanitizes the page / page_size parameters. Falls back to
    sane defaults and clamps out-of-range values instead of raising, so a
    bad client value degrades gracefully rather than failing the request.
    """
    try:
        page = int(request_body.get("page", DEFAULT_PAGE))
    except (TypeError, ValueError):
        page = DEFAULT_PAGE

    try:
        page_size = int(request_body.get("page_size", DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        page_size = DEFAULT_PAGE_SIZE

    if page < 1:
        page = DEFAULT_PAGE

    if page_size < 1:
        page_size = DEFAULT_PAGE_SIZE
    elif page_size > MAX_PAGE_SIZE:
        page_size = MAX_PAGE_SIZE

    return page, page_size


def get_db_connection():
    """
    Builds a Postgres connection using credentials pulled from AWS
    Parameter Store at invocation time. No credentials are hardcoded;
    the parameter name itself can be overridden via the DB_SSM_PARAM
    environment variable if a deployment needs a different path.
    """
    ssm = boto3.client("ssm", region_name="us-east-1")

    response = ssm.get_parameter(
        Name=DB_SSM_PARAM,
        WithDecryption=True
    )

    creds = json.loads(response["Parameter"]["Value"])
    return psycopg2.connect(
        host=creds["HOST"],
        database=creds["DATABASE NAME"],
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require"
    )


def get_total_review_count(cursor):
    """
    Returns the total number of volunteer review requests (users that
    have a volunteer application on file), used to compute pagination
    metadata (total_records / total_pages).
    """
    query = f"""
        SELECT COUNT(*) AS total
        FROM {SCHEMA_NAME}.users u
        JOIN {SCHEMA_NAME}.volunteer_applications va
            ON u.user_id = va.user_id
    """
    cursor.execute(query)
    row = cursor.fetchone()
    return int(row["total"]) if row and row["total"] is not None else 0


def get_volunteer_reviews(cursor, page, page_size):
    """
    Fetches one page of volunteer review requests, joining users and
    volunteer_applications by user_id, sorted by the most recently
    updated application first. Uses parameterized LIMIT/OFFSET so page
    and page_size are never interpolated directly into the SQL string.
    """
    offset = (page - 1) * page_size

    query = f"""
        SELECT
            u.user_id AS user_id,
            va.last_updated_at AS last_updated_at,
            va.application_status AS review_action
        FROM {SCHEMA_NAME}.users u
        JOIN {SCHEMA_NAME}.volunteer_applications va
            ON u.user_id = va.user_id
        ORDER BY va.last_updated_at DESC
        LIMIT %s OFFSET %s
    """
    cursor.execute(query, (page_size, offset))
    rows = cursor.fetchall()

    return [
        {
            "user_id": row["user_id"],
            "last_updated_at": row["last_updated_at"].isoformat() if row["last_updated_at"] else None,
            "review_action": row["review_action"]
        }
        for row in rows
    ]


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
        },
        "body": json.dumps(body, default=str)
    }


def lambda_handler(event, context):
    conn = None
    cursor = None

    request_body = parse_event_body(event)
    page, page_size = get_pagination_params(request_body)

    safe_response = {
        "data": [],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_records": 0,
            "total_pages": 0
        }
    }

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        total_records = get_total_review_count(cursor)
        total_pages = math.ceil(total_records / page_size) if total_records > 0 else 0
        data = get_volunteer_reviews(cursor, page, page_size) if total_records > 0 else []

        response_body = {
            "data": data,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_records": total_records,
                "total_pages": total_pages
            }
        }

        return build_response(200, response_body)

    except Exception as e:
        print("ERROR:", str(e))
        return build_response(500, safe_response)

    finally:
        if cursor: cursor.close()
        if conn: conn.close()


if __name__ == "__main__":
    test_event = {"page": 1, "page_size": 10}
    print(json.dumps(lambda_handler(test_event, None), indent=2))