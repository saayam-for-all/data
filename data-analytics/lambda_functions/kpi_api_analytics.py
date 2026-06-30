import json
import os

import psycopg2
from psycopg2.extras import RealDictCursor
from aws_lambda_powertools.utilities import parameters

SCHEMA_NAME = "virginia_dev_saayam_rdbms"


SLA = {
    "target_days": 10,
    "target_hours": 240,
    "warning_days": 8.33,
    "warning_hours": 200
}


def get_default_response() -> dict:
    """Return the baseline response dict with safe/empty values for every key."""
    return {
        "request_status_distribution": [],
        "total_requests": 0,
        "average_resolution_time_by_category": [],
        "sla": SLA
    }


def build_response(status_code: int, body: dict) -> dict:
    """Wrap body in the standard Lambda HTTP response envelope."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, default=str)
    }


def build_date_filter(
    time_range: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[str, list]:
    """Return a (sql_predicate, params) tuple for the requested time window.

    Args:
        time_range: One of "7D", "30D", "1Y", "Custom", "All", or any
            unrecognized value (treated as "All" ΓÇö no filter).
        start_date: Inclusive start date string; required when time_range
            is "Custom".
        end_date: Inclusive end date string; required when time_range
            is "Custom".

    Returns:
        A 2-tuple of (predicate_string, params_list). The predicate string
        is safe to embed after WHERE or AND; params_list contains any %s
        values in declaration order and is always passed to cursor.execute.

    Raises:
        ValueError: When time_range is "Custom" and start_date or end_date
            is missing.
    """
    if time_range == "7D":
        return "r.submission_date >= CURRENT_DATE - INTERVAL '7 days'", []
    if time_range == "30D":
        return "r.submission_date >= CURRENT_DATE - INTERVAL '30 days'", []
    if time_range == "1Y":
        return "r.submission_date >= CURRENT_DATE - INTERVAL '1 year'", []
    if time_range == "Custom":
        if not start_date or not end_date:
            raise ValueError(
                "start_date and end_date are required when time_range='Custom'"
            )
        return "r.submission_date BETWEEN %s AND %s", [start_date, end_date]
    # "All" or any unrecognized value ΓåÆ no filter
    return "", []


def get_db_connection():
    """Return a psycopg2 connection.

    When DB_HOST is set in the environment (local development), connects
    using the five DB_* env vars.  Otherwise falls back to the existing
    AWS SSM Parameter Store path so the deployed Lambda is unaffected.
    """
    db_host = os.environ.get("DB_HOST")
    if db_host:
        return psycopg2.connect(
            host=db_host,
            database=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            port=int(os.environ.get("DB_PORT", "5432")),
            sslmode="require",
        )

    creds = json.loads(parameters.get_parameter(
        "/dev/saayam/db/Virginia/Analytics/user",
        decrypt=True,
        max_age=3600
    ))

    db_name = creds["DATABASE NAME"]

    return psycopg2.connect(
        host=creds["HOST"],
        database=db_name,
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require"
    )


def fetch_request_status_distribution(
    cursor,
    time_range: str = "All",
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Return request counts grouped by status, optionally filtered by date.

    Args:
        cursor: An open psycopg2 RealDictCursor.
        time_range: Date filter preset (see build_date_filter).
        start_date: Start date for "Custom" range.
        end_date: End date for "Custom" range.

    Returns:
        List of {"status": str, "count": int} dicts ordered by status.
    """
    predicate, params = build_date_filter(time_range, start_date, end_date)
    where_clause = f"WHERE {predicate}" if predicate else ""

    query = f"""
        SELECT
            rs.req_status AS status,
            COUNT(r.req_id) AS count
        FROM {SCHEMA_NAME}.request r
        JOIN {SCHEMA_NAME}.request_status rs
            ON r.req_status_id = rs.req_status_id
        {where_clause}
        GROUP BY rs.req_status
        ORDER BY rs.req_status;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "status": row["status"],
            "count": int(row["count"])
        }
        for row in rows
    ]


def fetch_total_requests(
    cursor,
    time_range: str = "All",
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    """Return total request count, optionally filtered by submission date.

    Args:
        cursor: An open psycopg2 RealDictCursor.
        time_range: Date filter preset (see build_date_filter).
        start_date: Start date for "Custom" range.
        end_date: End date for "Custom" range.

    Returns:
        Total request count as an integer.
    """
    predicate, params = build_date_filter(time_range, start_date, end_date)
    where_clause = f"WHERE {predicate}" if predicate else ""

    query = f"""
        SELECT COUNT(r.req_id) AS total_requests
        FROM {SCHEMA_NAME}.request r
        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    return int(row["total_requests"]) if row and row["total_requests"] is not None else 0


