"""
Organization Analytics API for the Organization Dashboard.

Endpoint: POST /analytics/organizations

Returns every widget of the three-tab Organization Dashboard from a single call:

    summary                          -> the four common KPI cards
    growth_trend                     -> Tab 1, organizations + collaborators over time
    organizations_by_location        -> Tab 1, state (with nested city) breakdown
    organizations_by_size            -> Tab 2, small / medium / large
    collaborator_vs_contributor      -> Tab 2, count + percentage split
    rating_distribution              -> Tab 3, 1..5 stars
    organization_type_distribution   -> Tab 3, for_profit vs non_profit over time

Source tables: <schema>.organizations, <schema>.states

Database access is a plain local PostgreSQL connection configured through
environment variables. AWS Parameter Store is deliberately NOT used here.

    DB_HOST      (default: localhost)
    DB_PORT      (default: 5432)
    DB_NAME      (default: saayam)
    DB_USER      (default: postgres)
    DB_PASSWORD  (default: empty)
    DB_SSLMODE   (default: prefer)
    DB_SCHEMA    (default: virginia_dev_saayam_rdbms)
"""

import json
import os
import re
from datetime import datetime

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # driver is not needed for the mock-cursor unit tests
    psycopg2 = None
    RealDictCursor = None


DEFAULT_SCHEMA = "virginia_dev_saayam_rdbms"
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

SCHEMA_NAME = os.getenv("DB_SCHEMA", DEFAULT_SCHEMA).strip()
if not _IDENTIFIER_PATTERN.match(SCHEMA_NAME):
    raise ValueError(f"DB_SCHEMA is not a valid PostgreSQL identifier: {SCHEMA_NAME!r}")

ORGANIZATIONS_TABLE = f"{SCHEMA_NAME}.organizations"
# The issue names this lookup `states`, the existing analytics APIs and the sample
# data use `state`. Whichever one the connected database has is used.
STATE_LOOKUP_CANDIDATES = ("states", "state")

# Common dashboard filters, shared with the Request / Volunteer / Beneficiary / KPI APIs.
VALID_TIME_FILTERS = ("7D", "30D", "1Y", "ALL", "CUSTOM")
TIME_FILTER_INTERVALS = {
    "7D": "7 days",
    "30D": "30 days",
    "1Y": "1 year",
}

# group_by -> (DATE_TRUNC unit, TO_CHAR format)
GROUP_BY_SETTINGS = {
    "daily": ("day", "YYYY-MM-DD"),
    "weekly": ("week", 'IYYY-"W"IW'),
    "monthly": ("month", "YYYY-MM"),
    "yearly": ("year", "YYYY"),
}

VALID_ORGANIZATION_TYPES = ("ALL", "for_profit", "non_profit")
ORGANIZATION_SIZES = ("small", "medium", "large")
RATING_SCALE = (1, 2, 3, 4, 5)

DATE_FORMAT = "%Y-%m-%d"

# The sample data stores these as "Non-Profit" / "For-profit" / "Small", so both
# columns are normalised inside SQL before they are compared or grouped.
ORG_TYPE_EXPRESSION = "REPLACE(LOWER(TRIM(o.org_type)), '-', '_')"
ORG_SIZE_EXPRESSION = "LOWER(TRIM(o.org_size))"

RESPONSE_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


class FilterValidationError(ValueError):
    """Raised when the incoming dashboard filters are not usable."""


def get_default_response():
    """Empty but structurally complete payload, used for errors and as the base result."""
    return {
        "summary": {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": 0.0,
        },
        "growth_trend": [],
        "organizations_by_location": [],
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
        "rating_distribution": [],
        "organization_type_distribution": [],
    }


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": RESPONSE_HEADERS,
        "body": json.dumps(body, default=str),
    }


def parse_event_body(event):
    """Accept both a raw API Gateway event and a plain dict payload."""
    if not event:
        return {}

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise FilterValidationError("Request body is not valid JSON.")

    if isinstance(body, dict):
        return body

    return {}


