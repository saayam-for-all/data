"""Assigned Volunteers API (Issue #295).

A single AWS Lambda entry point behind ``POST /volunteers/assigned`` that
answers one question for the Review Request flow: *which volunteer(s) are
currently assigned to this help request?*

Input is the request identifier::

    {"req_id": "REQ-000007"}

Output is the request id echoed back plus an array, so more than one current
assignment can be reported when the data model permits it::

    {
      "req_id": "REQ-000007",
      "lead_volunteer_id": "SID-00-000-060-168",
      "assignedVolunteers": [
        {
          "user_id": "SID-00-000-000-085",
          "full_name": "Stephen Gair",
          "primary_email_address": "stephen.gair@gmail.com",
          "primary_phone_number": "4070870000",
          "user_status": "ACTIVE",
          "volunteer_type": "Primary",
          "assigned_at": "2026-01-10 09:00:00",
          "is_lead": false
        }
      ]
    }

What counts as a *current* assignment
-------------------------------------
``volunteers_assigned`` is the only request-to-volunteer link table in the
Saayam schema, and as it stands it carries **no assignment-status column and
no active-assignment indicator**::

    volunteers_assigned(vol_assigned_id, req_id, volunteer_id,
                        volunteer_type, last_update_date, last_updated_at)

The issue asks for current assignments to be distinguished from historical
ones, but there is no column that says so. "Current" is therefore defined
here, not read off the row:

1. For each ``(req_id, volunteer_id)`` pair only the row with the newest
   ``last_update_date`` is current; older rows are treated as superseded
   history (a reassignment, or a changed ``volunteer_type``). Ties break on
   the higher ``vol_assigned_id`` so the result is deterministic.
2. A request in a terminal status has no current assignment at all - see
   :data:`TERMINAL_REQUEST_STATUS_IDS`.

Both rules live in one constant and one ``NOT EXISTS`` clause, so when an
assignment-status column is eventually added this module changes in exactly
two places. Until then, a volunteer is never dropped from the response merely
because their *user* status changed: an inactive volunteer who is still the
current assignee is still returned, with their status reported as
informational data.

The lead volunteer
------------------
``requests.lead_volunteer_id`` is a second, independent assignment signal.
It is **not** reconciled with ``volunteers_assigned`` here, because in the
committed fixtures the two agree in only one of twenty cases - and in that
one case the matching row is typed ``Secondary``, not ``Primary``. Inventing
a precedence rule on that evidence would be guesswork. Instead both are
reported and the caller decides: the request's own ``lead_volunteer_id`` is
echoed at the top level, and each volunteer carries ``is_lead`` saying
whether they are that person. ``volunteers_assigned`` remains the sole
source of the array itself, so no assignment is fabricated from the request
row.

No shared-database credentials
------------------------------
Like ``organization_analytics``, this Lambda deliberately has **no** AWS
Parameter Store / SSM credential lookup. The connection is built solely from
explicit ``DB_*`` environment variables and ``get_db_connection`` raises when
they are absent, so there is no code path from this module to the shared
production database. Development and testing run entirely against the mock
CSV fixtures in ``data-analytics/sql``; see ``data-analytics/tests/``.

Safety
------
``req_id`` is the only user-supplied value and is always passed as a
parameterized ``%s`` bind; the only thing ever formatted into SQL text is the
trusted ``SCHEMA_NAME`` constant. Volunteer profile and status are joined with
``LEFT JOIN`` so NULL or missing optional information yields ``null`` fields
rather than dropping the volunteer or failing the request. Both queries are
set-based, so retrieving many volunteers costs the same two round trips as
retrieving one.
"""

import json
import os
from typing import Any, Optional

import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"

# req_status_id values come from the request_statuses lookup
# (data-analytics/sql/request_statuses.csv):
#
#     1 New   2 In Progress   3 Completed
#     4 Cancelled   5 On Hold   6 Escalated
#
# Only Cancelled suppresses the assignment list: the request "was withdrawn or
# cancelled before completion", so nobody is working it now. Completed is
# deliberately NOT included - a finished request still has volunteers who
# serviced it, and the Review Request flow needs to see who they were. On Hold
# and Escalated are paused or raised, not ended, so they keep their
# volunteers. Confirm against the business rules before deployment; this is
# the one line to change.
TERMINAL_REQUEST_STATUS_IDS = (4,)

# The keys every entry of ``assignedVolunteers`` carries, in response order.
# Listed explicitly so the payload shape stays stable even when a joined row
# is missing columns.
VOLUNTEER_FIELDS = (
    "user_id",
    "full_name",
    "primary_email_address",
    "primary_phone_number",
    "user_status",
    "volunteer_type",
    "assigned_at",
    "is_lead",
)


