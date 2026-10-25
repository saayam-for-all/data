"""
Steward Dashboard - Review Volunteers AWS Lambda API (issue #273)

Returns the paginated queue of volunteer applications waiting on a steward's
review. Rows come from `users` joined to `volunteer_applications` on user_id,
filtered to the statuses that actually need review, newest first.

Only the three reviewer-facing fields are returned. The user_id is what the
frontend hands back to the Review action.

Note on the source table: the issue text says `volunteers_details`. No such
table exists. The closest name is `volunteer_details`, but it has no status
or stage column, so it cannot express "requires review" at all. The review
state lives in `volunteer_applications.application_status`, which is what
this uses. See REVIEW_STATUSES below if the team confirms a different set.

Request payload (event body, or a plain dict when invoked directly):
    {
        "page": 1,          # optional, defaults to 1
        "page_size": 5      # optional, defaults to 10, capped at 100
    }

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

Local run (no AWS needed) - set DB_HOST/DB_NAME/DB_USER/DB_PASSWORD from
.env.example and point them at the docker-compose Postgres:

    python steward_volunteer_review_api.py
"""
import json
import math
import os
import re
from datetime import datetime, timezone

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor

# Schema is environment-configurable, matching the ORG_ANALYTICS_SCHEMA
# pattern already used by src/main.py.
SCHEMA_NAME = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")

# Application statuses that put a volunteer in the steward's review queue.
# Change this one tuple if the team confirms a different set.
REVIEW_STATUSES = ("UNDER_REVIEW",)

# The action label the frontend renders as a button. Constant by design -
# the issue's contract shows a fixed "Review" action, not a status echo.
VOLUNTEER_REVIEW_ACTION = "Review"

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100

# Schema names cannot be bound as query parameters, so the value is checked
# against this before it is ever interpolated into SQL.
_SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Warm-invocation cache so repeat calls don't hit Parameter Store every time.
_CREDENTIALS_CACHE = {}


def parse_event_body(event):
    """
    Normalizes the incoming event so the handler reads parameters the same
    way whether it arrived through API Gateway (JSON-encoded string body)
    or as a plain dict from a direct invoke or a test.
    """
    if not event:
        return {}

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    if isinstance(body, dict):
        return body

    return {}


