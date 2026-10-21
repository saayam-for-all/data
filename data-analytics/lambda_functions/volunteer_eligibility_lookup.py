"""Available Volunteers API for the Volunteer Dashboard (issue #289).

Endpoint: POST /volunteers/available
Body:     {"request_id": "<req_id>"}

Given a request_id, returns volunteers eligible for that request:
  1. Skill/category match: user_skills.cat_id related to request.req_cat_id,
     including ancestor/descendant categories via the existing
     help_categories_map hierarchy (not a hardcoded category-skill mapping).
  2. Location match, only for request_type.req_type == 'IN_PERSON' requests:
     volunteer_locations.curr_loc within a configurable radius of the
     beneficiary's user_locations.curr_loc (both PostGIS geography columns).
  3. Active status: users.user_status_id -> user_status.user_status == 'ACTIVE'.
  4. Volunteers already assigned to this request (volunteers_assigned) are
     excluded.

Database credentials come from local environment variables / DATABASE_URL.
No AWS SDK / Parameter Store dependency, so this can be exercised against a
local Postgres+PostGIS instance without AWS access.
"""

from __future__ import annotations

import json
import os
import re

import psycopg2
from psycopg2.extras import RealDictCursor

DEFAULT_SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ALLOWED_SCHEMA_NAMES = frozenset(
    {
        DEFAULT_SCHEMA_NAME,
        "ireland_dev_saayam_rdbms",
    }
)
_SCHEMA_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def resolve_schema_name(raw=None):
    """Return a safe SQL schema identifier, or the default if invalid.

    Identifiers cannot be parameterized in psycopg2, so DB_SCHEMA is
    allowlisted and checked against a strict identifier regex before being
    interpolated into table-name constants below.
    """
    candidate = str(
        raw if raw is not None else os.getenv("DB_SCHEMA", DEFAULT_SCHEMA_NAME) or ""
    ).strip()
    if candidate in ALLOWED_SCHEMA_NAMES:
        return candidate
    if candidate and _SCHEMA_IDENTIFIER_RE.fullmatch(candidate):
        return candidate
    return DEFAULT_SCHEMA_NAME


SCHEMA_NAME = resolve_schema_name()
REQUEST_TABLE = f"{SCHEMA_NAME}.request"
REQUEST_TYPE_TABLE = f"{SCHEMA_NAME}.request_type"
USERS_TABLE = f"{SCHEMA_NAME}.users"
USER_STATUS_TABLE = f"{SCHEMA_NAME}.user_status"
USER_SKILLS_TABLE = f"{SCHEMA_NAME}.user_skills"
HELP_CATEGORIES_TABLE = f"{SCHEMA_NAME}.help_categories"
HELP_CATEGORIES_MAP_TABLE = f"{SCHEMA_NAME}.help_categories_map"
VOLUNTEER_LOCATIONS_TABLE = f"{SCHEMA_NAME}.volunteer_locations"
USER_LOCATIONS_TABLE = f"{SCHEMA_NAME}.user_locations"
VOLUNTEERS_ASSIGNED_TABLE = f"{SCHEMA_NAME}.volunteers_assigned"

# ASSUMPTION -- not an established business rule. No matching radius is
# defined or configured anywhere in this repo (issue #289 leaves it as an
# open question). Override via VOLUNTEER_MATCH_RADIUS_METERS; confirm the
# real value with the team/PM before relying on this default.
DEFAULT_MATCH_RADIUS_METERS = 16093  # ~10 miles

ACTIVE_STATUS = "ACTIVE"
REQUEST_TYPE_IN_PERSON = "IN_PERSON"


class RequestValidationError(ValueError):
    """Raised when the payload cannot be used to look up a request."""


def parse_event_body(event):
    """Return the payload for both API Gateway and direct Lambda invocations."""
    if not event:
        return {}

    body = event.get("body") if isinstance(event, dict) else None
    if body is None:
        return event if isinstance(event, dict) else {}
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body, dict):
        return body
    return {}


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }


