import json
import math
import os

import boto3
import psycopg2

USERS_TABLE = os.environ.get(
    "USERS_TABLE",
    "users"
)

VOLUNTEERS_TABLE = os.environ.get(
    "VOLUNTEERS_TABLE",
    "volunteer_applications"
)

USER_ID_COLUMN = os.environ.get(
    "USER_ID_COLUMN",
    "user_id"
)

VOLUNTEER_USER_ID_COLUMN = os.environ.get(
    "VOLUNTEER_USER_ID_COLUMN",
    "user_id"
)

VOLUNTEER_STATUS_COLUMN = os.environ.get(
    "VOLUNTEER_STATUS_COLUMN",
    "application_status"
)

VOLUNTEER_UPDATED_COLUMN = os.environ.get(
    "VOLUNTEER_UPDATED_COLUMN",
    "last_updated_at"
)

REVIEW_STATUS = os.environ.get(
    "VOLUNTEER_REVIEW_STATUS",
    "UNDER_REVIEW"
)

RESPONSE_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
}

def parse_event_body(event):
    """
    Parse request parameters from direct Lambda invocation
    or API Gateway event body.
    """

    if not event:
        return {}

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, str):
        try:
            parsed_body = json.loads(body)

            if isinstance(parsed_body, dict):
                return parsed_body

            return {}

        except json.JSONDecodeError:
            return {}

    if isinstance(body, dict):
        return body

    return {}

def get_pagination_parameters(request_body):
    """Extract and validate page and page_size."""

    page = request_body.get("page", 1)
    page_size = request_body.get("page_size", 5)

    try:
        page = int(page)
        page_size = int(page_size)

    except (TypeError, ValueError):
        raise ValueError(
            "page and page_size must be integers"
        )

    if page < 1:
        raise ValueError(
            "page must be greater than or equal to 1"
        )

    if page_size < 1:
        raise ValueError(
            "page_size must be greater than or equal to 1"
        )

    if page_size > 100:
        raise ValueError(
            "page_size must not be greater than 100"
        )

    return page, page_size

def lambda_handler(event, context):
    """Handle Steward Dashboard Review Volunteers requests."""

    connection = None
    cursor = None

    try:

        http_method = (
            event.get("httpMethod")
            if isinstance(event, dict)
            else None
        )

        if http_method == "OPTIONS":
            return {
                "statusCode": 200,
                "headers": RESPONSE_HEADERS,
                "body": json.dumps({})
            }

        request_body = parse_event_body(event)

        page, page_size = get_pagination_parameters(
            request_body
        )

        offset = (page - 1) * page_size

        db_config = get_db_config()

        connection = psycopg2.connect(**db_config)
        cursor = connection.cursor()

        print("Database connected successfully.")

        total_records = get_total_review_records(
            cursor
        )

        review_records = get_review_records(
            cursor=cursor,
            page_size=page_size,
            offset=offset
        )

        if total_records == 0:
            total_pages = 0
        else:
            total_pages = math.ceil(
                total_records / page_size
            )

        response_data = {
            "data": review_records,
            "pagination": {
                "current_page": page,
                "page_size": page_size,
                "total_records": total_records,
                "total_pages": total_pages
            }
        }

        return {
            "statusCode": 200,
            "headers": RESPONSE_HEADERS,
            "body": json.dumps(response_data)
        }

    except ValueError as e:

        print("Validation error:", str(e))

        return {
            "statusCode": 400,
            "headers": RESPONSE_HEADERS,
            "body": json.dumps({
                "data": [],
                "pagination": {
                    "current_page": 1,
                    "page_size": 5,
                    "total_records": 0,
                    "total_pages": 0
                },
                "error": str(e)
            })
        }

    except Exception as e:

        print("ERROR:", str(e))

        safe_response = {
            "data": [],
            "pagination": {
                "current_page": 1,
                "page_size": 5,
                "total_records": 0,
                "total_pages": 0
            }
        }

        return {
            "statusCode": 500,
            "headers": RESPONSE_HEADERS,
            "body": json.dumps(safe_response)
        }

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()

        print("Database connection closed.")

