"""Volunteer Microservice API - list volunteers available for a help request.

POST /volunteers/available
    {"request_id": "REQ-00-000-000-001"}

Given a request_id the handler resolves the request's category and type, then
returns the volunteers that satisfy the applicable matching rules:

  1. Skill match       user_skills.cat_id = requests.req_cat_id
                       (optionally widened to child categories via
                       help_category_map, see ENABLE_HIERARCHICAL_CATEGORY_MATCH)
  2. Status            users.user_status_id -> user_status.user_status,
                       resolved by name so no numeric status id is hardcoded
  3. Location          in-person requests only: PostGIS ST_DWithin between
                       volunteer_locations.curr_loc and the beneficiary's
                       user_locations.curr_loc
  4. Assignment        volunteers already assigned to this request are dropped
                       (EXCLUDE_ASSIGNED_VOLUNTEERS)

Everything the issue flagged as "to be confirmed" is configuration rather than
a literal in the SQL - see the CONFIG block below.

Note on the request location: requests.req_loc is VARCHAR(125) free text, not a
geography column, so it cannot drive PostGIS matching. The beneficiary's point
from user_locations.curr_loc is used instead (falling back to the creator when
the request has no separate beneficiary), which is the only geography(Point,
4326) value available for a request.
"""

import json
import os
import re

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor

# --- Configuration -------------------------------------------------------
# None of these are business rules we get to invent; they are the values the
# issue listed as "to be confirmed", exposed so they can be set per
# environment without a code change.

SCHEMA_NAME = os.environ.get("SAAYAM_DB_SCHEMA", "virginia_dev_saayam_rdbms")

SSM_DB_PARAMETER = os.environ.get(
    "SAAYAM_DB_SSM_PARAMETER", "/dev/saayam/db/Virginia/Analytics/user")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Status names (not ids) that make a volunteer eligible.
ELIGIBLE_VOLUNTEER_STATUSES = [
    s.strip() for s in
    os.environ.get("ELIGIBLE_VOLUNTEER_STATUSES", "Active").split(",")
    if s.strip()
]

# request_types.req_type values that mean "the volunteer has to show up".
IN_PERSON_REQUEST_TYPES = [
    s.strip().lower() for s in
    os.environ.get("IN_PERSON_REQUEST_TYPES", "In person").split(",")
    if s.strip()
]

# Proximity rule for in-person requests, in metres (geography => metres).
IN_PERSON_MATCH_RADIUS_METERS = float(
    os.environ.get("IN_PERSON_MATCH_RADIUS_METERS", "50000"))

EXCLUDE_ASSIGNED_VOLUNTEERS = (
    os.environ.get("EXCLUDE_ASSIGNED_VOLUNTEERS", "true").lower() == "true")

# Off until the parent/child business rule is confirmed; when on, a request in
# a parent category also matches volunteers skilled in its child categories.
ENABLE_HIERARCHICAL_CATEGORY_MATCH = (
    os.environ.get("ENABLE_HIERARCHICAL_CATEGORY_MATCH", "false").lower()
    == "true")

# Schema names cannot be passed as a bind parameter, so validate the identifier
# rather than interpolating whatever the environment happens to hold.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _schema():
    if not _IDENTIFIER.match(SCHEMA_NAME):
        raise ValueError("Invalid schema name: {!r}".format(SCHEMA_NAME))
    return SCHEMA_NAME


# --- Plumbing ------------------------------------------------------------

def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body),
    }


def parse_event_body(event):
    """Accept both a direct invoke payload and an API Gateway proxy event."""
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
    """Credentials come from SSM Parameter Store - never from the source."""
    ssm = boto3.client("ssm", region_name=AWS_REGION)
    response = ssm.get_parameter(Name=SSM_DB_PARAMETER, WithDecryption=True)

    creds = json.loads(response["Parameter"]["Value"])
    return psycopg2.connect(
        host=creds["HOST"],
        database=creds["DATABASE NAME"],
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require",
    )


# --- Queries -------------------------------------------------------------

def fetch_request(cursor, request_id):
    """Resolve the request plus its type name and beneficiary location."""
    query = """
        SELECT r.req_id,
               r.req_cat_id,
               r.req_type_id,
               rt.req_type,
               COALESCE(r.beneficiary_id, r.creator_id) AS location_user_id,
               ul.curr_loc IS NOT NULL                  AS has_location
        FROM {schema}.requests r
        LEFT JOIN {schema}.request_types rt
               ON rt.req_type_id = r.req_type_id
        LEFT JOIN {schema}.user_locations ul
               ON ul.user_id = COALESCE(r.beneficiary_id, r.creator_id)
        WHERE r.req_id = %(request_id)s
    """.format(schema=_schema())
    cursor.execute(query, {"request_id": request_id})
    return cursor.fetchone()


