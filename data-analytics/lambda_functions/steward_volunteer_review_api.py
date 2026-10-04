"""
steward_volunteer_review_api.py

Steward Dashboard - Review Volunteers.

Returns the paginated list of volunteer applications awaiting steward review,
merged across the Virginia and Ireland databases, newest updated first.

Request payload:
    {"page": 1, "page_size": 5}

Response body:
    {
        "data": [
            {
                "user_id": "SID-00-000-000-001",
                "updated_time": "2026-05-12T07:15:00Z",
                "volunteer_review": "Review"
            }
        ],
        "pagination": {
            "current_page": 1,
            "page_size": 5,
            "total_records": 20,
            "total_pages": 4
        }
    }

Environment variables (no credentials or parameter paths are hardcoded):
    DB_PARAM_PATH_VIRGINIA   SSM path for the Virginia DB config
    DB_PARAM_PATH_IRELAND    SSM path for the Ireland DB config
    REVIEW_REGIONS           Comma separated, defaults to "Virginia,Ireland"
    REVIEW_APPLICATION_STATUSES
                             Comma separated application_status values that
                             count as needing review. Defaults to
                             IN_REVIEW,UNDER_REVIEW (see the note below).
    AWS_SSM_REGION           Defaults to us-east-1
    LOG_LEVEL                Defaults to INFO
"""

import json
import logging
import math
import os
from datetime import date, datetime

import boto3
import psycopg2

LOGGER = logging.getLogger()
LOGGER.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REAL_TABLE_USERS_VIRGINIA = "virginia_dev_saayam_rdbms.users"
REAL_TABLE_VOLUNTEER_APPLICATIONS_VIRGINIA = (
    "virginia_dev_saayam_rdbms.volunteer_applications"
)

REAL_TABLE_USERS_IRELAND = "ireland_dev_saayam_rdbms.users"
REAL_TABLE_VOLUNTEER_APPLICATIONS_IRELAND = (
    "ireland_dev_saayam_rdbms.volunteer_applications"
)

REGION_TABLES = {
    "Virginia": {
        "users": REAL_TABLE_USERS_VIRGINIA,
        "applications": REAL_TABLE_VOLUNTEER_APPLICATIONS_VIRGINIA,
    },
    "Ireland": {
        "users": REAL_TABLE_USERS_IRELAND,
        "applications": REAL_TABLE_VOLUNTEER_APPLICATIONS_IRELAND,
    },
}

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 5
MAX_PAGE_SIZE = 100
VOLUNTEER_REVIEW_ACTION = "Review"

DEFAULT_REGIONS = "Virginia,Ireland"

# app_status_type is ENUM ('STARTED', 'IN_REVIEW', 'ACCEPTED', 'REJECTED').
# The schema migration is applied manually per environment, and older
# environments still carry the previous values (DRAFT, SUBMITTED,
# UNDER_REVIEW, APPROVED). Both review values are listed so the endpoint
# works either side of the migration; they never coexist in one database.
# Drop UNDER_REVIEW once every environment is migrated.
DEFAULT_REVIEW_STATUSES = "IN_REVIEW,UNDER_REVIEW"

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}

GENERIC_ERROR_MESSAGE = "Unable to retrieve volunteer review requests at this time."


class ValidationError(ValueError):
    """Raised when the incoming payload fails validation."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def get_db_config(db):
    """Read a regional DB config from SSM. The path comes from the env."""
    env_name = f"DB_PARAM_PATH_{db.upper()}"
    parameter_name = os.environ.get(env_name)
    if not parameter_name:
        raise ValueError(f"Missing required environment variable: {env_name}")

    ssm = boto3.client("ssm", region_name=os.environ.get("AWS_SSM_REGION", "us-east-1"))
    response = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
    config = response["Parameter"]["Value"]

    try:
        parsed = json.loads(config)
        return {
            "host": parsed["host"],
            "port": int(parsed.get("port", 5432)),
            "dbname": parsed["dbname"],
            "user": parsed["user"],
            "password": parsed["password"],
        }
    except (json.JSONDecodeError, KeyError):
        # Same positional parsing the other analytics Lambdas use, for
        # parameter values that are not strict JSON.
        config_list = [line.strip() for line in config.splitlines()]
        return {
            "host": config_list[1].split()[1][1:-2],
            "port": int(config_list[5].split()[1][:-1]),
            "dbname": config_list[4].split()[2][1:-2],
            "user": config_list[2].split()[1][1:-2],
            "password": config_list[3].split()[1][1:-2],
        }


def get_regions():
    regions = [
        region.strip()
        for region in os.environ.get("REVIEW_REGIONS", DEFAULT_REGIONS).split(",")
        if region.strip()
    ]
    unknown = [region for region in regions if region not in REGION_TABLES]
    if unknown:
        raise ValueError(f"Unknown region(s) in REVIEW_REGIONS: {unknown}")
    if not regions:
        raise ValueError("REVIEW_REGIONS resolved to an empty list.")
    return regions


def get_review_statuses():
    statuses = [
        status.strip().upper()
        for status in os.environ.get(
            "REVIEW_APPLICATION_STATUSES", DEFAULT_REVIEW_STATUSES
        ).split(",")
        if status.strip()
    ]
    if not statuses:
        raise ValueError("REVIEW_APPLICATION_STATUSES resolved to an empty list.")
    return statuses


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------

def parse_event_body(event):
    if not event:
        return {}

    body = event.get("body")

    if body is None:
        query_params = event.get("queryStringParameters")
        if isinstance(query_params, dict) and query_params:
            return query_params
        return event

    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body, dict):
        return body

    return {}


def _coerce_positive_int(value, field, default, maximum=None):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValidationError(f"'{field}' must be a positive integer.")
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError(f"'{field}' must be a positive integer.")
    if number < 1:
        raise ValidationError(f"'{field}' must be greater than zero.")
    if maximum is not None and number > maximum:
        raise ValidationError(f"'{field}' cannot be greater than {maximum}.")
    return number


def parse_pagination(request_body):
    page = _coerce_positive_int(request_body.get("page"), "page", DEFAULT_PAGE)
    page_size = _coerce_positive_int(
        request_body.get("page_size"), "page_size", DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
    )
    return page, page_size


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_timestamp(value):
    """Render a DB timestamp as ISO 8601 UTC, e.g. 2026-05-12T07:15:00Z.

    last_updated_at is stored in UTC, so the Z suffix is appended rather than
    converted. The frontend is responsible for rendering in the steward's
    local timezone.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "").replace(" ", "T"))
        except ValueError:
            return text
        return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


