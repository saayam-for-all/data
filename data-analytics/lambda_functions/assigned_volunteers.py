"""Assigned Volunteers API (Issue #295).

A single AWS Lambda entry point behind ``POST /volunteers/assigned`` that
answers one question for the Review Request flow: *which volunteer(s) are
currently assigned to this help request?*

Input is the request identifier::

    {"req_id": "REQ-00-000-000-0018"}

Output is the request id echoed back plus an array, so more than one current
assignment can be reported when the data model permits it::

    {
      "req_id": "REQ-00-000-000-0018",
      "assignedVolunteers": [
        {
          "user_id": "SID-00-000-000-078",
          "full_name": "Vighnesh Sridhar",
          "primary_email_address": "vighnesh.s.saayam@gmail.com",
          "primary_phone_number": "4087265003",
          "user_status": "ACTIVE",
          "volunteer_type": "LEAD",
          "assigned_at": "2026-01-10 09:00:00"
        }
      ]
    }

What counts as a *current* assignment
-------------------------------------
``volunteers_assigned`` is the only request-to-volunteer link table in the
Saayam schema, and as it stands it carries **no assignment-status column and
no active-assignment indicator**::

    volunteers_assigned(volunteers_assigned_id, request_id, volunteer_id,
                        volunteer_type, last_update_date)

"Current" is therefore defined here, not read off the row:

1. For each ``(request_id, volunteer_id)`` pair only the row with the newest
   ``last_update_date`` is current; older rows are treated as superseded
   history (a reassignment, or a changed ``volunteer_type``). Ties break on
   the higher ``volunteers_assigned_id`` so the result is deterministic.
2. A request in a terminal status - ``CANCELLED`` or ``DELETED``, see
   :data:`TERMINAL_REQUEST_STATUS_IDS` - has no current assignment at all.

Both rules live in one constant and one ``NOT EXISTS`` clause, so when an
assignment-status column is eventually added this module changes in exactly
two places. Until then, a volunteer is never dropped from the response merely
because their *user* status changed: an inactive volunteer who is still the
current assignee is still returned, with their status reported as
informational data.

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

# req_status_id values from the request_status lookup
# (database/lookup_tables/request_status.csv): 4 CANCELLED, 5 DELETED. A
# request in one of these states has no current volunteer assignment, however
# many historical rows volunteers_assigned still holds for it.
TERMINAL_REQUEST_STATUS_IDS = (4, 5)

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
               r.req_user_id,
               r.req_status_id
        FROM {SCHEMA_NAME}.request r
        WHERE r.req_id = %s
        """,
        [req_id],
    )
    return cursor.fetchone()


def fetch_assigned_volunteers(cursor: Any, req_id: str) -> list[dict[str, Any]]:
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
        WHERE va.request_id = %s
          AND NOT EXISTS (
                SELECT 1
                FROM {SCHEMA_NAME}.volunteers_assigned newer
                WHERE newer.request_id = va.request_id
                  AND newer.volunteer_id = va.volunteer_id
                  AND (newer.last_update_date > va.last_update_date
                       OR (newer.last_update_date = va.last_update_date
                           AND newer.volunteers_assigned_id
                               > va.volunteers_assigned_id))
          )
        ORDER BY va.last_update_date DESC, va.volunteer_id ASC
        """,
        [req_id],
    )
    return [_shape_volunteer(row) for row in cursor.fetchall()]


def _shape_volunteer(row: Any) -> dict[str, Any]:
    """Normalize one joined row into the response entry shape.

    Every key in :data:`VOLUNTEER_FIELDS` is always present, defaulting to
    ``None``, so missing or NULL optional profile information surfaces as
    ``null`` rather than as a missing key.

    Args:
        row: A row from :func:`fetch_assigned_volunteers`.

    Returns:
        A plain dict with exactly the response keys.
    """
    return {field: row.get(field) for field in VOLUNTEER_FIELDS}


def build_assigned_volunteers_response(
    cursor: Any, req_id: str
) -> tuple[int, dict[str, Any]]:
    """Resolve the full response for one ``req_id``.

    Args:
        cursor: An open dict-returning cursor.
        req_id: The validated request identifier.

    Returns:
        A ``(status_code, body)`` tuple. ``404`` when the request does not
        exist; otherwise ``200`` with the assigned volunteers, which is an
        empty list both when nothing is assigned and when the request is in a
        terminal status.
    """
    request_row = fetch_request(cursor, req_id)
    if request_row is None:
        return 404, {"error": f"no request found for req_id {req_id!r}"}

    if request_row.get("req_status_id") in TERMINAL_REQUEST_STATUS_IDS:
        return 200, {"req_id": req_id, "assignedVolunteers": []}

    return 200, {
        "req_id": req_id,
        "assignedVolunteers": fetch_assigned_volunteers(cursor, req_id),
    }


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
    print(json.dumps(lambda_handler({"req_id": "REQ-00-000-000-0018"}), indent=2))