def _parse_date(value, field_name):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise FilterValidationError(
            f"'{field_name}' is required when time_filter is CUSTOM."
        )

    if isinstance(value, datetime):
        return value.strftime(DATE_FORMAT)

    try:
        return datetime.strptime(str(value).strip(), DATE_FORMAT).strftime(DATE_FORMAT)
    except ValueError:
        raise FilterValidationError(
            f"'{field_name}' must be a date in YYYY-MM-DD format, got {value!r}."
        )


def parse_filters(request_body):
    """Validate the common dashboard filters and return them in a normalised form."""
    request_body = request_body or {}

    time_filter = str(request_body.get("time_filter") or "ALL").strip().upper()
    if time_filter not in VALID_TIME_FILTERS:
        raise FilterValidationError(
            f"Invalid time_filter {time_filter!r}. Supported values: {', '.join(VALID_TIME_FILTERS)}."
        )

    group_by = str(request_body.get("group_by") or "monthly").strip().lower()
    if group_by not in GROUP_BY_SETTINGS:
        raise FilterValidationError(
            f"Invalid group_by {group_by!r}. Supported values: {', '.join(GROUP_BY_SETTINGS)}."
        )

    start_date = None
    end_date = None
    if time_filter == "CUSTOM":
        start_date = _parse_date(request_body.get("start_date"), "start_date")
        end_date = _parse_date(request_body.get("end_date"), "end_date")
        if start_date > end_date:
            raise FilterValidationError(
                "'start_date' must be on or before 'end_date' for a CUSTOM range."
            )

    region = str(request_body.get("region") or "ALL").strip()
    if not region:
        region = "ALL"

    raw_org_type = str(request_body.get("organization_type") or "ALL").strip()
    organization_type = (
        "ALL"
        if raw_org_type.upper() == "ALL"
        else raw_org_type.lower().replace("-", "_")
    )
    if organization_type not in VALID_ORGANIZATION_TYPES:
        raise FilterValidationError(
            f"Invalid organization_type {raw_org_type!r}. "
            f"Supported values: {', '.join(VALID_ORGANIZATION_TYPES)}."
        )

    return {
        "time_filter": time_filter,
        "start_date": start_date,
        "end_date": end_date,
        "group_by": group_by,
        "region": region,
        "organization_type": organization_type,
    }


def relation_exists(cursor, table_name, column_name=None):
    """Check information_schema for a table, or for a column inside that table."""
    try:
        if column_name is None:
            cursor.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
                LIMIT 1;
                """,
                (SCHEMA_NAME, table_name),
            )
        else:
            cursor.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s AND column_name = %s
                LIMIT 1;
                """,
                (SCHEMA_NAME, table_name, column_name),
            )
        return cursor.fetchone() is not None
    except Exception as error:
        # Fall back to the narrower behaviour rather than failing the whole request.
        print(f"Schema introspection failed for {table_name}.{column_name}: {error}")
        return False


def build_schema_context(cursor):
    """
    Adapt the SQL to whatever the connected database actually has.

    `is_contributor` is a recent column and may be missing in dev, and the state
    lookup table may be named `states` or `state`, so neither is allowed to break
    the request.
    """
    state_table = next(
        (name for name in STATE_LOOKUP_CANDIDATES if relation_exists(cursor, name)),
        None,
    )
    has_states = state_table is not None
    has_contributor = relation_exists(cursor, "organizations", "is_contributor")

    from_clause = f"FROM {ORGANIZATIONS_TABLE} o"
    if has_states:
        from_clause += (
            f" LEFT JOIN {SCHEMA_NAME}.{state_table} s ON o.state_id = s.state_id"
        )

    state_id_expression = "COALESCE(NULLIF(TRIM(o.state_id::text), ''), 'Unknown')"
    if has_states:
        state_name_expression = (
            "COALESCE(NULLIF(TRIM(s.state_name), ''), "
            "NULLIF(TRIM(o.state_id::text), ''), 'Unknown')"
        )
    else:
        state_name_expression = state_id_expression

    return {
        "has_states": has_states,
        "state_table": state_table,
        "has_contributor": has_contributor,
        "from_clause": from_clause,
        "state_id_expression": state_id_expression,
        "state_name_expression": state_name_expression,
        # COUNT(*) FILTER (WHERE FALSE) is valid SQL and yields 0.
        "contributor_expression": "o.is_contributor IS TRUE" if has_contributor else "FALSE",
    }


