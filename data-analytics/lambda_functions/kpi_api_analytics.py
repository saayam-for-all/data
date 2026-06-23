import json
import boto3
import psycopg2
from psycopg2.extras import RealDictCursor

SCHEMA = "virginia_dev_saayam_rdbms"

TABLE_REQUEST         = f"{SCHEMA}.request"
TABLE_REQUEST_STATUS  = f"{SCHEMA}.request_status"
TABLE_HELP_CATEGORIES = f"{SCHEMA}.help_categories"

SLA = {
    "target_days": 10,
    "target_hours": 240,
    "warning_days": 8.33,
    "warning_hours": 200
}


def get_default_response():
    return {
        "request_status_distribution": [],
        "total_requests": 0,
        "average_resolution_time_by_category": [],
        "sla": SLA
    }


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


def get_db_config():
    # Credentials stored in SSM Parameter Store (same path as other lambdas)
    ssm = boto3.client("ssm", region_name="us-east-1")
    response = ssm.get_parameter(
        Name="/dev/saayam/db/Virginia/Analytics/user",
        WithDecryption=True
    )

    config = response["Parameter"]["Value"]
    config_list = [line.strip() for line in config.splitlines()]

    host     = config_list[1].split()[1][1:-2]
    port     = int(config_list[5].split()[1][:-1])
    dbname   = config_list[4].split()[2][1:-2]
    user     = config_list[2].split()[1][1:-2]
    password = config_list[3].split()[1][1:-2]

    return {
        "host": host,
        "port": port,
        "dbname": dbname,
        "user": user,
        "password": password
    }


def fetch_request_status_distribution(cursor):
    query = f"""
        SELECT
            rs.req_status AS status,
            COUNT(r.req_id) AS count
        FROM {TABLE_REQUEST} r
        JOIN {TABLE_REQUEST_STATUS} rs
            ON r.req_status_id = rs.req_status_id
        GROUP BY rs.req_status
        ORDER BY rs.req_status;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [{"status": row["status"], "count": int(row["count"])} for row in rows]


def fetch_total_requests(cursor):
    query = f"SELECT COUNT(req_id) AS total_requests FROM {TABLE_REQUEST};"
    cursor.execute(query)
    row = cursor.fetchone()
    return int(row["total_requests"]) if row and row["total_requests"] is not None else 0


def fetch_average_resolution_time_by_category(cursor):
    # Only include resolved requests where both dates are present
    # serviced_date - submission_date gives a positive interval
    query = f"""
        SELECT
            hc.cat_name AS category,
            ROUND(
                AVG(
                    EXTRACT(EPOCH FROM (r.serviced_date - r.submission_date)) / 3600
                )::numeric,
                2
            ) AS avg_hours
        FROM {TABLE_REQUEST} r
        JOIN {TABLE_HELP_CATEGORIES} hc
            ON r.req_cat_id = hc.cat_id
        JOIN {TABLE_REQUEST_STATUS} rs
            ON r.req_status_id = rs.req_status_id
        WHERE r.submission_date IS NOT NULL
          AND r.serviced_date IS NOT NULL
          AND r.serviced_date >= r.submission_date
          AND UPPER(rs.req_status) IN ('RESOLVED', 'COMPLETED')
        GROUP BY hc.cat_name
        ORDER BY avg_hours DESC;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [
        {
            "category": row["category"],
            "avg_hours": float(row["avg_hours"]) if row["avg_hours"] is not None else 0.0
        }
        for row in rows
    ]


def lambda_handler(event, context):
    conn = None
    cursor = None
    response_body = get_default_response()

    try:
        db_config = get_db_config()
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        print("Virginia database connected successfully.")

        try:
            response_body["request_status_distribution"] = fetch_request_status_distribution(cursor)
        except Exception as err:
            print(f"Status distribution query failed: {err}")
            response_body["request_status_distribution"] = []

        try:
            response_body["total_requests"] = fetch_total_requests(cursor)
        except Exception as err:
            print(f"Total request count query failed: {err}")
            response_body["total_requests"] = 0

        try:
            response_body["average_resolution_time_by_category"] = fetch_average_resolution_time_by_category(cursor)
        except Exception as err:
            print(f"Average resolution time query failed: {err}")
            response_body["average_resolution_time_by_category"] = []

        return build_response(200, response_body)

    except Exception as err:
        print(f"DB connection failed: {err}")
        return build_response(500, response_body)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        print("Virginia database connection closed.")


if __name__ == "__main__":
    result = lambda_handler({}, None)
    print(json.dumps(result, indent=2))