def get_db_connection():
    """Open a local PostgreSQL connection from env vars. No AWS dependency."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    kwargs = {
        "host": os.getenv("PGHOST", os.getenv("DB_HOST", "localhost")),
        "port": os.getenv("PGPORT", os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv(
            "PGDATABASE", os.getenv("DB_NAME", os.getenv("POSTGRES_DB", "saayam"))
        ),
        "user": os.getenv(
            "PGUSER", os.getenv("DB_USER", os.getenv("POSTGRES_USER", "postgres"))
        ),
        "password": os.getenv(
            "PGPASSWORD", os.getenv("DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", ""))
        ),
        "connect_timeout": int(os.getenv("PGCONNECT_TIMEOUT", "10")),
    }
    sslmode = os.getenv("PGSSLMODE")
    if sslmode:
        kwargs["sslmode"] = sslmode
    return psycopg2.connect(**kwargs)


def parse_request_id(body):
    """Require request_id (or requestId) from the payload."""
    body = body or {}
    raw = body.get("request_id", body.get("requestId"))
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise RequestValidationError("request_id is required")
    return str(raw).strip()


def matching_radius_meters():
    return int(os.getenv("VOLUNTEER_MATCH_RADIUS_METERS", str(DEFAULT_MATCH_RADIUS_METERS)))


def get_request_context(cursor, request_id):
    """Look up the request plus its resolved request_type. None if not found."""
    cursor.execute(
        f"""
        SELECT r.req_id, r.req_user_id, r.req_cat_id, rt.req_type
        FROM {REQUEST_TABLE} r
        JOIN {REQUEST_TYPE_TABLE} rt ON r.req_type_id = rt.req_type_id
        WHERE r.req_id = %(request_id)s
        """,
        {"request_id": request_id},
    )
    return cursor.fetchone()


def has_beneficiary_location(cursor, req_user_id):
    """True when the beneficiary has a usable geolocation on file."""
    cursor.execute(
        f"""
        SELECT curr_loc IS NOT NULL AS has_location
        FROM {USER_LOCATIONS_TABLE}
        WHERE user_id = %(req_user_id)s
        """,
        {"req_user_id": req_user_id},
    )
    row = cursor.fetchone()
    return bool(row and row.get("has_location"))


def build_matching_sql(is_in_person):
    """Build the skill+status(+location) matching query.

    Skill matching walks the help_categories_map hierarchy in both
    directions from req_cat_id (ancestors and descendants), so a volunteer
    skilled in a broader or narrower category than the request's exact
    category still matches -- not just an exact cat_id match. This reuses
    the existing category mapping rather than hardcoding category-skill
    relationships, per the issue's requirement.

    The location join/filter is only appended when is_in_person is True, so
    remote requests structurally skip location filtering entirely (rather
    than including a join that's merely neutralized).
    """
    location_join = ""
    location_filter = ""
    if is_in_person:
        location_join = f"""
        JOIN {VOLUNTEER_LOCATIONS_TABLE} vl ON vl.user_id = u.user_id
        JOIN {USER_LOCATIONS_TABLE} ul ON ul.user_id = %(req_user_id)s
        """
        location_filter = """
          AND vl.curr_loc IS NOT NULL
          AND ul.curr_loc IS NOT NULL
          AND ST_DWithin(vl.curr_loc, ul.curr_loc, %(radius_meters)s)
        """

    return f"""
        WITH RECURSIVE
        category_ancestors AS (
            SELECT parent_id, child_id
            FROM {HELP_CATEGORIES_MAP_TABLE}
            WHERE child_id = %(req_cat_id)s
            UNION ALL
            SELECT m.parent_id, m.child_id
            FROM {HELP_CATEGORIES_MAP_TABLE} m
            JOIN category_ancestors a ON m.child_id = a.parent_id
        ),
        category_descendants AS (
            SELECT parent_id, child_id
            FROM {HELP_CATEGORIES_MAP_TABLE}
            WHERE parent_id = %(req_cat_id)s
            UNION ALL
            SELECT m.parent_id, m.child_id
            FROM {HELP_CATEGORIES_MAP_TABLE} m
            JOIN category_descendants d ON m.parent_id = d.child_id
        ),
        related_categories AS (
            SELECT %(req_cat_id)s AS cat_id
            UNION SELECT parent_id FROM category_ancestors WHERE parent_id IS NOT NULL
            UNION SELECT child_id FROM category_descendants
        )
        SELECT u.user_id, u.full_name, ARRAY_AGG(DISTINCT hc.cat_name) AS skills
        FROM {USERS_TABLE} u
        JOIN {USER_STATUS_TABLE} st ON u.user_status_id = st.user_status_id
        JOIN {USER_SKILLS_TABLE} us ON us.user_id = u.user_id
        JOIN related_categories rc ON us.cat_id = rc.cat_id
        JOIN {HELP_CATEGORIES_TABLE} hc ON hc.cat_id = us.cat_id
        {location_join}
        WHERE st.user_status = %(active_status)s
          AND NOT EXISTS (
              SELECT 1 FROM {VOLUNTEERS_ASSIGNED_TABLE} va
              WHERE va.request_id = %(request_id)s AND va.volunteer_id = u.user_id
          )
        {location_filter}
        GROUP BY u.user_id, u.full_name
    """


def format_volunteer(row):
    volunteer_id = str(row.get("user_id") or "")
    skills = [s for s in (row.get("skills") or []) if s]
    return {
        "volunteerId": volunteer_id,
        "name": str(row.get("full_name") or volunteer_id),
        "skills": skills,
        "status": "Active",
    }


def get_available_volunteers(cursor, req_cat_id, req_user_id, request_id, is_in_person, radius_meters):
    """Run the single set-based matching query. Avoids N+1 queries."""
    if is_in_person and not has_beneficiary_location(cursor, req_user_id):
        print(f"No beneficiary geolocation for req_user_id={req_user_id}; no in-person matches possible")
        return []

    params = {
        "req_cat_id": req_cat_id,
        "req_user_id": req_user_id,
        "request_id": request_id,
        "active_status": ACTIVE_STATUS,
    }
    if is_in_person:
        params["radius_meters"] = radius_meters

    cursor.execute(build_matching_sql(is_in_person), params)
    return [format_volunteer(row) for row in cursor.fetchall()]


def lambda_handler(event, context):
    conn = None
    cursor = None
    try:
        body = parse_event_body(event)
        try:
            request_id = parse_request_id(body)
        except RequestValidationError as e:
            return build_response(400, {"error": str(e)})

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        request_ctx = get_request_context(cursor, request_id)
        if request_ctx is None:
            return build_response(404, {"error": f"request {request_id} not found"})

        is_in_person = request_ctx["req_type"] == REQUEST_TYPE_IN_PERSON

        volunteers = get_available_volunteers(
            cursor,
            req_cat_id=request_ctx["req_cat_id"],
            req_user_id=request_ctx["req_user_id"],
            request_id=request_id,
            is_in_person=is_in_person,
            radius_meters=matching_radius_meters(),
        )

        return build_response(200, {"requestId": request_id, "availableVolunteers": volunteers})

    except Exception as e:
        print(f"ERROR: {e}")
        return build_response(500, {"error": "internal error retrieving available volunteers"})

    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