def build_where_clause(filters, context, extra_conditions=None):
    """
    Build the shared WHERE clause for every widget.

    Returns (sql, params) with every user supplied value passed as a bound parameter.
    """
    conditions = ["o.created_at IS NOT NULL"]
    params = []

    time_filter = filters["time_filter"]
    if time_filter == "CUSTOM":
        conditions.append("o.created_at >= %s::date")
        conditions.append("o.created_at < (%s::date + INTERVAL '1 day')")
        params.append(filters["start_date"])
        params.append(filters["end_date"])
    elif time_filter in TIME_FILTER_INTERVALS:
        conditions.append("o.created_at >= CURRENT_DATE - %s::interval")
        params.append(TIME_FILTER_INTERVALS[time_filter])

    region = filters["region"]
    if region.upper() != "ALL":
        if context["has_states"]:
            conditions.append(
                "(UPPER(TRIM(COALESCE(s.state_name, ''))) = UPPER(%s)"
                " OR UPPER(TRIM(COALESCE(o.state_id::text, ''))) = UPPER(%s))"
            )
            params.append(region)
            params.append(region)
        else:
            conditions.append("UPPER(TRIM(COALESCE(o.state_id::text, ''))) = UPPER(%s)")
            params.append(region)

    organization_type = filters["organization_type"]
    if organization_type != "ALL":
        conditions.append(f"{ORG_TYPE_EXPRESSION} = %s")
        params.append(organization_type)

    for condition in extra_conditions or []:
        conditions.append(condition)

    return "WHERE " + " AND ".join(conditions), params


def _to_int(value):
    return int(value) if value is not None else 0


def _percentage(count, total):
    return round(count * 100.0 / total, 1) if total else 0.0


def fetch_summary(cursor, filters, context):
    """The four common KPI cards."""
    where_clause, params = build_where_clause(filters, context)

    query = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS total_collaborators,
            COUNT(*) FILTER (WHERE {context['contributor_expression']}) AS total_contributors,
            ROUND(AVG(o.org_rating)::numeric, 1) AS average_org_rating
        {context['from_clause']}
        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone() or {}

    average_rating = row.get("average_org_rating")
    return {
        "total_organizations": _to_int(row.get("total_organizations")),
        "total_collaborators": _to_int(row.get("total_collaborators")),
        "total_contributors": _to_int(row.get("total_contributors")),
        "average_org_rating": float(average_rating) if average_rating is not None else 0.0,
    }


def fetch_growth_trend(cursor, filters, context):
    """Running totals of organizations and collaborators, grouped by the selected period."""
    trunc_unit, date_format = GROUP_BY_SETTINGS[filters["group_by"]]
    where_clause, where_params = build_where_clause(filters, context)

    query = f"""
        SELECT
            period,
            SUM(new_organizations) OVER (ORDER BY period) AS total_organizations,
            SUM(new_collaborators) OVER (ORDER BY period) AS total_collaborators
        FROM (
            SELECT
                TO_CHAR(DATE_TRUNC(%s, o.created_at), %s) AS period,
                COUNT(*) AS new_organizations,
                COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS new_collaborators
            {context['from_clause']}
            {where_clause}
            GROUP BY 1
        ) grouped
        ORDER BY period ASC;
    """

    cursor.execute(query, [trunc_unit, date_format] + where_params)

    return [
        {
            "period": row["period"],
            "total_organizations": _to_int(row["total_organizations"]),
            "total_collaborators": _to_int(row["total_collaborators"]),
        }
        for row in cursor.fetchall()
    ]


