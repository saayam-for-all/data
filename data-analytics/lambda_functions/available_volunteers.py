"""Available Volunteers API for Saayam request assignment workflows.

Endpoint: POST /volunteers/available

Given a request_id, return volunteers who match the request category (via
user_skills and help_categories_map), have Active status, and — when the
request type is In person — are within the existing geospatial matching
radius of the beneficiary/request location.

Database credentials come from local environment variables / DATABASE_URL.
AWS Parameter Store is not used.
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

    Identifiers cannot be parameterized, so DB_SCHEMA is allowlisted and
    matched against a strict identifier regex before interpolation.
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
USER_LOCATIONS_TABLE = f"{SCHEMA_NAME}.user_locations"
HELP_CATEGORIES_TABLE = f"{SCHEMA_NAME}.help_categories"
HELP_CATEGORIES_MAP_TABLE = f"{SCHEMA_NAME}.help_categories_map"
VOLUNTEER_DETAILS_TABLE = f"{SCHEMA_NAME}.volunteer_details"
VOLUNTEER_LOCATIONS_TABLE = f"{SCHEMA_NAME}.volunteer_locations"
VOLUNTEERS_ASSIGNED_TABLE = f"{SCHEMA_NAME}.volunteers_assigned"
CITY_TABLE = f"{SCHEMA_NAME}.city"

# Existing spatial matching defaults from saayam-for-all/spatial config.py.
# Override with env vars rather than inventing a new hardcoded radius.
DEFAULT_RADIUS_KM = float(os.getenv("VOLUNTEER_MATCH_RADIUS_KM", "25"))
CALAMITY_RADIUS_KM = float(os.getenv("VOLUNTEER_CALAMITY_RADIUS_KM", "200"))
ELIGIBLE_STATUS = os.getenv("VOLUNTEER_ELIGIBLE_STATUS", "ACTIVE")


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
    """Open a local PostgreSQL connection. Never reads AWS Parameter Store."""
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


def is_in_person_request(req_type):
    """True when request_type.req_type is In person / IN_PERSON."""
    normalized = re.sub(r"[^A-Z0-9]", "", str(req_type or "").upper())
    return normalized == "INPERSON"


def matching_radius_meters(is_calamity=False):
    """Return the matching radius in meters from existing spatial rules."""
    km = CALAMITY_RADIUS_KM if is_calamity else DEFAULT_RADIUS_KM
    return float(km) * 1000.0


def format_skill_name(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.replace("_", " ").title()


def format_status(value):
    if value is None or str(value).strip() == "":
        return None
    return str(value).replace("_", " ").strip().title()


def volunteer_display_name(row):
    full = str(row.get("name") or row.get("full_name") or "").strip()
    if full:
        return full
    parts = [
        str(part).strip()
        for part in (row.get("first_name"), row.get("last_name"))
        if part and str(part).strip()
    ]
    return " ".join(parts) or str(row.get("volunteer_id") or row.get("user_id") or "")


def _as_skill_list(raw):
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        values = raw
    else:
        values = [part.strip() for part in str(raw).split(",")]
    skills = []
    seen = set()
    for value in values:
        formatted = format_skill_name(value)
        if formatted and formatted not in seen:
            seen.add(formatted)
            skills.append(formatted)
    return skills


def format_volunteer(row):
    volunteer_id = str(row.get("volunteer_id") or row.get("user_id") or "")
    return {
        "volunteerId": volunteer_id,
        "name": volunteer_display_name(row) or volunteer_id,
        "skills": _as_skill_list(row.get("skills")),
        "status": format_status(row.get("status")) or format_status(ELIGIBLE_STATUS),
    }


def request_lookup_sql():
    """Load the help request plus type and beneficiary/request coordinates.

    Beneficiary geography comes from user_locations.curr_loc (latest current
    point). If that is missing, city.lattitude/longitude is used when req_loc
    matches a known city name.
    """
    return f"""
        SELECT
            r.req_id,
            r.req_user_id,
            r.req_cat_id,
            r.req_type_id,
            r.req_loc,
            COALESCE(r.iscalamity, FALSE) AS iscalamity,
            rt.req_type,
            ST_Y(ul.curr_loc::geometry) AS beneficiary_lat,
            ST_X(ul.curr_loc::geometry) AS beneficiary_lon,
            city.lattitude AS city_lat,
            city.longitude AS city_lon
        FROM {REQUEST_TABLE} r
        LEFT JOIN {REQUEST_TYPE_TABLE} rt
            ON r.req_type_id = rt.req_type_id
        LEFT JOIN {USER_LOCATIONS_TABLE} ul
            ON r.req_user_id = ul.user_id
        LEFT JOIN LATERAL (
            SELECT c.lattitude, c.longitude
            FROM {CITY_TABLE} c
            WHERE r.req_loc IS NOT NULL
              AND TRIM(r.req_loc) <> ''
              AND LOWER(TRIM(c.city_name))
                  = LOWER(TRIM(SPLIT_PART(r.req_loc, ',', 1)))
            LIMIT 1
        ) city ON TRUE
        WHERE r.req_id = %s
        LIMIT 1
    """


def available_volunteers_sql(apply_location=False):
    """Skill, status, and optional proximity matching in one set-based query.

    Category matching uses help_categories_map so a volunteer matches when
    user_skills.cat_id is the request category, an ancestor, or a descendant.
    Volunteers already assigned to this request are excluded. Missing
    volunteer geolocation excludes only that volunteer when location matching
    is required; it does not fail the query.
    """
    location_filter = ""
    location_join = ""
    distance_select = "NULL::double precision AS distance_meters"
    order_by = "name ASC NULLS LAST, u.user_id ASC"

    if apply_location:
        location_join = f"""
        LEFT JOIN LATERAL (
            SELECT vl.curr_loc, vl.updated_at
            FROM {VOLUNTEER_LOCATIONS_TABLE} vl
            WHERE vl.user_id = u.user_id
              AND vl.curr_loc IS NOT NULL
            ORDER BY vl.updated_at DESC NULLS LAST
            LIMIT 1
        ) latest_loc ON TRUE
        """
        location_filter = """
              AND latest_loc.curr_loc IS NOT NULL
              AND ST_DWithin(
                    latest_loc.curr_loc::geography,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    %s
              )
        """
        distance_select = """
            ST_Distance(
                latest_loc.curr_loc::geography,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
            ) AS distance_meters
        """
        order_by = "distance_meters ASC NULLS LAST, name ASC NULLS LAST, u.user_id ASC"

    return f"""
        WITH RECURSIVE matched_cats AS (
            SELECT %s::varchar AS cat_id
            UNION
            SELECT m.parent_id
            FROM {HELP_CATEGORIES_MAP_TABLE} m
            JOIN matched_cats mc ON m.child_id = mc.cat_id
            WHERE m.parent_id IS NOT NULL
              AND m.parent_id <> '0.0.0.0.0'
            UNION
            SELECT m.child_id
            FROM {HELP_CATEGORIES_MAP_TABLE} m
            JOIN matched_cats mc ON m.parent_id = mc.cat_id
            WHERE m.child_id IS NOT NULL
        ),
        volunteer_skills AS (
            SELECT
                us.user_id,
                ARRAY_REMOVE(
                    ARRAY_AGG(DISTINCT COALESCE(hc.cat_name, us.cat_id::text)),
                    NULL
                ) AS skills
            FROM {USER_SKILLS_TABLE} us
            JOIN matched_cats mc
                ON TRIM(us.cat_id::text) = TRIM(mc.cat_id::text)
            LEFT JOIN {HELP_CATEGORIES_TABLE} hc
                ON TRIM(us.cat_id::text) = TRIM(hc.cat_id::text)
            GROUP BY us.user_id
        )
        SELECT
            u.user_id AS volunteer_id,
            COALESCE(
                NULLIF(TRIM(u.full_name), ''),
                NULLIF(TRIM(CONCAT_WS(' ', u.first_name, u.last_name)), ''),
                u.user_id
            ) AS name,
            vs.skills,
            st.user_status AS status,
            {distance_select}
        FROM volunteer_skills vs
        JOIN {VOLUNTEER_DETAILS_TABLE} vd
            ON vd.user_id = vs.user_id
        JOIN {USERS_TABLE} u
            ON u.user_id = vs.user_id
        LEFT JOIN {USER_STATUS_TABLE} st
            ON u.user_status_id = st.user_status_id
        {location_join}
        WHERE UPPER(TRIM(COALESCE(st.user_status, ''))) = UPPER(%s)
          AND NOT EXISTS (
                SELECT 1
                FROM {VOLUNTEERS_ASSIGNED_TABLE} va
                WHERE va.request_id = %s
                  AND va.volunteer_id = u.user_id
          )
          {location_filter}
        ORDER BY {order_by}
    """


def resolve_origin_coordinates(request_row):
    """Prefer live beneficiary geography, then city coordinates from req_loc."""
    lat = request_row.get("beneficiary_lat")
    lon = request_row.get("beneficiary_lon")
    if lat is not None and lon is not None:
        return float(lat), float(lon)
    city_lat = request_row.get("city_lat")
    city_lon = request_row.get("city_lon")
    if city_lat is not None and city_lon is not None:
        return float(city_lat), float(city_lon)
    return None, None


def fetch_request(cursor, request_id):
    cursor.execute(request_lookup_sql(), (request_id,))
    return cursor.fetchone()


def fetch_available_volunteers(cursor, request_row):
    req_cat_id = request_row.get("req_cat_id")
    request_id = request_row.get("req_id")
    apply_location = is_in_person_request(request_row.get("req_type"))
    lat, lon = resolve_origin_coordinates(request_row) if apply_location else (None, None)

    # In-person matching needs an origin point. If it is missing, skip the
    # radius filter instead of failing the whole API call.
    if apply_location and (lat is None or lon is None):
        apply_location = False

    sql = available_volunteers_sql(apply_location=apply_location)
    # Placeholder order matches available_volunteers_sql: category CTE, optional
    # distance SELECT, status + request_id filters, optional ST_DWithin.
    params = [req_cat_id]
    if apply_location:
        params.extend([lon, lat])
    params.extend([ELIGIBLE_STATUS, request_id])
    if apply_location:
        radius_m = matching_radius_meters(bool(request_row.get("iscalamity")))
        params.extend([lon, lat, radius_m])
    cursor.execute(sql, tuple(params))
    return cursor.fetchall() or []


def collect_available_volunteers(cursor, request_id):
    request_row = fetch_request(cursor, request_id)
    if not request_row:
        return None
    rows = fetch_available_volunteers(cursor, request_row)
    return {
        "requestId": request_row.get("req_id") or request_id,
        "availableVolunteers": [format_volunteer(row) for row in rows],
    }


def lambda_handler(event, context):
    """Entry point for POST /volunteers/available."""
    method = ""
    if isinstance(event, dict):
        method = str(event.get("httpMethod") or "").upper()
    if method == "OPTIONS":
        return build_response(200, {})
    if method and method != "POST":
        return build_response(405, {"error": "Method not allowed"})

    try:
        request_id = parse_request_id(parse_event_body(event))
    except RequestValidationError as exc:
        return build_response(400, {"error": str(exc)})

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        payload = collect_available_volunteers(cursor, request_id)
        if payload is None:
            return build_response(404, {"error": "request not found"})
        return build_response(200, payload)
    except Exception as exc:  # noqa: BLE001 - API must not crash
        print(f"Available volunteers lookup failed: {exc}")
        return build_response(500, {"error": "internal server error"})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    sample_event = {"request_id": "REQ-00-000-000-001"}
    result = lambda_handler(sample_event, None)
    print(json.dumps(json.loads(result["body"]), indent=2))
