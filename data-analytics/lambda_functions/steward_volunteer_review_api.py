import json
import logging
import os
from contextlib import closing
from datetime import timezone

import boto3
import psycopg2
from psycopg2 import sql

LOGGER = logging.getLogger(__name__)


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": body,
    }


def parse_pagination(event):
    if not isinstance(event, dict):
        raise ValueError("Request must be a JSON object.")
    payload = event.get("body", event)
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            raise ValueError("Request body must be valid JSON.") from None
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    page, page_size = payload.get("page", 1), payload.get("page_size", 5)
    if type(page) is not int or page < 1:
        raise ValueError("page must be a positive integer.")
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("page_size must be an integer between 1 and 100.")
    if (page - 1) * page_size > 9223372036854775807:
        raise ValueError("Requested page is too large.")
    return page, page_size


def get_review_statuses():
    statuses = json.loads(os.environ["STEWARD_REVIEW_STATUSES"])
    if (not isinstance(statuses, list) or not statuses
            or any(not isinstance(s, str) or not s.strip() for s in statuses)):
        raise ValueError("Review statuses must be a nonempty JSON list of strings.")
    return list(dict.fromkeys(statuses))


def get_db_connection():
    parameter = boto3.client("ssm").get_parameter(
        Name=os.environ["DB_CONFIG_PARAMETER"], WithDecryption=True
    )
    config = json.loads(parameter["Parameter"]["Value"])
    return psycopg2.connect(
        host=config["HOST"], port=config["PORT"],
        dbname=config["DATABASE NAME"], user=config["USERNAME"],
        password=config["PASSWORD"], sslmode="require", connect_timeout=10,
        options="-c timezone=UTC -c statement_timeout=15000",
    )


def format_updated_time(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def get_review_queue(cursor, schema, statuses, page, page_size):
    tables = {
        "users": sql.Identifier(schema, "users"),
        "applications": sql.Identifier(schema, "volunteer_applications"),
    }
    query = sql.SQL("""
        WITH review_queue AS (
            SELECT u.user_id, va.last_updated_at
            FROM {users} AS u
            JOIN {applications} AS va ON va.user_id = u.user_id
            WHERE va.application_status = ANY(%s)
        ), page_rows AS (
            SELECT user_id, last_updated_at
            FROM review_queue
            ORDER BY last_updated_at DESC NULLS LAST, user_id ASC
            LIMIT %s OFFSET %s
        )
        SELECT p.user_id, p.last_updated_at, totals.total_records
        FROM (SELECT COUNT(*) AS total_records FROM review_queue) AS totals
        LEFT JOIN page_rows AS p ON TRUE
        ORDER BY p.last_updated_at DESC NULLS LAST, p.user_id ASC
    """).format(**tables)
    cursor.execute(query, (statuses, page_size, (page - 1) * page_size))
    rows = cursor.fetchall()
    total = rows[0][2]
    return {
        "data": [
            {"user_id": user_id, "updated_time": format_updated_time(updated),
             "volunteer_review": "Review"}
            for user_id, updated, _ in rows if user_id is not None
        ],
        "pagination": {
            "current_page": page, "page_size": page_size,
            "total_records": total,
            "total_pages": (total + page_size - 1) // page_size,
        },
    }


def lambda_handler(event, context):
    try:
        page, page_size = parse_pagination(event)
    except ValueError as exc:
        return response(400, {"error": str(exc)})

    try:
        statuses = get_review_statuses()
        schema = os.environ["DB_SCHEMA"]
        if not schema.strip():
            raise ValueError("DB_SCHEMA is required.")
        with closing(get_db_connection()) as connection:
            connection.set_session(readonly=True)
            with connection.cursor() as cursor:
                result = get_review_queue(cursor, schema, statuses, page, page_size)
        return response(200, result)
    except Exception:
        LOGGER.error("Steward volunteer review request failed")
        return response(500, {"error": "Unable to retrieve volunteer applications."})