def fetch_average_resolution_time_by_category(
    cursor,
    time_range: str = "All",
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Return average resolution hours per help category, filtered by date.

    Existing conditions (non-null dates, serviced >= submitted, resolved
    statuses) are kept intact; the date filter is appended with AND.

    Args:
        cursor: An open psycopg2 RealDictCursor.
        time_range: Date filter preset (see build_date_filter).
        start_date: Start date for "Custom" range.
        end_date: End date for "Custom" range.

    Returns:
        List of {"category": str, "avg_hours": float} dicts, ordered
        descending by avg_hours.
    """
    predicate, params = build_date_filter(time_range, start_date, end_date)
    date_clause = f"AND {predicate}" if predicate else ""

    query = f"""
        SELECT
            hc.cat_name AS category,
            ROUND(
                AVG(
                    EXTRACT(EPOCH FROM (r.serviced_date - r.submission_date)) / 3600
                )::numeric,
                2
            ) AS avg_hours
        FROM {SCHEMA_NAME}.request r
        JOIN {SCHEMA_NAME}.help_categories hc
            ON r.req_cat_id = hc.cat_id
        JOIN {SCHEMA_NAME}.request_status rs
            ON r.req_status_id = rs.req_status_id
        WHERE r.submission_date IS NOT NULL
          AND r.serviced_date IS NOT NULL
          AND r.serviced_date >= r.submission_date
          AND UPPER(rs.req_status) IN ('COMPLETED', 'RESOLVED')
          {date_clause}
        GROUP BY hc.cat_name
        ORDER BY avg_hours DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "category": row["category"],
            "avg_hours": float(row["avg_hours"]) if row["avg_hours"] is not None else 0
        }
        for row in rows
    ]


def lambda_handler(event, context):
    """AWS Lambda entry point.

    Reads optional time_range / start_date / end_date from the event payload
    and passes them to each fetch function.  Defaults to "All" (no filter).
    A bad Custom payload causes individual query fallbacks; the sla block is
    always present in the response.
    """
    conn = None
    cursor = None
    response_body = get_default_response()

    event = event or {}
    time_range: str = event.get("time_range", "All")
    start_date: str | None = event.get("start_date")
    end_date: str | None = event.get("end_date")

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            response_body["request_status_distribution"] = fetch_request_status_distribution(
                cursor, time_range, start_date, end_date
            )
        except Exception as error:
            print(f"Status distribution query failed: {error}")
            response_body["request_status_distribution"] = []

        try:
            response_body["total_requests"] = fetch_total_requests(
                cursor, time_range, start_date, end_date
            )
        except Exception as error:
            print(f"Total request count query failed: {error}")
            response_body["total_requests"] = 0

        try:
            response_body["average_resolution_time_by_category"] = fetch_average_resolution_time_by_category(
                cursor, time_range, start_date, end_date
            )
        except Exception as error:
            print(f"Average resolution time query failed: {error}")
            response_body["average_resolution_time_by_category"] = []

        return build_response(200, response_body)

    except Exception as error:
        print(f"DB connection failed: {error}")
        return build_response(500, response_body)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    result = lambda_handler({}, None)
    print(json.dumps(result, indent=2))