# --------------------------------------------------------------------------- #
# Response envelope + DB connection
# --------------------------------------------------------------------------- #
def build_response(status_code: int, body: Any) -> dict[str, Any]:
    """Wrap a body in the standard API Gateway proxy response envelope.

    Args:
        status_code: HTTP status code to return.
        body: JSON-serializable response payload.

    Returns:
        A dict with ``statusCode``, CORS ``headers`` and a JSON ``body``.
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def get_db_connection() -> "psycopg2.extensions.connection":
    """Open a Postgres connection described entirely by environment variables.

    The connection is built from ``DB_HOST``/``DB_NAME``/``DB_USER``/
    ``DB_PASSWORD``/``DB_PORT``. There is intentionally **no** AWS Parameter
    Store fallback: this module must not be able to reach the shared
    production database, so an unconfigured environment is an error rather
    than an implicit escalation to real credentials.

    Returns:
        An open ``psycopg2`` connection.

    Raises:
        RuntimeError: If ``DB_HOST`` is not set.
    """
    db_host = os.environ.get("DB_HOST")
    if not db_host:
        raise RuntimeError(
            "DB_HOST is not set. assigned_volunteers has no AWS Parameter "
            "Store fallback by design - set the DB_* environment variables to "
            "point at your own database, or run the mock-backed test suite in "
            "data-analytics/tests/."
        )

    return psycopg2.connect(
        host=db_host,
        database=os.environ.get("DB_NAME", "saayam_local"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
        port=os.environ.get("DB_PORT", "5432"),
    )


# --------------------------------------------------------------------------- #
# Input parsing
# --------------------------------------------------------------------------- #
def parse_event_body(event: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Return the request payload from a Lambda event.

    Mirrors ``organization_analytics.parse_event_body`` so this API accepts
    the same shapes as the other endpoints: an API Gateway proxy event
    carrying a JSON string ``body``, a dict ``body``, or a plain invocation
    event with the fields at the top level.

    Args:
        event: The raw Lambda event.

    Returns:
        The decoded payload, or ``{}`` when it cannot be read.
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


def _extract_req_id(payload: dict[str, Any]) -> str:
    """Pull and validate ``req_id`` from the request payload.

    Args:
        payload: The decoded request body.

    Returns:
        The trimmed request identifier.

    Raises:
        ValueError: If ``req_id`` is absent, not a string, or blank.
    """
    req_id = payload.get("req_id")
    if not isinstance(req_id, str) or not req_id.strip():
        raise ValueError("req_id is required")
    return req_id.strip()


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #
def fetch_request(cursor: Any, req_id: str) -> Optional[dict[str, Any]]:
    """Look the help request up so an unknown ``req_id`` can be rejected.

    Args:
        cursor: An open dict-returning cursor.
        req_id: The request identifier supplied by the caller.

    Returns:
        The request row, or ``None`` when no such request exists.
    """
    cursor.execute(
        f"""
        SELECT r.req_id,
               r.creator_id,
               r.req_status_id,
               r.lead_volunteer_id
        FROM {SCHEMA_NAME}.requests r
        WHERE r.req_id = %s
        """,
        [req_id],
    )
    return cursor.fetchone()


def fetch_assigned_volunteers(
    cursor: Any, req_id: str, lead_volunteer_id: Optional[str] = None
) -> list[dict[str, Any]]:
    """Return the volunteers currently assigned to ``req_id``.

    A single set-based statement: the ``NOT EXISTS`` anti-join keeps only the
    newest ``volunteers_assigned`` row per volunteer, and the profile and
    status joins run in the same pass, so N volunteers still cost one query.
    ``LEFT JOIN`` keeps a volunteer in the result even when their ``users``
    row or ``user_status`` lookup is missing.

    ``NOT EXISTS`` is used rather than ``DISTINCT ON`` so the same SQL runs
    unmodified on both test backends in ``data-analytics/tests/mock_db.py``.

    Args:
        cursor: An open dict-returning cursor.
        req_id: The request identifier, passed as a bind parameter.
        lead_volunteer_id: ``requests.lead_volunteer_id`` for this request,
            used only to set the ``is_lead`` flag. Not used to filter.

    Returns:
        One dict per current volunteer, newest assignment first.
    """
    cursor.execute(
        f"""
        SELECT va.volunteer_id         AS user_id,
               u.full_name             AS full_name,
               u.primary_email_address AS primary_email_address,
               u.primary_phone_number  AS primary_phone_number,
               us.user_status          AS user_status,
               va.volunteer_type       AS volunteer_type,
               va.last_update_date     AS assigned_at
        FROM {SCHEMA_NAME}.volunteers_assigned va
        LEFT JOIN {SCHEMA_NAME}.users u
               ON u.user_id = va.volunteer_id
        LEFT JOIN {SCHEMA_NAME}.user_status us
               ON us.user_status_id = u.user_status_id
        WHERE va.req_id = %s
          AND NOT EXISTS (
                SELECT 1
                FROM {SCHEMA_NAME}.volunteers_assigned newer
                WHERE newer.req_id = va.req_id
                  AND newer.volunteer_id = va.volunteer_id
                  AND (newer.last_update_date > va.last_update_date
                       OR (newer.last_update_date = va.last_update_date
                           AND newer.vol_assigned_id > va.vol_assigned_id))
          )
        ORDER BY va.last_update_date DESC, va.volunteer_id ASC
        """,
        [req_id],
    )
    return [
        _shape_volunteer(row, lead_volunteer_id) for row in cursor.fetchall()
    ]


def _shape_volunteer(row: Any, lead_volunteer_id: Optional[str] = None) -> dict[str, Any]:
    """Normalize one joined row into the response entry shape.

    Every key in :data:`VOLUNTEER_FIELDS` is always present, defaulting to
    ``None``, so missing or NULL optional profile information surfaces as
    ``null`` rather than as a missing key.

    Args:
        row: A row from :func:`fetch_assigned_volunteers`.
        lead_volunteer_id: The request's ``lead_volunteer_id``, if any.

    Returns:
        A plain dict with exactly the response keys.
    """
    entry = {field: row.get(field) for field in VOLUNTEER_FIELDS}
    entry["is_lead"] = (
        lead_volunteer_id is not None
        and row.get("user_id") == lead_volunteer_id
    )
    return entry


def build_assigned_volunteers_response(
    cursor: Any, req_id: str
) -> tuple[int, dict[str, Any]]:
    """Resolve the full response for one ``req_id``.

    Args:
        cursor: An open dict-returning cursor.
        req_id: The validated request identifier.

    Returns:
        A ``(status_code, body)`` tuple. ``404`` when the request does not
        exist; otherwise ``200`` with ``lead_volunteer_id`` and the assigned
        volunteers, which is an empty list both when nothing is assigned and
        when the request is in a terminal status.
    """
    request_row = fetch_request(cursor, req_id)
    if request_row is None:
        return 404, {"error": f"no request found for req_id {req_id!r}"}

    lead_volunteer_id = request_row.get("lead_volunteer_id")
    body = {"req_id": req_id, "lead_volunteer_id": lead_volunteer_id}

    if request_row.get("req_status_id") in TERMINAL_REQUEST_STATUS_IDS:
        body["assignedVolunteers"] = []
        return 200, body

    body["assignedVolunteers"] = fetch_assigned_volunteers(
        cursor, req_id, lead_volunteer_id
    )
    return 200, body


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #
def lambda_handler(
    event: Optional[dict[str, Any]], context: Any = None
) -> dict[str, Any]:
    """Serve ``POST /volunteers/assigned``.

    A missing ``req_id`` is rejected with ``400`` before any query runs; an
    unknown ``req_id`` returns ``404``; a valid request with no current
    assignment is **not** an error and returns ``200`` with an empty
    ``assignedVolunteers`` array; a connection or query failure returns
    ``500`` without leaking connection details.

    Args:
        event: API Gateway proxy event or a plain invocation payload.
        context: Unused Lambda context object.

    Returns:
        An API Gateway proxy response from :func:`build_response`.
    """
    payload = parse_event_body(event)

    # Validate up front so bad input surfaces as a clean 400 rather than
    # reaching the database at all.
    try:
        req_id = _extract_req_id(payload)
    except ValueError as exc:
        print(f"[assigned_volunteers] bad request: {exc}")
        return build_response(400, {"error": str(exc)})

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        status_code, body = build_assigned_volunteers_response(cursor, req_id)
        return build_response(status_code, body)

    except ValueError as exc:
        print(f"[assigned_volunteers] bad request: {exc}")
        return build_response(400, {"error": str(exc)})

    except Exception as exc:  # noqa: BLE001
        print(f"[assigned_volunteers] database error: {exc}")
        return build_response(500, {"error": "internal server error"})

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    print(json.dumps(lambda_handler({"req_id": "REQ-000007"}), indent=2))
