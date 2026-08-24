import json
import logging
import math
import os

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_db_connection():
    """Establish local PostgreSQL database connection."""
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            database=os.environ.get("DB_NAME", "saayam_db"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", "postgres"),
            port=os.environ.get("DB_PORT", "5432"),
        )
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        raise e


def fetch_volunteer_reviews(cursor, page, page_size):
    """Retrieve paginated volunteer requests requiring steward review."""
    offset = (page - 1) * page_size

    # Total Count Query
    count_query = """
        SELECT COUNT(v.id) AS total_records
        FROM volunteers v
        JOIN users u ON v.user_id = u.id
        WHERE LOWER(v.status) IN ('pending', 'under_review', 'requires_review', 'review');
    """
    cursor.execute(count_query)
    count_result = cursor.fetchone()
    total_records = count_result["total_records"] if count_result else 0

    total_pages = math.ceil(total_records / page_size) if total_records > 0 else 0

    # Paginated Data Query sorted by latest updated_at
    data_query = """
        SELECT 
            COALESCE(u.id::text, u.saayam_id, v.user_id::text) AS user_id,
            TO_CHAR(COALESCE(v.updated_at, v.created_at), 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS updated_time,
            'Review' AS volunteer_review
        FROM volunteers v
        JOIN users u ON v.user_id = u.id
        WHERE LOWER(v.status) IN ('pending', 'under_review', 'requires_review', 'review')
        ORDER BY COALESCE(v.updated_at, v.created_at) DESC
        LIMIT %s OFFSET %s;
    """
    cursor.execute(data_query, (page_size, offset))
    records = cursor.fetchall() or []

    return {
        "data": records,
        "pagination": {
            "current_page": page,
            "page_size": page_size,
            "total_records": total_records,
            "total_pages": total_pages,
        },
    }


def lambda_handler(event, context):
    """Main Lambda handler for Review Volunteers API."""
    try:
        payload = {}
        if event.get("body"):
            payload = (
                json.loads(event["body"])
                if isinstance(event["body"], str)
                else event["body"]
            )
        else:
            payload = event

        page = max(1, int(payload.get("page", 1)))
        page_size = max(1, int(payload.get("page_size", 5)))

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        result = fetch_volunteer_reviews(cursor, page, page_size)

        cursor.close()
        conn.close()

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": result,
        }

    except psycopg2.Error as db_err:
        logger.error(f"Database Error: {str(db_err)}")
        return {
            "statusCode": 500,
            "body": {
                "error_code": "DE 1001",
                "message": "Database execution error.",
            },
        }
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}")
        return {
            "statusCode": 500,
            "body": {
                "error_code": "DE 1000",
                "message": "Internal server execution error.",
            },
        }