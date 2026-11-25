"""Find volunteers for a request (issue #717).

API Gateway must authenticate the caller and supply the Saayam user_id in its
authorizer context (user_id, lambda.user_id, or claims/custom:user_id). Never
accept identity from the body or decode an unverified Authorization header.

Configure DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, optional DB_PORT, and optional
VOLUNTEER_SEARCH_SCHEMA (default: virginia_dev_saayam_rdbms). Uses the existing
psycopg2 Lambda dependency. Both the issue's table names and the older database
schema names in this repository are supported, with explicit column projections.
"""

import json
import os
import re
from contextlib import contextmanager

FORBIDDEN = "Only the lead volunteer for this request can search for volunteers"
EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+\Z")
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
USER_ID_PATTERN = re.compile(r"SID-[0-9]+(?:-[0-9]+)*\Z")

# Canonical names come from the issue. Alternatives cover the older DB schema.
TABLE_NAMES = {
    "requests": ("requests", "request"),
    "users": ("users",),
    "volunteer_details": ("volunteer_details",),
    "countries": ("countries", "country"),
    "user_skills": ("user_skills",),
    "help_category": ("help_category", "help_categories"),
    "volunteers_assigned": ("volunteers_assigned",),
    "volunteer_ratings": ("volunteer_ratings", "volunteer_rating"),
}


class ApiError(Exception):
    """An expected API error with a public, non-sensitive message."""

    def __init__(self, status_code, message):
        """Keep the HTTP status alongside the public error message."""
        super().__init__(message)
        self.status_code = status_code


def build_response(status_code, body):
    """Return the analytics API envelope, including CORS on errors."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body, allow_nan=False),
    }


def validate_body(event):
    """Parse and validate the JSON body once before opening a connection."""
    body = event.get("body")
    if body is None or body == "" or body == {}:
        raise ApiError(400, "Request body is required")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except (ValueError, RecursionError):
            raise ApiError(400, "Request body must be a valid JSON object") from None
    if not isinstance(body, dict):
        raise ApiError(400, "Request body must be a JSON object")
    if not body:
        raise ApiError(400, "Request body is required")

    request_id = body.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ApiError(400, "request_id is required")
    search_field = body.get("search_field")
    if not isinstance(search_field, str) or search_field not in SEARCH_FIELDS:
        raise ApiError(400, "search_field must be name, email or phone")
    query = body.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ApiError(400, "query is required and must be a string")
    query = query.strip()
    if search_field == "name" and len(query) < 3:
        raise ApiError(400, "Name query must contain at least 3 characters")
    if search_field == "email" and not EMAIL_PATTERN.fullmatch(query):
        raise ApiError(400, "query must be a valid email address")
    if search_field == "phone" and len(phone_digits(query)) < 7:
        raise ApiError(400, "Phone query must contain at least 7 digits")
    return request_id.strip(), search_field, query


def get_caller_id(event):
    """Read a Saayam ID only from trusted REST/HTTP API authorizer context."""
    context = event.get("requestContext")
    authorizer = context.get("authorizer") if isinstance(context, dict) else None
    if not isinstance(authorizer, dict):
        raise ApiError(401, "Missing or invalid caller")
    sources = [authorizer, authorizer.get("lambda"), authorizer.get("claims")]
    jwt = authorizer.get("jwt")
    if isinstance(jwt, dict):
        sources.append(jwt.get("claims"))
    ids = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("user_id", "custom:user_id"):
            if key not in source:
                continue
            value = source[key]
            if not isinstance(value, str) or not USER_ID_PATTERN.fullmatch(value):
                raise ApiError(401, "Missing or invalid caller")
            ids.append(value)
    if not ids or len(set(ids)) != 1:
        raise ApiError(401, "Missing or invalid caller")
    return ids[0]


def phone_digits(value):
    """Use the same ASCII digits as PostgreSQL's phone normalization."""
    return re.sub(r"[^0-9]", "", value)


