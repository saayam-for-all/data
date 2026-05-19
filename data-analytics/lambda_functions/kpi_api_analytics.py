import json
import psycopg2
import os

# Virginia RDS table references
REAL_TABLE_REQUEST = "virginia_dev_saayam_rdbms.request"
REAL_TABLE_REQUEST_STATUS = "virginia_dev_saayam_rdbms.request_status"
REAL_TABLE_HELP_CATEGORIES = "virginia_dev_saayam_rdbms.help_categories"

# SLA constants (dashboard-defined thresholds)
SLA_TARGET_DAYS = 10
SLA_TARGET_HOURS = 240
SLA_WARNING_DAYS = 8.33
SLA_WARNING_HOURS = 200


def lambda_handler(event, context):
    conn = None
    cursor = None

    DB_CONFIG = {
        "host": os.environ['host'],
        "port": os.environ['port'],
        "dbname": os.environ['dbname'],
        "user": os.environ['user'],
        "password": os.environ['password']
    }

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        print("Successfully connected to the database")

        status_distribution, total_requests = get_request_status_distribution(cursor)
        avg_resolution = get_average_resolution_time_by_category(cursor)

        response_body = {
            "request_status_distribution": status_distribution,
            "total_requests": total_requests,
            "average_resolution_time_by_category": avg_resolution,
            "sla": {
                "target_days": SLA_TARGET_DAYS,
                "target_hours": SLA_TARGET_HOURS,
                "warning_days": SLA_WARNING_DAYS,
                "warning_hours": SLA_WARNING_HOURS
            }
        }

        return {
            "statusCode": 200,
            "body": json.dumps(response_body)
        }

    except Exception as e:
        print("ERROR:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Could not connect to database"})
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        print("Database connection closed")


def get_request_status_distribution(cursor):
    """
    Counts requests grouped by their status label (e.g. CREATED, IN_PROGRESS, RESOLVED).
    Joins request -> request_status to resolve the status name from the FK.
    Returns (distribution_list, total_count).
    """
    try:
        query = f"""
            SELECT rs.req_status, COUNT(r.req_id) AS count
            FROM {REAL_TABLE_REQUEST} r
            JOIN {REAL_TABLE_REQUEST_STATUS} rs
                ON r.req_status_id = rs.req_status_id
            GROUP BY rs.req_status
            ORDER BY count DESC
        """
        cursor.execute(query)
        rows = cursor.fetchall()

        distribution = [
            {"status": row[0], "count": int(row[1])}
            for row in rows
        ]
        total = sum(item["count"] for item in distribution)

        return distribution, total

    except Exception as e:
        print("Error in get_request_status_distribution:", str(e))
        return [], 0


def get_average_resolution_time_by_category(cursor):
    """
    Calculates average resolution time (in hours) per help category.
    Uses submission_date and serviced_date from the request table.
    Only includes requests where both dates are present.
    Joins request -> help_categories to get the category name.
    """
    try:
        query = f"""
            SELECT
                hc.cat_name AS category,
                ROUND(
                    AVG(
                        EXTRACT(EPOCH FROM (r.serviced_date - r.submission_date)) / 3600
                    )::numeric,
                    2
                ) AS avg_hours
            FROM {REAL_TABLE_REQUEST} r
            JOIN {REAL_TABLE_HELP_CATEGORIES} hc
                ON r.req_cat_id = hc.cat_id
            WHERE r.submission_date IS NOT NULL
              AND r.serviced_date IS NOT NULL
            GROUP BY hc.cat_name
            ORDER BY avg_hours DESC
        """
        cursor.execute(query)
        rows = cursor.fetchall()

        return [
            {"category": row[0], "avg_hours": float(row[1])}
            for row in rows
        ]

    except Exception as e:
        print("Error in get_average_resolution_time_by_category:", str(e))
        return []