def fetch_organizations_by_location(cursor, filters, context):
    """
    State level counts with the matching city breakdown nested underneath.

    Percentages are relative to the total number of organizations in the window.
    """
    where_clause, params = build_where_clause(filters, context)

    query = f"""
        SELECT
            {context['state_id_expression']} AS state_id,
            {context['state_name_expression']} AS state_name,
            COALESCE(NULLIF(TRIM(o.city_name), ''), 'Unknown') AS city_name,
            COUNT(*) AS organization_count
        {context['from_clause']}
        {where_clause}
        GROUP BY 1, 2, 3
        ORDER BY 1, 3;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    states = {}
    total = 0
    for row in rows:
        count = _to_int(row["organization_count"])
        total += count

        state = states.setdefault(
            row["state_id"],
            {
                "state_id": row["state_id"],
                "state_name": row["state_name"],
                "organization_count": 0,
                "percentage": 0.0,
                "cities": [],
            },
        )
        state["organization_count"] += count
        state["cities"].append(
            {"city_name": row["city_name"], "organization_count": count}
        )

    location = sorted(
        states.values(),
        key=lambda state: (-state["organization_count"], state["state_id"]),
    )
    for state in location:
        state["percentage"] = _percentage(state["organization_count"], total)
        state["cities"].sort(
            key=lambda city: (-city["organization_count"], city["city_name"])
        )

    return location


def fetch_organizations_by_size(cursor, filters, context):
    """Small / medium / large distribution, always returning all three buckets."""
    where_clause, params = build_where_clause(filters, context)

    query = f"""
        SELECT
            COALESCE(NULLIF({ORG_SIZE_EXPRESSION}, ''), 'unknown') AS org_size,
            COUNT(*) AS organization_count
        {context['from_clause']}
        {where_clause}
        GROUP BY 1;
    """

    cursor.execute(query, params)
    counts = {row["org_size"]: _to_int(row["organization_count"]) for row in cursor.fetchall()}

    distribution = [
        {"org_size": size, "organization_count": counts.pop(size, 0)}
        for size in ORGANIZATION_SIZES
    ]
    # Anything the database holds outside the three supported values is still reported.
    distribution.extend(
        {"org_size": size, "organization_count": counts[size]}
        for size in sorted(counts)
    )
    return distribution


def fetch_collaborator_vs_contributor(cursor, filters, context):
    """Collaborator and contributor counts with their share of the two combined."""
    where_clause, params = build_where_clause(filters, context)

    query = f"""
        SELECT
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_count,
            COUNT(*) FILTER (WHERE {context['contributor_expression']}) AS contributor_count
        {context['from_clause']}
        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone() or {}

    collaborators = _to_int(row.get("collaborator_count"))
    contributors = _to_int(row.get("contributor_count"))
    total = collaborators + contributors

    return [
        {
            "type": "collaborator",
            "organization_count": collaborators,
            "percentage": _percentage(collaborators, total),
        },
        {
            "type": "contributor",
            "organization_count": contributors,
            "percentage": _percentage(contributors, total),
        },
    ]


def fetch_rating_distribution(cursor, filters, context):
    """1..5 star distribution. Organizations with a NULL rating are skipped, not failed on."""
    where_clause, params = build_where_clause(
        filters,
        context,
        extra_conditions=["o.org_rating IS NOT NULL", "o.org_rating BETWEEN 1 AND 5"],
    )

    query = f"""
        SELECT
            o.org_rating::int AS rating,
            COUNT(*) AS organization_count
        {context['from_clause']}
        {where_clause}
        GROUP BY 1
        ORDER BY 1;
    """

    cursor.execute(query, params)
    counts = {_to_int(row["rating"]): _to_int(row["organization_count"]) for row in cursor.fetchall()}

    return [
        {"rating": rating, "organization_count": counts.get(rating, 0)}
        for rating in RATING_SCALE
    ]


