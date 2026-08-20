"""Steward Dashboard -- Review Volunteers API.

Returns the paginated queue of volunteer applications that are waiting on a steward's
decision, newest-touched first. Each row carries the user id (the frontend uses it to
open the Review action), the last-updated timestamp, and a constant "Review" action label.

A note on the tables -- READ BEFORE MERGING
-------------------------------------------
The ticket asks for a join of `users` and `volunteers`. There is no `volunteers` table yet --
not on main, not on any remote branch, and not in the 46-table schema catalog at
database/mock-data-generation/db_info.json. It is expected to land separately, schema unknown
at the time of writing.

Until then this runs against `volunteer_applications`, the only volunteer table carrying a
status column (`application_status`), and therefore the only one that can express "only
volunteer requests requiring review are returned". Its user_id is both its primary key and a
1:1 join key to users.user_id.

Every assumption about which table and columns to read lives in the VOLUNTEER SOURCE BINDING
block below -- nothing else in this file names a volunteer column. When the real `volunteers`
table lands, retarget that block, update the fixture in
data-analytics/sql/steward_volunteer_review_local_setup.sql, and the rest of the module,
including the tests, should not need to change.

Local testing
-------------
Credentials come from data-analytics/.env (gitignored) via python-dotenv -- no AWS
Parameter Store, nothing hardcoded. Seed a local database first with
data-analytics/sql/steward_volunteer_review_local_setup.sql, then see
test_steward_volunteer_review_api.py (live) and
test_steward_volunteer_review_api_unit.py (mocked).
"""

import json
import math
import os

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
USERS = f"{SCHEMA_NAME}.users"

# ---------------------------------------------------------------------------
# VOLUNTEER SOURCE BINDING
#
# The single place this module decides *where* volunteer review requests come from.
# The `volunteers` table named in the ticket does not exist yet; when it lands, retarget
# these six names and nothing else in this file should need to change.
#
# Each name is interpolated into SQL as a trusted identifier, so these must stay
# hardcoded constants -- never assign request input to them.
# ---------------------------------------------------------------------------
VOLUNTEER_TABLE = f"{SCHEMA_NAME}.volunteer_applications"

# Column on VOLUNTEER_TABLE that joins to users.user_id.
VOLUNTEER_JOIN_COLUMN = "user_id"

# Column holding the last-updated timestamp the queue is sorted by and reports.
VOLUNTEER_UPDATED_COLUMN = "last_updated_at"

# Column holding the review state.
VOLUNTEER_STATUS_COLUMN = "application_status"

# True when VOLUNTEER_STATUS_COLUMN is a Postgres enum (USER-DEFINED) rather than plain
# text. Enums cannot be compared to text parameters without an explicit ::text cast.
# Set to False if the new table stores status as VARCHAR/TEXT.
VOLUNTEER_STATUS_IS_ENUM = True

# Which status values put a record in the steward's queue. SUBMITTED is waiting to be picked
# up; UNDER_REVIEW is already being looked at. Both still need action. The real Postgres enum
# is not checked into this repo -- this list comes from the mock data generator
# (database/mock-data-generation/utils.py), so it is unverified against production.
REVIEW_STATUSES = ("SUBMITTED", "UNDER_REVIEW")
# ---------------------------------------------------------------------------

# A UI action label, not a database column. The frontend renders it as the Review button.
REVIEW_ACTION_LABEL = "Review"

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 5
MAX_PAGE_SIZE = 100


def parse_event_body(event):
    """Reads the request payload from either an API Gateway event or a direct invoke.

    API Gateway hands us the payload as a JSON *string* under event["body"]; a direct
    Lambda invoke (and our own tests) passes the dict itself. Accepting both means the
    same handler works in production and from a local script.
    """
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


def build_response(status_code, body):
    # LEARN THIS: API Gateway proxy integration requires `body` to be a JSON *string*,
    # not a dict. default=str lets json.dumps handle types it cannot serialize on its own
    # (datetime, Decimal) instead of raising.
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


def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("HOST"),
        dbname=os.getenv("DATABASE_NAME"),
        user=os.getenv("USERNAME"),
        password=os.getenv("PASSWORD"),
        port=os.getenv("PORT"),
    )