def build_pagination(page, page_size, total_records):
    return {
        "current_page": page,
        "page_size": page_size,
        "total_records": total_records,
        "total_pages": math.ceil(total_records / page_size) if total_records else 0,
    }


def empty_payload(page=DEFAULT_PAGE, page_size=DEFAULT_PAGE_SIZE):
    return {"data": [], "pagination": build_pagination(page, page_size, 0)}


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------

def get_review_requests_for_region(cursor, users, applications, statuses, row_limit):
    """Return (rows, total_records) for one regional database.

    row_limit is offset + page_size, so the caller has enough rows from each
    region to build the requested page after merging.
    """
    placeholders = ", ".join(["%s"] * len(statuses))

    count_query = f"""
        SELECT COUNT(*)
        FROM {applications} va
        JOIN {users} u
            ON u.user_id = va.user_id
        WHERE va.application_status::text IN ({placeholders})
    """
    cursor.execute(count_query, tuple(statuses))
    count_row = cursor.fetchone()
    total_records = int(count_row[0]) if count_row else 0

    if total_records == 0:
        return [], 0

    select_query = f"""
        SELECT u.user_id,
               va.last_updated_at
        FROM {applications} va
        JOIN {users} u
            ON u.user_id = va.user_id
        WHERE va.application_status::text IN ({placeholders})
        ORDER BY va.last_updated_at DESC, u.user_id DESC
        LIMIT %s
    """
    cursor.execute(select_query, tuple(statuses) + (row_limit,))
    rows = [
        {
            "user_id": row[0],
            "updated_time": format_timestamp(row[1]),
            "volunteer_review": VOLUNTEER_REVIEW_ACTION,
        }
        for row in cursor.fetchall()
    ]
    return rows, total_records


def merge_review_requests(rows_by_region, page, page_size):
    """Merge regional pages, re-sort, and slice out the requested page."""
    merged = []
    for rows in rows_by_region:
        merged.extend(rows)

    merged.sort(
        key=lambda row: (row["updated_time"] or "", row["user_id"] or ""), reverse=True
    )

    offset = (page - 1) * page_size
    return merged[offset: offset + page_size]


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    connections = []
    page, page_size = DEFAULT_PAGE, DEFAULT_PAGE_SIZE

    try:
        request_body = parse_event_body(event)
        page, page_size = parse_pagination(request_body)
    except ValidationError as exc:
        LOGGER.warning("Validation failed: %s", exc)
        return build_response(
            400, {"message": str(exc), **empty_payload(page, page_size)}
        )

    try:
        regions = get_regions()
        statuses = get_review_statuses()
        row_limit = (page - 1) * page_size + page_size

        rows_by_region = []
        total_records = 0

        for region in regions:
            config = get_db_config(region)
            connection = psycopg2.connect(**config)
            connections.append((region, connection))
            LOGGER.info("%s database connected successfully.", region)

            with connection.cursor() as cursor:
                rows, count = get_review_requests_for_region(
                    cursor,
                    REGION_TABLES[region]["users"],
                    REGION_TABLES[region]["applications"],
                    statuses,
                    row_limit,
                )
            rows_by_region.append(rows)
            total_records += count

        data = merge_review_requests(rows_by_region, page, page_size)

        return build_response(
            200,
            {
                "data": data,
                "pagination": build_pagination(page, page_size, total_records),
            },
        )

    except Exception:
        LOGGER.exception("Error retrieving volunteer review requests.")
        return build_response(
            500, {"message": GENERIC_ERROR_MESSAGE, **empty_payload(page, page_size)}
        )

    finally:
        for region, connection in connections:
            try:
                connection.close()
                LOGGER.info("%s database connection closed.", region)
            except Exception:
                LOGGER.warning("Failed to close %s connection.", region)


if __name__ == "__main__":
    print(lambda_handler({"page": 1, "page_size": 5}, None))