def fetch_organization_type_distribution(cursor, filters, context):
    """For-profit vs non-profit running totals per period, for the stacked bar chart."""
    trunc_unit, date_format = GROUP_BY_SETTINGS[filters["group_by"]]
    where_clause, where_params = build_where_clause(filters, context)

    query = f"""
        SELECT
            period,
            SUM(new_for_profit) OVER (ORDER BY period) AS for_profit,
            SUM(new_non_profit) OVER (ORDER BY period) AS non_profit
        FROM (
            SELECT
                TO_CHAR(DATE_TRUNC(%s, o.created_at), %s) AS period,
                COUNT(*) FILTER (WHERE {ORG_TYPE_EXPRESSION} = 'for_profit') AS new_for_profit,
                COUNT(*) FILTER (WHERE {ORG_TYPE_EXPRESSION} = 'non_profit') AS new_non_profit
            {context['from_clause']}
            {where_clause}
            GROUP BY 1
        ) grouped
        ORDER BY period ASC;
    """

    cursor.execute(query, [trunc_unit, date_format] + where_params)

    distribution = []
    for row in cursor.fetchall():
        for_profit = _to_int(row["for_profit"])
        non_profit = _to_int(row["non_profit"])
        distribution.append(
            {
                "period": row["period"],
                "for_profit": for_profit,
                "non_profit": non_profit,
                "total": for_profit + non_profit,
            }
        )
    return distribution


# section key -> (fetch function, value used when that single query fails)
DASHBOARD_SECTIONS = (
    ("summary", fetch_summary, None),
    ("growth_trend", fetch_growth_trend, []),
    ("organizations_by_location", fetch_organizations_by_location, []),
    ("organizations_by_size", fetch_organizations_by_size, []),
    ("collaborator_vs_contributor", fetch_collaborator_vs_contributor, []),
    ("rating_distribution", fetch_rating_distribution, []),
    ("organization_type_distribution", fetch_organization_type_distribution, []),
)


def get_db_config():
    """Local PostgreSQL connection settings. AWS Parameter Store is not used."""
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME", "saayam"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
        "sslmode": os.getenv("DB_SSLMODE", "prefer"),
    }


def get_db_connection():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed; cannot open a database connection.")
    return psycopg2.connect(**get_db_config())


def lambda_handler(event, context):
    conn = None
    cursor = None
    response_body = get_default_response()

    try:
        filters = parse_filters(parse_event_body(event))
    except FilterValidationError as error:
        print(f"Invalid dashboard filters: {error}")
        response_body["error"] = str(error)
        return build_response(400, response_body)

    response_body["filters_applied"] = filters

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        schema_context = build_schema_context(cursor)

        for section, fetch, empty_value in DASHBOARD_SECTIONS:
            try:
                response_body[section] = fetch(cursor, filters, schema_context)
            except Exception as error:
                # One failing widget must not take the whole dashboard down.
                print(f"Query for '{section}' failed: {error}")
                if empty_value is not None:
                    response_body[section] = empty_value

        return build_response(200, response_body)

    except Exception as error:
        print(f"DB connection failed: {error}")
        return build_response(500, response_body)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    sample_payloads = {
        "Standard test (30D, daily)": {
            "time_filter": "30D",
            "start_date": None,
            "end_date": None,
            "group_by": "daily",
            "region": "ALL",
            "organization_type": "ALL",
        },
        "Last 12 months (1Y, monthly)": {
            "time_filter": "1Y",
            "start_date": None,
            "end_date": None,
            "group_by": "monthly",
            "region": "ALL",
            "organization_type": "ALL",
        },
        "Filter by region": {
            "time_filter": "1Y",
            "start_date": None,
            "end_date": None,
            "group_by": "monthly",
            "region": "California",
            "organization_type": "ALL",
        },
        "Filter by organization type": {
            "time_filter": "1Y",
            "start_date": None,
            "end_date": None,
            "group_by": "monthly",
            "region": "ALL",
            "organization_type": "non_profit",
        },
        "Custom date range": {
            "time_filter": "CUSTOM",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "group_by": "monthly",
            "region": "ALL",
            "organization_type": "ALL",
        },
    }

    for name, payload in sample_payloads.items():
        print(f"\n===== {name} =====")
        print(json.dumps(lambda_handler(payload, None), indent=2))