def _coerce_positive_int(value, default):
    """int() the value, falling back to `default` on anything unusable or below 1."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 1 else default


def normalize_pagination(request_body):
    """Turns raw request input into a safe (page, page_size) pair.

    Bad input is clamped to sane values rather than rejected with a 400 -- the ticket
    defines no validation-error response, and a dashboard is better served by showing
    page 1 than by showing an error. page_size is capped so a caller cannot ask for the
    entire table in one request.
    """
    page = _coerce_positive_int(request_body.get("page"), DEFAULT_PAGE)
    page_size = _coerce_positive_int(request_body.get("page_size"), DEFAULT_PAGE_SIZE)
    return page, min(page_size, MAX_PAGE_SIZE)


def get_default_response(page, page_size):
    """The exact empty shape the handler returns for no-results and for failures.

    Keeping this identical to the success shape means the frontend never has to branch on
    whether the call succeeded -- data is always a list, pagination always has all four keys.
    """
    return {
        "data": [],
        "pagination": {
            "current_page": page,
            "page_size": page_size,
            "total_records": 0,
            "total_pages": 0,
        },
    }


def fetch_volunteer_reviews(cursor, page, page_size):
    """Fetches one page of the review queue, plus the unpaginated total, in one round trip.

    Returns (rows, total_records).
    """
    offset = (page - 1) * page_size

    updated = f"v.{VOLUNTEER_UPDATED_COLUMN}"
    # An enum column cannot be compared to a text parameter without an explicit cast.
    status = f"v.{VOLUNTEER_STATUS_COLUMN}" + ("::text" if VOLUNTEER_STATUS_IS_ENUM else "")

    # Three things here are worth understanding rather than copying:
    #
    # 1. COUNT(*) OVER() is a window function: it reports how many rows the WHERE clause
    #    matched *before* LIMIT/OFFSET trimmed them. That gives us total_records without a
    #    second COUNT query and without the two numbers ever disagreeing.
    #
    # 2. ORDER BY includes u.user_id as a tiebreaker. Sorting by the timestamp alone is not
    #    deterministic when values tie -- Postgres may return tied rows in a different order
    #    per query, so the same record can appear on two pages while another is never shown
    #    at all. A unique tiebreaker makes paging stable.
    #
    # 3. = ANY(%s) takes the whole status list as a single array parameter, so it stays
    #    parameterized rather than being interpolated into the SQL text.
    #
    # LEARN THIS: table and column names cannot be passed as %s parameters -- only *values*
    # can. That is why the identifiers below are f-string interpolated while every
    # user-supplied value goes through %s. It is safe only because those identifiers are
    # module constants that request input can never reach.
    query = f"""
        SELECT
            u.user_id,
            TO_CHAR({updated}, 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS updated_time,
            COUNT(*) OVER() AS total_records
        FROM {VOLUNTEER_TABLE} v
        JOIN {USERS} u ON u.user_id = v.{VOLUNTEER_JOIN_COLUMN}
        WHERE {status} = ANY(%s)
        ORDER BY {updated} DESC, u.user_id DESC
        LIMIT %s OFFSET %s
    """

    cursor.execute(query, [list(REVIEW_STATUSES), page_size, offset])
    rows = cursor.fetchall()

    # COUNT(*) OVER() rides along on every row, so with zero rows there is nothing to read
    # it from -- an empty page legitimately means zero matches.
    total_records = int(rows[0]["total_records"]) if rows else 0

    data = [
        {
            "user_id": row["user_id"],
            "updated_time": row["updated_time"],
            "volunteer_review": REVIEW_ACTION_LABEL,
        }
        for row in rows
    ]

    return data, total_records


def lambda_handler(event, context):
    conn = None
    cursor = None

    request_body = parse_event_body(event)
    page, page_size = normalize_pagination(request_body)

    response_body = get_default_response(page, page_size)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        print("Database connected successfully.")

        data, total_records = fetch_volunteer_reviews(cursor, page, page_size)

        response_body["data"] = data
        response_body["pagination"]["total_records"] = total_records
        response_body["pagination"]["total_pages"] = math.ceil(total_records / page_size)

        return build_response(200, response_body)

    except Exception as e:
        # The exception text can carry host names and driver internals, so it goes to the
        # log and never into the response. Callers get the same safe empty shape.
        print("ERROR:", str(e))
        return build_response(500, get_default_response(page, page_size))

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        print("Database connection closed")


if __name__ == "__main__":
    print(json.dumps(lambda_handler({}, None), indent=2))
