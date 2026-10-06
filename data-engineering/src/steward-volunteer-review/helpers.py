"""Database access and query helpers for the Steward Volunteer Review API (issue #273).

Column names for `volunteer_applications` are confirmed against
database/mock-data-generation/volunteer_applications.py (user_id,
application_status, last_updated_at). The `users` table has no DDL in this
repo; its primary key is ASSUMED to be `id` pending verification against the
real table - see infrastructure/db/init/002_steward_volunteer_review.sql.
"""
import json
import math
import os

import psycopg2

# Status value(s) that mean "needs steward review". Confirm against the live
# DB with `SELECT DISTINCT application_status FROM volunteer_applications;`
# before relying on this in a real environment - defaults to the mock-data
# generator's value (database/mock-data-generation/utils.py STATUSES).
REVIEW_STATUSES = [
    status.strip()
    for status in os.getenv("STEWARD_REVIEW_STATUSES", "UNDER_REVIEW").split(",")
    if status.strip()
]

# Optional schema qualifying the users / volunteer_applications tables.
# Configurable so no schema name is hardcoded against a specific environment.
DB_SCHEMA = os.getenv("STEWARD_REVIEW_DB_SCHEMA", "").strip()

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 10

# Action label the Steward Dashboard shows for every row this endpoint returns.
VOLUNTEER_REVIEW_ACTION = "Review"


def _qualified(table_name):
    """Prefixes table_name with DB_SCHEMA when one is configured."""
    return f"{DB_SCHEMA}.{table_name}" if DB_SCHEMA else table_name


def get_db_connection():
    """Opens a Postgres connection.

    In deployed environments, credentials are pulled from AWS Parameter
    Store at the path named by the DB_CREDENTIALS_PARAM env var - the path
    itself is never hardcoded. For local/dev testing (no AWS access, per
    CONTRIBUTING.md), set DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD instead
    (e.g. against infrastructure/docker-compose.yml's Postgres).
    """
    param_path = os.getenv("DB_CREDENTIALS_PARAM")

    if param_path:
        from aws_lambda_powertools.utilities import parameters

        creds = json.loads(parameters.get_parameter(param_path, decrypt=True, max_age=3600))
        return psycopg2.connect(
            host=creds["HOST"],
            user=creds["USERNAME"],
            password=creds["PASSWORD"],
            database=creds["DATABASE NAME"],
            port=creds["PORT"],
            sslmode="require",
        )

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "saayam"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "password"),
    )


def parse_pagination(body):
    """Validates and normalizes page/page_size from the request body.

    Returns (page, page_size). Raises ValueError with a user-facing message
    on invalid input.
    """
    page = body.get("page", 1)
    page_size = body.get("page_size", DEFAULT_PAGE_SIZE)

    try:
        page = int(page)
        page_size = int(page_size)
    except (TypeError, ValueError):
        raise ValueError("page and page_size must be integers")

    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")

    return page, page_size


def get_applications_for_review(page, page_size):
    """Fetches one page of volunteer applications awaiting steward review.

    Joins volunteer_applications to users on user ID, filters to the
    configured review status(es), and sorts by last_updated_at descending.
    Uses parameterized queries throughout. Returns (rows, total_records).
    """
    users_table = _qualified("users")
    applications_table = _qualified("volunteer_applications")
    offset = (page - 1) * page_size

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM {applications_table} va
            JOIN {users_table} u ON va.user_id = u.id
            WHERE va.application_status = ANY(%s)
            """,
            (REVIEW_STATUSES,),
        )
        total_records = cursor.fetchone()[0]

        cursor.execute(
            f"""
            SELECT va.user_id, va.last_updated_at
            FROM {applications_table} va
            JOIN {users_table} u ON va.user_id = u.id
            WHERE va.application_status = ANY(%s)
            ORDER BY va.last_updated_at DESC
            LIMIT %s OFFSET %s
            """,
            (REVIEW_STATUSES, page_size, offset),
        )
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    data = [
        {
            "user_id": user_id,
            "updated_time": updated_time.isoformat() if hasattr(updated_time, "isoformat") else updated_time,
            "volunteer_review": VOLUNTEER_REVIEW_ACTION,
        }
        for user_id, updated_time in rows
    ]

    return data, total_records


def build_pagination(page, page_size, total_records):
    """Builds the pagination block for the API response."""
    return {
        "current_page": page,
        "page_size": page_size,
        "total_records": total_records,
        "total_pages": math.ceil(total_records / page_size),
    }
