import json
import psycopg2
import os

# Virginia RDS table references
REAL_TABLE_REQUEST = "virginia_dev_saayam_rdbms.request"
REAL_TABLE_REQUEST_STATUS = "virginia_dev_saayam_rdbms.request_status"
REAL_TABLE_HELP_CATEGORIES = "virginia_dev_saayam_rdbms.help_categories"


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

        response_body = {
            "request_status_distribution": status_distribution,
            "total_requests": total_requests
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