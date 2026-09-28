import json
import math
import os

import psycopg2


SCHEMA_NAME = os.getenv("DB_SCHEMA", "virginia_dev_saayam_rdbms")
USERS_TABLE = f"{SCHEMA_NAME}.users"
VOLUNTEER_APPLICATIONS_TABLE = f"{SCHEMA_NAME}.volunteer_applications"


def parse_event_body(event):
    """Parse Lambda event body into a dictionary."""
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


def get_db_connection():
    """Create and return a PostgreSQL connection."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "saayam_local"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", "5432"),
    )


def build_response(status_code, body):
    """Build the Lambda API response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def get_review_volunteers(cursor, page, page_size):
    """Fetch volunteer applications requiring steward review."""
    offset = (page - 1) * page_size

    count_query = f"""
        SELECT COUNT(*)
        FROM {VOLUNTEER_APPLICATIONS_TABLE} va
        JOIN {USERS_TABLE} u
            ON u.user_id = va.user_id
        WHERE va.application_status = %s
    """

    cursor.execute(count_query, ("UNDER_REVIEW",))
    total_records = cursor.fetchone()[0]

    data_query = f"""
        SELECT
            u.user_id,
            TO_CHAR(
                va.last_updated_at::timestamp,
                'YYYY-MM-DD"T"HH24:MI:SS"Z"'
            ) AS updated_time
        FROM {VOLUNTEER_APPLICATIONS_TABLE} va
        JOIN {USERS_TABLE} u
            ON u.user_id = va.user_id
        WHERE va.application_status = %s
        ORDER BY va.last_updated_at::timestamp DESC
        LIMIT %s OFFSET %s
    """

    cursor.execute(
        data_query,
        ("UNDER_REVIEW", page_size, offset),
    )

    rows = cursor.fetchall()

    data = [
        {
            "user_id": row[0],
            "updated_time": row[1],
            "volunteer_review": "Review",
        }
        for row in rows
    ]

    total_pages = (
        math.ceil(total_records / page_size)
        if total_records > 0
        else 0
    )

    return {
        "data": data,
        "pagination": {
            "current_page": page,
            "page_size": page_size,
            "total_records": total_records,
            "total_pages": total_pages,
        },
    }


def lambda_handler(event, context):
    """AWS Lambda entry point."""
    connection = None
    cursor = None

    try:
        body = parse_event_body(event)

        page = int(body.get("page", 1))
        page_size = int(body.get("page_size", 5))

        if page < 1 or page_size < 1:
            return build_response(
                400,
                {"message": "page and page_size must be greater than 0"},
            )

        connection = get_db_connection()
        cursor = connection.cursor()

        result = get_review_volunteers(
            cursor,
            page,
            page_size,
        )

        return build_response(200, result)

    except (ValueError, TypeError):
        return build_response(
            400,
            {"message": "Invalid pagination values"},
        )

    except Exception as exc:
        print("ERROR:", str(exc))
        return build_response(
            500,
            {"message": "Unable to retrieve volunteer applications"},
        )

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()


if __name__ == "__main__":
    test_event = {
        "body": json.dumps(
            {
                "page": 1,
                "page_size": 5,
            }
        )
    }

    print(lambda_handler(test_event, None))