def get_pagination_params(request_body):
    """
    Reads and sanitizes page / page_size. Bad or out-of-range values fall
    back to defaults rather than raising, so a malformed client value
    degrades into a normal first page instead of failing the request.
    """
    try:
        page = int(request_body.get("page", DEFAULT_PAGE))
    except (TypeError, ValueError):
        page = DEFAULT_PAGE

    try:
        page_size = int(request_body.get("page_size", DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        page_size = DEFAULT_PAGE_SIZE

    if page < 1:
        page = DEFAULT_PAGE

    if page_size < 1:
        page_size = DEFAULT_PAGE_SIZE
    elif page_size > MAX_PAGE_SIZE:
        page_size = MAX_PAGE_SIZE

    return page, page_size


def _review_source_sql():
    """
    Builds the shared FROM + WHERE fragment used by both the count query and
    the page query. Keeping it in one place is what stops the two from
    drifting apart and reporting a total that doesn't match the rows.

    Caller must bind one parameter: the list of review statuses.
    """
    schema = SCHEMA_NAME
    if not _SCHEMA_PATTERN.match(schema or ""):
        raise ValueError(f"Invalid schema name: {schema!r}")

    # application_status is a Postgres enum, so it is cast to text before
    # being compared against the bound status list.
    return f"""
        FROM {schema}.users u
        JOIN {schema}.volunteer_applications va
            ON u.user_id = va.user_id
        WHERE va.application_status::text = ANY(%s)
    """


def _status_params():
    return list(REVIEW_STATUSES)


def _to_iso_utc(value):
    """
    Formats a timestamp as ISO 8601 in UTC, e.g. 2026-05-12T07:15:00Z.

    volunteer_applications.last_updated_at is `timestamp without time zone`,
    so naive values are read as UTC. Aware values are converted.
    """
    if value is None:
        return None

    if isinstance(value, str):
        return value

    if not isinstance(value, datetime):
        return str(value)

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)

    return value.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ssm_credentials():
    """
    Pulls DB credentials from Parameter Store. The parameter name itself is
    not hardcoded - it comes from DB_SSM_PARAM, per the issue's requirement
    not to hardcode credentials or Parameter Store paths.
    """
    param_name = os.environ.get("DB_SSM_PARAM")
    if not param_name:
        raise RuntimeError(
            "DB_SSM_PARAM is not set. Point it at the Parameter Store entry "
            "holding the analytics DB credentials, or set DB_HOST / DB_NAME / "
            "DB_USER / DB_PASSWORD to run against a local Postgres."
        )

    if param_name in _CREDENTIALS_CACHE:
        return _CREDENTIALS_CACHE[param_name]

    ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    response = ssm.get_parameter(Name=param_name, WithDecryption=True)
    creds = json.loads(response["Parameter"]["Value"])

    config = {
        "host": creds["HOST"],
        "port": creds["PORT"],
        "database": creds["DATABASE NAME"],
        "user": creds["USERNAME"],
        "password": creds["PASSWORD"],
    }
    _CREDENTIALS_CACHE[param_name] = config
    return config


def get_db_connection():
    """
    Opens a Postgres connection. If DB_HOST is set the local .env values are
    used directly, which is how this gets tested against the docker-compose
    Postgres without any AWS access. Otherwise credentials come from
    Parameter Store. Nothing is hardcoded in either path.
    """
    if os.environ.get("DB_HOST"):
        return psycopg2.connect(
            host=os.environ["DB_HOST"],
            port=os.environ.get("DB_PORT", "5432"),
            database=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
        )

    return psycopg2.connect(sslmode="require", **_ssm_credentials())


def get_total_review_count(cursor):
    """
    Counts the volunteer applications currently awaiting steward review.
    Drives total_records / total_pages in the response.
    """
    query = "SELECT COUNT(*) AS total" + _review_source_sql()
    cursor.execute(query, (_status_params(),))
    row = cursor.fetchone()
    return int(row["total"]) if row and row.get("total") is not None else 0


def get_volunteer_reviews(cursor, page, page_size):
    """
    Fetches one page of the review queue, newest first.

    ORDER BY carries a user_id tiebreaker on purpose: ordering by timestamp
    alone leaves rows with identical timestamps in an undefined order, which
    lets a row repeat on one page and vanish from the next as the client
    walks the offsets.

    page_size / offset are bound as parameters, never interpolated.
    """
    offset = (page - 1) * page_size

    query = f"""
        SELECT
            u.user_id AS user_id,
            va.last_updated_at AS updated_time
        {_review_source_sql()}
        ORDER BY va.last_updated_at DESC NULLS LAST, va.user_id DESC
        LIMIT %s OFFSET %s
    """
    cursor.execute(query, (_status_params(), page_size, offset))
    rows = cursor.fetchall()

    return [
        {
            "user_id": row["user_id"],
            "updated_time": _to_iso_utc(row["updated_time"]),
            "volunteer_review": VOLUNTEER_REVIEW_ACTION,
        }
        for row in rows
    ]


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }


def lambda_handler(event, context):
    conn = None
    cursor = None

    request_body = parse_event_body(event)
    page, page_size = get_pagination_params(request_body)

    def envelope(data, total_records):
        return {
            "data": data,
            "pagination": {
                "current_page": page,
                "page_size": page_size,
                "total_records": total_records,
                "total_pages": math.ceil(total_records / page_size) if total_records else 0,
            },
        }

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        total_records = get_total_review_count(cursor)
        data = get_volunteer_reviews(cursor, page, page_size) if total_records else []

        return build_response(200, envelope(data, total_records))

    except Exception as error:
        # Logged for CloudWatch, never returned - the client gets a safe,
        # correctly shaped empty payload rather than a database message.
        print(f"steward_volunteer_review_api failed: {error}")
        return build_response(500, envelope([], 0))

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    print(json.dumps(lambda_handler({"page": 1, "page_size": 5}, None), indent=2))