def search_by_name(query):
    """Match literal, case-insensitive prefixes of full, first, or last name."""
    value = query.lower()
    fields = ("full_name", "first_name", "last_name")
    # LEFT/equality treats percent, underscore and backslash as literal text.
    exact = " OR ".join(f"LOWER(BTRIM(u.{name})) = %s" for name in fields)
    prefix = " OR ".join(
        f"LEFT(LOWER(BTRIM(u.{name})), LENGTH(%s)) = %s" for name in fields
    )
    return f"({prefix})", [value] * 6, f"({exact})", [value] * 3


def search_by_email(query):
    """Match the primary email exactly, ignoring case."""
    clause = "LOWER(u.primary_email_address) = %s"
    return clause, [query.lower()], clause, [query.lower()]


def search_by_phone(query):
    """Match seven-to-ten-digit suffixes; longer numbers use the last ten."""
    digits = phone_digits(query)
    suffix = digits[-10:]
    stored = "REGEXP_REPLACE(u.primary_phone_number, '[^0-9]', '', 'g')"
    return (
        f"RIGHT({stored}, LENGTH(%s)) = %s", [suffix, suffix],
        f"{stored} = %s", [digits],
    )


SEARCH_FIELDS = {
    "name": search_by_name,
    "email": search_by_email,
    "phone": search_by_phone,
}


@contextmanager
def open_data_source():
    """Own the read-only database connection and always release it."""
    import psycopg2

    connection = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=10,
    )
    try:
        # Keep the lead/beneficiary check and search on the same data snapshot.
        connection.set_session(
            readonly=True, isolation_level="REPEATABLE READ", autocommit=False,
        )
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '15s'")
            yield SearchData(cursor)
    finally:
        connection.close()


