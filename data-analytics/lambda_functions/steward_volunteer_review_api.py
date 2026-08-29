import json
import math
import os
from datetime import timezone

import boto3
import psycopg2


VIRGINIA_SCHEMA = "virginia_dev_saayam_rdbms"
IRELAND_SCHEMA = "ireland_dev_saayam_rdbms"

REVIEW_STATUS = "IN_REVIEW"
REVIEW_ACTION = "Review"

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 5
MAX_PAGE_SIZE = 100

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


REGIONS = {
    "VIRGINIA_DB_SSM_PARAMETER": VIRGINIA_SCHEMA,
    "IRELAND_DB_SSM_PARAMETER": IRELAND_SCHEMA,
}


def parse_event_body(event):
    """Return the request payload as a dictionary."""
    if not event:
        return {}

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, dict):
        return body

    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}

    return {}


def get_pagination_params(payload):
    """Read and validate page and page_size values."""

    try:
        page = int(payload.get("page", DEFAULT_PAGE))
    except (TypeError, ValueError):
        page = DEFAULT_PAGE

    try:
        page_size = int(payload.get("page_size", DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        page_size = DEFAULT_PAGE_SIZE

    if page < 1:
        page = DEFAULT_PAGE

    if page_size < 1:
        page_size = DEFAULT_PAGE_SIZE

    page_size = min(page_size, MAX_PAGE_SIZE)

    return page, page_size


def build_response(status_code, body):
    """Build an API Gateway compatible response."""
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


def get_db_config(parameter_name):
    """Read database credentials from AWS Parameter Store."""
    aws_region = os.environ.get("AWS_REGION", "us-east-1")

    ssm = boto3.client("ssm", region_name=aws_region)

    response = ssm.get_parameter(
        Name=parameter_name,
        WithDecryption=True,
    )

    credentials = json.loads(response["Parameter"]["Value"])

    return {
        "host": credentials["HOST"],
        "dbname": credentials["DATABASE NAME"],
        "user": credentials["USERNAME"],
        "password": credentials["PASSWORD"],
        "port": credentials["PORT"],
        "sslmode": "require",
    }


def connect_to_region(env_variable):
    """Create a database connection for a configured region."""
    parameter_name = os.environ.get(env_variable)

    if not parameter_name:
        return None

    db_config = get_db_config(parameter_name)

    return psycopg2.connect(**db_config)


def fetch_review_requests(cursor, schema):
    """
    Retrieve volunteer applications that require steward review.

    The table names are controlled internally while all variable query
    values are supplied through SQL parameters.
    """
    users_table = f"{schema}.users"
    applications_table = f"{schema}.volunteer_applications"

    query = f"""
        SELECT
            u.user_id,
            va.last_updated_at
        FROM {users_table} AS u
        JOIN {applications_table} AS va
            ON u.user_id = va.user_id
        WHERE va.application_status = %s
        ORDER BY va.last_updated_at DESC NULLS LAST
    """

    cursor.execute(query, (REVIEW_STATUS,))

    return cursor.fetchall()


def format_updated_time(value):
    """Convert a database timestamp to an ISO-8601 UTC string."""
    if value is None:
        return None

    if not hasattr(value, "isoformat"):
        return str(value)

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)

    return value.isoformat().replace("+00:00", "Z")


def paginate_records(records, page, page_size):
    """Return one requested page and its pagination metadata."""
    total_records = len(records)

    total_pages = (
        math.ceil(total_records / page_size)
        if total_records
        else 0
    )

    start = (page - 1) * page_size
    end = start + page_size

    page_records = records[start:end]

    data = [
        {
            "user_id": user_id,
            "updated_time": format_updated_time(updated_time),
            "volunteer_review": REVIEW_ACTION,
        }
        for user_id, updated_time in page_records
    ]

    pagination = {
        "current_page": page,
        "page_size": page_size,
        "total_records": total_records,
        "total_pages": total_pages,
    }

    return data, pagination


def lambda_handler(event, context):
    """AWS Lambda entry point for Steward volunteer review requests."""

    if event:
        request_context = event.get("requestContext", {})
        http = request_context.get("http", {})

        method = http.get("method") or event.get("httpMethod")

        if method == "OPTIONS":
            return build_response(200, {})

    payload = parse_event_body(event)
    page, page_size = get_pagination_params(payload)

    connections = []

    try:
        records = []

        for env_variable, schema in REGIONS.items():
            connection = connect_to_region(env_variable)

            if connection is None:
                continue

            connections.append(connection)
            cursor = connection.cursor()

            try:
                records.extend(
                    fetch_review_requests(cursor, schema)
                )
            finally:
                cursor.close()

        # Data from all regions must be merged before pagination.
        # None timestamps are pushed to the end.
        records.sort(
            key=lambda row: (
                row[1] is not None,
                row[1],
            ),
            reverse=True,
        )

        data, pagination = paginate_records(
            records,
            page,
            page_size,
        )

        return build_response(
            200,
            {
                "data": data,
                "pagination": pagination,
            },
        )

    except Exception:
        # Do not expose credentials, database details, or raw exceptions.
        return build_response(
            500,
            {
                "data": [],
                "pagination": {
                    "current_page": page,
                    "page_size": page_size,
                    "total_records": 0,
                    "total_pages": 0,
                },
                "error": "Unable to retrieve volunteer review requests.",
            },
        )

    finally:
        for connection in connections:
            connection.close()