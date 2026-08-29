"""
KPI Analytics Lambda for the Saayam Super Admin dashboard.

Returns chart-ready data for two KPI widgets:
    1. Request Status Distribution
    2. Average Resolution Time by Category

Database: Virginia AWS RDS PostgreSQL.
Closes #160.
"""

import json
import os

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor

SCHEMA = "virginia_dev_saayam_rdbms"

SSM_PARAM = "/dev/saayam/db/Virginia/Analytics/user"

# Statuses shown on the KPI dashboard.
# The request_status lookup table has RESOLVED. It does not have COMPLETED.
DASHBOARD_STATUSES = ("CREATED", "IN_PROGRESS", "RESOLVED")

# A request is finished once it reaches this status.
RESOLVED_STATUS = "RESOLVED"

# SLA targets come from the dashboard spec, not from the database.
SLA = {
    "target_days": 10,
    "target_hours": 240,
    "warning_days": 8.33,
    "warning_hours": 200,
}


def default_response():
    """Response shape used when data is missing or a query fails."""
    return {
        "request_status_distribution": [],
        "total_requests": 0,
        "average_resolution_time_by_category": [],
        "sla": SLA,
    }


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def get_db_connection():
    """
    Connect to the Virginia RDS database.

    Credentials are read from SSM Parameter Store, the same parameter used by
    beneficiariesTrendAnalysis.py. If DB_HOST is set in the environment, those
    values are used instead, so the Lambda can be run locally without AWS access.
    """
    if os.getenv("DB_HOST"):
        return psycopg2.connect(
            host=os.environ["DB_HOST"],
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.getenv("DB_PASSWORD", ""),
            port=os.getenv("DB_PORT", "5432"),
            sslmode=os.getenv("DB_SSLMODE", "require"),
        )

    ssm = boto3.client("ssm", region_name="us-east-1")
    parameter = ssm.get_parameter(Name=SSM_PARAM, WithDecryption=True)
    creds = json.loads(parameter["Parameter"]["Value"])

    return psycopg2.connect(
        host=creds["HOST"],
        dbname=creds["DATABASE NAME"],
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require",
    )


def get_request_status_distribution(cursor):
    """Count requests for each status shown on the dashboard."""
    query = f"""
        SELECT
            rs.req_status AS status,
            COUNT(r.req_id) AS count
        FROM {SCHEMA}.request r
        JOIN {SCHEMA}.request_status rs
            ON r.req_status_id = rs.req_status_id
        WHERE UPPER(rs.req_status) IN %(statuses)s
        GROUP BY rs.req_status
        ORDER BY rs.req_status;
    """

    cursor.execute(query, {"statuses": DASHBOARD_STATUSES})

    return [
        {"status": row["status"], "count": int(row["count"])}
        for row in cursor.fetchall()
    ]


def get_total_requests(cursor):
    """Count all requests, regardless of status."""
    query = f"SELECT COUNT(req_id) AS total FROM {SCHEMA}.request;"

    cursor.execute(query)
    row = cursor.fetchone()

    if not row or row["total"] is None:
        return 0

    return int(row["total"])


def get_average_resolution_time_by_category(cursor):
    """
    Average time to resolve a request, in hours, grouped by help category.

    Resolution time is serviced_date - submission_date. Rows are skipped when
    either date is missing, or when serviced_date is earlier than
    submission_date, since that cannot be a real resolution time.
    """
    query = f"""
        SELECT
            hc.cat_name AS category,
            ROUND(
                AVG(
                    EXTRACT(EPOCH FROM (r.serviced_date - r.submission_date)) / 3600
                )::numeric,
                2
            ) AS avg_hours
        FROM {SCHEMA}.request r
        JOIN {SCHEMA}.request_status rs
            ON r.req_status_id = rs.req_status_id
        JOIN {SCHEMA}.help_categories hc
            ON r.req_cat_id = hc.cat_id
        WHERE UPPER(rs.req_status) = %(resolved)s
          AND r.submission_date IS NOT NULL
          AND r.serviced_date IS NOT NULL
          AND r.serviced_date >= r.submission_date
        GROUP BY hc.cat_name
        ORDER BY avg_hours DESC;
    """

    cursor.execute(query, {"resolved": RESOLVED_STATUS})

    return [
        {"category": row["category"], "avg_hours": float(row["avg_hours"])}
        for row in cursor.fetchall()
    ]


def lambda_handler(event, context):
    body = default_response()
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
    except Exception as error:
        print("Database connection failed:", error)
        return build_response(500, body)

    try:
        # Each query is wrapped separately, so one failing widget does not
        # take down the rest of the dashboard.
        try:
            body["request_status_distribution"] = get_request_status_distribution(cursor)
        except Exception as error:
            print("Status distribution query failed:", error)

        try:
            body["total_requests"] = get_total_requests(cursor)
        except Exception as error:
            print("Total requests query failed:", error)

        try:
            body["average_resolution_time_by_category"] = (
                get_average_resolution_time_by_category(cursor)
            )
        except Exception as error:
            print("Average resolution time query failed:", error)

        return build_response(200, body)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        print("Database connection closed")


if __name__ == "__main__":
    print(json.dumps(lambda_handler({}, None), indent=2))