class SearchData:
    """Load requests and matching volunteers without reading sensitive columns."""

    def __init__(self, cursor):
        """Resolve the configured schema using only table/column metadata."""
        self.cursor = cursor
        schema = os.environ.get("VOLUNTEER_SEARCH_SCHEMA", "virginia_dev_saayam_rdbms")
        if not IDENTIFIER_PATTERN.fullmatch(schema):
            raise RuntimeError("Invalid database schema configuration")
        self.schema = schema
        # Read column metadata to handle the documented legacy naming variants.
        names = [name for aliases in TABLE_NAMES.values() for name in aliases]
        cursor.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = ANY(%s)", (schema, names),
        )
        self.columns = {}
        for table, column in cursor.fetchall():
            self.columns.setdefault(table, set()).add(column)

    def table(self, name):
        """Resolve a whitelisted canonical or legacy table name."""
        for candidate in TABLE_NAMES[name]:
            if candidate in self.columns:
                return f'"{self.schema}"."{candidate}"'
        raise RuntimeError("Required search table is missing")

    def column(self, table, *alternatives):
        """Resolve one of the explicit, non-sensitive column alternatives."""
        name = self.table(table).split('"')[-2]
        for candidate in alternatives:
            if candidate in self.columns[name]:
                return candidate
        raise RuntimeError("Required search column is missing")

    def get_request(self, request_id):
        """Load authorization fields without requiring a users row for the lead."""
        request_key = self.column("requests", "req_id", "request_id")
        self.cursor.execute(
            f"SELECT lead_volunteer_id, beneficiary_id FROM {self.table('requests')} "
            f"WHERE {request_key} = %s", (request_id,),
        )
        return self.cursor.fetchone()

    def load_volunteers(self, request_id, caller_id, beneficiary_id, search):
        """Search eligible users and enrich only the matching rows."""
        predicate, match_params, exact, exact_params = search
        assigned_key = self.column("volunteers_assigned", "req_id", "request_id")
        updated = self.column("user_skills", "last_updated_at", "last_update_date")
        query = f"""
            SELECT u.user_id AS volunteer_id,
                   NULLIF(BTRIM(u.full_name), '') AS name,
                   skill.cause,
                   NULLIF(CONCAT_WS(', ', NULLIF(BTRIM(u.city_name), ''),
                       NULLIF(BTRIM(c.country_code), '')), '') AS location,
                   ratings.rating,
                   CASE WHEN BTRIM(u.primary_phone_number) <> ''
                       THEN u.primary_phone_number END AS phone,
                   CASE WHEN BTRIM(u.primary_email_address) <> ''
                       THEN u.primary_email_address END AS email,
                   EXISTS (
                       SELECT 1 FROM {self.table('volunteers_assigned')} va
                       WHERE va.{assigned_key} = %s AND va.volunteer_id = u.user_id
                   ) AS already_assigned
            FROM {self.table('users')} u
            LEFT JOIN {self.table('countries')} c ON c.country_id = u.country_id
            LEFT JOIN LATERAL (
                SELECT NULLIF(BTRIM(h.cat_name), '') AS cause
                FROM {self.table('user_skills')} us
                JOIN {self.table('help_category')} h ON h.cat_id::text = us.cat_id::text
                WHERE us.user_id = u.user_id AND us.cat_id::text <> '0.0.0.0.0'
                ORDER BY us.{updated} DESC NULLS LAST, us.cat_id::text ASC
                LIMIT 1
            ) skill ON TRUE
            LEFT JOIN LATERAL (
                SELECT ROUND(AVG(CASE vr.rating::text
                    WHEN 'POOR' THEN 1 WHEN 'BELOW_AVERAGE' THEN 2
                    WHEN 'AVERAGE' THEN 3 WHEN 'GOOD' THEN 4
                    WHEN 'EXCELLENT' THEN 5 END), 1) AS rating
                FROM {self.table('volunteer_ratings')} vr
                WHERE vr.user_id = u.user_id
            ) ratings ON TRUE
            WHERE u.user_status_id = 1
              AND EXISTS (SELECT 1 FROM {self.table('volunteer_details')} vd
                          WHERE vd.user_id = u.user_id)
              AND u.user_id <> %s
              AND u.user_id IS DISTINCT FROM %s
              AND ({predicate})
            ORDER BY CASE WHEN ({exact}) THEN 0 ELSE 1 END,
                     LOWER(BTRIM(u.full_name)) ASC NULLS LAST, u.user_id ASC
        """
        params = [request_id, caller_id, beneficiary_id] + match_params + exact_params
        self.cursor.execute(query, params)
        fields = ("volunteer_id", "name", "cause", "location", "rating",
                  "phone", "email", "already_assigned")
        volunteers = []
        for row in self.cursor.fetchall():
            volunteer = dict(zip(fields, row))
            if volunteer["rating"] is not None:
                volunteer["rating"] = float(volunteer["rating"])
            volunteers.append(volunteer)
        return volunteers


def lambda_handler(event, context):
    """Validate and authorize once, then dispatch the requested search field."""
    if not isinstance(event, dict):
        return build_response(400, {"error": "Request body is required"})
    request_context = event.get("requestContext")
    http = request_context.get("http") if isinstance(request_context, dict) else None
    method = event.get("httpMethod")
    if isinstance(http, dict):
        method = http.get("method", method)
    if method == "OPTIONS":
        return build_response(200, {})
    try:
        request_id, search_field, query = validate_body(event)
        caller_id = get_caller_id(event)
        with open_data_source() as data:
            request = data.get_request(request_id)
            if request is None:
                raise ApiError(400, "Request does not exist")
            lead_id, beneficiary_id = request
            if lead_id is None or caller_id != lead_id:
                raise ApiError(403, FORBIDDEN)
            search = SEARCH_FIELDS[search_field](query)
            volunteers = data.load_volunteers(
                request_id, caller_id, beneficiary_id, search,
            )
        return build_response(200, {
            "request_id": request_id, "search_field": search_field, "query": query,
            "total": len(volunteers), "volunteers": volunteers,
        })
    except ApiError as exc:
        return build_response(exc.status_code, {"error": str(exc)})
    except Exception:  # noqa: BLE001 - redact every failure at the API boundary.
        # Exception messages/tracebacks can contain SQL parameters or DB secrets.
        # Do not print or log them, nor the event, contacts, query, or tokens.
        return build_response(500, {"error": "Internal server error"})