def get_total_review_records(cursor):

    query = f"""
        SELECT COUNT(DISTINCT u.{USER_ID_COLUMN})
        FROM {USERS_TABLE} u
        JOIN {VOLUNTEERS_TABLE} v
            ON u.{USER_ID_COLUMN} = v.{VOLUNTEER_USER_ID_COLUMN}
        WHERE v.{VOLUNTEER_STATUS_COLUMN} = %s
    """

    cursor.execute(
        query,
        (REVIEW_STATUS,)
    )

    result = cursor.fetchone()

    if not result:
        return 0

    return int(result[0])

def get_review_records(cursor, page_size, offset):

    query = f"""
        SELECT
            u.{USER_ID_COLUMN} AS user_id,
            v.{VOLUNTEER_UPDATED_COLUMN} AS updated_time
        FROM {USERS_TABLE} u
        JOIN {VOLUNTEERS_TABLE} v
            ON u.{USER_ID_COLUMN} = v.{VOLUNTEER_USER_ID_COLUMN}
        WHERE v.{VOLUNTEER_STATUS_COLUMN} = %s
        ORDER BY
            v.{VOLUNTEER_UPDATED_COLUMN} DESC,
            u.{USER_ID_COLUMN} ASC
        LIMIT %s
        OFFSET %s
    """

    cursor.execute(
        query,
        (
            REVIEW_STATUS,
            page_size,
            offset
        )
    )

    rows = cursor.fetchall()

    results = []

    for row in rows:
        user_id = row[0]
        updated_time = row[1]

        results.append({
            "user_id": user_id,
            "updated_time": format_updated_time(
                updated_time
            ),
            "volunteer_review": "Review"
        })

    return results

def format_updated_time(value):
    """
    Convert database timestamp into an ISO-8601 UTC-style
    representation expected by the API.

    Example:

        2026-05-12 07:15:00
        ->
        2026-05-12T07:15:00Z
    """

    if value is None:
        return None

    if hasattr(value, "strftime"):
        return value.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    value = str(value)

    if value.endswith("Z"):
        return value

    if " " in value:
        value = value.replace(" ", "T", 1)

    return f"{value}Z"

def get_db_config():

    parameter_name = os.environ.get(
        "DB_PARAMETER_NAME"
    )

    if not parameter_name:
        raise ValueError(
            "DB_PARAMETER_NAME environment variable is not configured"
        )

    ssm = boto3.client(
        "ssm",
        region_name=os.environ.get(
            "AWS_REGION",
            "us-east-1"
        )
    )

    response = ssm.get_parameter(
        Name=parameter_name,
        WithDecryption=True
    )

    config = response["Parameter"]["Value"]

    return parse_db_parameter(config)

def parse_db_parameter(config):
    """
    The expected values contain host, user, password, database name,
    and port information.
    """

    config_list = [
        line.strip()
        for line in config.splitlines()
        if line.strip()
    ]

    parsed = {}

    for line in config_list:
        if "=" not in line:
            continue

        key, value = line.split("=", 1)

        key = key.strip().lower()
        value = value.strip().strip("'").strip('"')

        parsed[key] = value

    host = parsed.get("host")
    port = parsed.get("port")
    dbname = (
        parsed.get("dbname")
        or parsed.get("database")
        or parsed.get("db")
    )
    user = parsed.get("user")
    password = parsed.get("password")

    if not all([host, port, dbname, user, password]):
        return parse_existing_parameter_format(
            config_list
        )

    return {
        "host": host,
        "port": int(port),
        "dbname": dbname,
        "user": user,
        "password": password
    }

def parse_existing_parameter_format(config_list):

    try:
        host = config_list[1].split()[1][1:-2]
        user = config_list[2].split()[1][1:-2]
        password = config_list[3].split()[1][1:-2]
        dbname = config_list[4].split()[2][1:-2]
        port = int(config_list[5].split()[1][:-1])

    except (IndexError, ValueError) as e:
        raise ValueError(
            "Unable to parse database configuration from "
            "AWS Parameter Store"
        ) from e

    return {
        "host": host,
        "port": port,
        "dbname": dbname,
        "user": user,
        "password": password
    }