def fetch_available_volunteers(cursor, request, apply_location):
    """One set-based query for every matching rule - no per-volunteer lookups."""
    schema = _schema()

    # Widening the category set is a UNION rather than an OR so the direct
    # match still uses the user_skills(cat_id) index.
    if ENABLE_HIERARCHICAL_CATEGORY_MATCH:
        category_cte = """
            SELECT %(req_cat_id)s::varchar AS cat_id
            UNION
            SELECT m.child_id
            FROM {schema}.help_category_map m
            WHERE m.parent_id = %(req_cat_id)s
        """.format(schema=schema)
    else:
        category_cte = "SELECT %(req_cat_id)s::varchar AS cat_id"

    assignment_clause = ""
    if EXCLUDE_ASSIGNED_VOLUNTEERS:
        assignment_clause = """
          AND NOT EXISTS (
              SELECT 1
              FROM {schema}.volunteers_assigned va
              WHERE va.req_id = %(request_id)s
                AND va.volunteer_id = u.user_id
          )
        """.format(schema=schema)

    # A volunteer with no location row simply fails the proximity test for
    # in-person requests; it never errors the call.
    location_clause = ""
    if apply_location:
        location_clause = """
          AND vl.curr_loc IS NOT NULL
          AND req_point.curr_loc IS NOT NULL
          AND ST_DWithin(vl.curr_loc, req_point.curr_loc, %(radius_m)s)
        """

    query = """
        WITH match_categories AS (
            {category_cte}
        ),
        req_point AS (
            SELECT ul.curr_loc
            FROM {schema}.user_locations ul
            WHERE ul.user_id = %(location_user_id)s
        )
        SELECT u.user_id                              AS volunteer_id,
               u.full_name,
               ust.user_status                        AS status,
               ARRAY_AGG(DISTINCT hc.cat_name)        AS skills,
               MIN(ST_Distance(vl.curr_loc, req_point.curr_loc))
                                                      AS distance_meters
        FROM {schema}.volunteer_details vd
        JOIN {schema}.users u
             ON u.user_id = vd.user_id
        JOIN {schema}.user_status ust
             ON ust.user_status_id = u.user_status_id
        JOIN {schema}.user_skills usk
             ON usk.user_id = u.user_id
        JOIN match_categories mc
             ON mc.cat_id = usk.cat_id
        JOIN {schema}.help_categories hc
             ON hc.cat_id = usk.cat_id
        LEFT JOIN {schema}.volunteer_locations vl
             ON vl.user_id = vd.user_id
        LEFT JOIN req_point ON TRUE
        WHERE ust.user_status = ANY(%(eligible_statuses)s)
        {assignment_clause}
        {location_clause}
        GROUP BY u.user_id, u.full_name, ust.user_status
        ORDER BY distance_meters NULLS LAST, u.full_name
    """.format(schema=schema, category_cte=category_cte,
               assignment_clause=assignment_clause,
               location_clause=location_clause)

    params = {
        "req_cat_id": request["req_cat_id"],
        "request_id": request["req_id"],
        "location_user_id": request["location_user_id"],
        "eligible_statuses": ELIGIBLE_VOLUNTEER_STATUSES,
        "radius_m": IN_PERSON_MATCH_RADIUS_METERS,
    }
    cursor.execute(query, params)
    return cursor.fetchall()


def is_in_person(request):
    req_type = (request.get("req_type") or "").strip().lower()
    return req_type in IN_PERSON_REQUEST_TYPES


def format_volunteer(row):
    distance = row.get("distance_meters")
    return {
        "volunteerId": row["volunteer_id"],
        "name": row.get("full_name"),
        "skills": [s for s in (row.get("skills") or []) if s],
        "status": row.get("status"),
        "distanceMeters": round(float(distance), 1) if distance is not None else None,
    }


# --- Handler -------------------------------------------------------------

def lambda_handler(event, context):
    conn = None
    cursor = None

    body = parse_event_body(event)
    request_id = (body.get("request_id") or "").strip() if body else ""

    if not request_id:
        return build_response(400, {"error": "request_id is required"})

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        request = fetch_request(cursor, request_id)
        if not request:
            return build_response(
                404, {"error": "request not found: {}".format(request_id)})

        # In-person requests need a beneficiary point to measure against. If
        # there isn't one we still answer, but we say the filter was skipped
        # rather than silently implying these volunteers are nearby.
        apply_location = is_in_person(request) and bool(request.get("has_location"))
        if is_in_person(request) and not apply_location:
            print("No beneficiary location for {}; skipping proximity filter"
                  .format(request_id))

        rows = fetch_available_volunteers(cursor, request, apply_location)

        return build_response(200, {
            "requestId": request_id,
            "availableVolunteers": [format_volunteer(r) for r in rows],
            "locationFilterApplied": apply_location,
        })

    except Exception as exc:
        print("available_volunteers failed for {}: {}".format(request_id, exc))
        return build_response(500, {"error": "Internal server error"})

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    print(json.dumps(
        lambda_handler({"request_id": "REQ-00-000-000-001"}, None), indent=2))
