import json
import os
import boto3
import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"


SLA = {
    "target_days": 10,
    "target_hours": 240,
    "warning_days": 8.33,
    "warning_hours": 200
}


def get_default_response():
    return {
        "7D":  {"request_status_distribution": [], "total_requests": 0, "average_resolution_time_by_category": []},
        "30D": {"request_status_distribution": [], "total_requests": 0, "average_resolution_time_by_category": []},
        "1Y":  {"request_status_distribution": [], "total_requests": 0, "average_resolution_time_by_category": []},
        "All": {"request_status_distribution": [], "total_requests": 0, "average_resolution_time_by_category": []},
        "Custom": {"request_status_distribution": [], "total_requests": 0, "average_resolution_time_by_category": []},
        "Snapshot":{"request_status_distribution": [], "total_requests": 0, "average_resolution_time_by_category": []},
        "sla": SLA
    }


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": body
    }


def get_db_connection():
    ssm = boto3.client("ssm", region_name="us-east-1")

    response = ssm.get_parameter(
        Name="/dev/saayam/db/Virginia/Analytics/user",
        WithDecryption=True
    )

    creds = json.loads(response["Parameter"]["Value"])
    db_name = creds["DATABASE NAME"]
    return psycopg2.connect(
        host=creds["HOST"],
        database=db_name,
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require"
    )
def get_grouping(time_range):
    period = ""
    date_string = ""

    if time_range == '7D':
        period = "day"
        date_string = "YYYY-MM-DD"
    elif time_range == '30D':
        period = "day"
        date_string = "YYYY-MM-DD"
    elif time_range == '1Y':
        period = "month"
        date_string = "YYYY-MM"
    elif time_range == 'Custom':
        period = "day"
        date_string = "YYYY-MM-DD"
    elif time_range == "All":
        return "month", "YYYY-MM"
    elif time_range == 'Snapshot':
        return None,None
    else:
        raise ValueError("Invalid time range. Must be one of: '7D', '30D', '1Y', or 'Custom'.")

    return period, date_string

def build_date_filter(time_range, start_date=None, end_date=None):
    if time_range == "7D":
        return "r.submission_date >= CURRENT_DATE - INTERVAL '7 days'", ()

    if time_range == "30D":
        return "r.submission_date >= CURRENT_DATE - INTERVAL '30 days'", ()

    if time_range == "1Y":
        return "r.submission_date >= CURRENT_DATE - INTERVAL '1 year'", ()

    if time_range == "All":
        return "", ()

    if time_range == "Custom":
        if not start_date or not end_date:
            raise ValueError(
                "start_date and end_date are required when time_range is Custom"
            )

        return "r.submission_date BETWEEN %s AND %s", (
            start_date,
            end_date
        )

    raise ValueError(
        "Invalid time_range. Supported values are: 7D, 30D, 1Y, All, Custom"
    )

def fetch_request_status_distribution(cursor, time_range="All", start_date=None, end_date=None):
    date_filter, params = build_date_filter(time_range, start_date, end_date)
    date_filter_clause = f"WHERE {date_filter}" if date_filter else ""

    query = f"""
        SELECT
            rs.req_status AS status,
            COUNT(r.req_id) AS count
        FROM {SCHEMA_NAME}.request r
        JOIN {SCHEMA_NAME}.request_status rs
            ON r.req_status_id = rs.req_status_id
        {date_filter_clause}
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


def fetch_total_requests(cursor, time_range="All", start_date=None, end_date=None):
    date_filter, params = build_date_filter(time_range, start_date, end_date)
    date_filter_clause = f"WHERE {date_filter}" if date_filter else ""

    query = f"""
        SELECT COUNT(r.req_id) AS total_requests
        FROM {SCHEMA_NAME}.request r
        {date_filter_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    return (
        int(row["total_requests"])
        if row and row["total_requests"] is not None
        else 0
    )


def fetch_average_resolution_time_by_category(
    cursor,
    time_range="All",
    start_date=None,
    end_date=None
):
    date_filter, params = build_date_filter(time_range, start_date, end_date)
    date_filter_clause = f"AND {date_filter}" if date_filter else ""

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
          {date_filter_clause}
        GROUP BY hc.cat_name
        ORDER BY avg_hours DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "category": row["category"],
            "avg_hours": (
                float(row["avg_hours"])
                if row["avg_hours"] is not None
                else 0
            )
        }
        for row in rows
    ]

def lambda_handler(event, context):
    conn = None
    cursor = None

    event = event or {}

    time_range = event.get("time_range", "All")
    start_date = event.get("start_date")
    end_date = event.get("end_date")

    response_body = {
        "request_status_distribution": [],
        "total_requests": 0,
        "average_resolution_time_by_category": [],
        "sla": SLA
    }

    try:
        # Validate the requested date filter before opening the DB connection.
        build_date_filter(time_range, start_date, end_date)

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            response_body["request_status_distribution"] = (
                fetch_request_status_distribution(
                    cursor,
                    time_range,
                    start_date,
                    end_date
                )
            )
        except Exception as e:
            print(f"Request status distribution failed: {e}")

        try:
            response_body["total_requests"] = fetch_total_requests(
                cursor,
                time_range,
                start_date,
                end_date
            )
        except Exception as e:
            print(f"Total requests failed: {e}")

        try:
            response_body["average_resolution_time_by_category"] = (
                fetch_average_resolution_time_by_category(
                    cursor,
                    time_range,
                    start_date,
                    end_date
                )
            )
        except Exception as e:
            print(f"Average resolution time failed: {e}")

        return build_response(200, response_body)

    except ValueError as e:
        print(f"Invalid date filter: {e}")
        return build_response(400, response_body)

    except Exception as e:
        print(f"DB connection failed: {e}")
        return build_response(500, response_body)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    result = lambda_handler({"time_range": "All"}, None)
    print(json.dumps(result, indent=2))