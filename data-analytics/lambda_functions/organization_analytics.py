import json
import os
from datetime import date

import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"

# Column required by the analytics spec but not guaranteed to be present in the
# deployed organizations table yet (see task note); contributor metrics degrade
# gracefully to 0 without it.
CONTRIBUTOR_COLUMN = "is_contributor"

VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
VALID_GROUP_BY = {"daily", "weekly", "monthly", "yearly"}

MIN_RATING = 1
MAX_RATING = 5

# ddl_organizations.sql declares org_type/org_size as lowercase enums
# ('non_profit', 'small'), but the source extracts in data-analytics/sql
# carry display labels ('Non-Profit', 'For-profit', 'Small'). Both are
# normalized to the enum form so the API reports the same buckets either way.
NORMALIZED_ORG_TYPE = "REPLACE(LOWER(o.org_type::text), '-', '_')"
NORMALIZED_ORG_SIZE = "REPLACE(LOWER(o.org_size::text), '-', '_')"

GROUP_BY_TRUNC = {
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
    "yearly": "year",
}


def normalize_label(value):
    """'Non-Profit' / 'non profit' / 'NON_PROFIT' -> 'non_profit'."""
    if value is None:
        return None
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def get_default_response():
    """Every dashboard section, empty. Matches the issue's suggested structure."""
    return {
        "summary": {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": 0,
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
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def get_db_connection():
    """Connect using plain environment variables only.

    The task forbids AWS Parameter Store / SSM, so credentials are read straight
    from the environment (injected by the Lambda config in deployment, or exported
    locally). No boto3, no hard-coded paths. `DB_SSLMODE` lets the deployed
    environment require TLS without changing the code.
    """
    connect_kwargs = dict(
        host=os.environ.get("DB_HOST", "localhost"),
        database=os.environ.get("DB_NAME", "saayam_local"),
        user=os.environ.get("DB_USER", "saayam"),
        password=os.environ.get("DB_PASSWORD", "saayam_local"),
        port=os.environ.get("DB_PORT", "5432"),
    )
    sslmode = os.environ.get("DB_SSLMODE")
    if sslmode:
        connect_kwargs["sslmode"] = sslmode

    conn = psycopg2.connect(**connect_kwargs)
    # Read-only workload: each statement stands alone, so one failed metric
    # cannot leave the connection in an aborted transaction.
    conn.autocommit = True
    return conn


def parse_event_body(event):
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


def has_contributor_column(cursor):
    """The organizations table may not carry is_contributor yet (see task notes)."""
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = 'organizations'
          AND column_name = %s;
        """,
        [SCHEMA_NAME, CONTRIBUTOR_COLUMN],
    )
    return cursor.fetchone() is not None


def parse_filters(request_body):
    time_filter = str(request_body.get("time_filter", "ALL")).upper()
    if time_filter not in VALID_TIME_FILTERS:
        time_filter = "ALL"

    group_by = str(request_body.get("group_by", "daily")).lower()
    if group_by not in VALID_GROUP_BY:
        group_by = "daily"

    region = request_body.get("region", None)
    if region is not None and str(region).strip().upper() == "ALL":
        region = None

    organization_type = request_body.get("organization_type", None)
    if organization_type is not None and str(organization_type).strip().upper() == "ALL":
        organization_type = None

    return {
        "time_filter": time_filter,
        "start_date": request_body.get("start_date", None),
        "end_date": request_body.get("end_date", None),
        "region": region,
        "organization_type": organization_type,
        "group_by": group_by,
    }


def validate_filters(filters):
    """Return an error message for filter combinations that cannot be honoured."""
    if filters["time_filter"] != "CUSTOM":
        return None

    start_date = filters["start_date"]
    end_date = filters["end_date"]

    if not start_date or not end_date:
        return "time_filter 'CUSTOM' requires both start_date and end_date (YYYY-MM-DD)."

    try:
        parsed_start = date.fromisoformat(str(start_date))
        parsed_end = date.fromisoformat(str(end_date))
    except ValueError:
        return "start_date and end_date must be ISO dates in YYYY-MM-DD format."

    if parsed_start > parsed_end:
        return "start_date must not be later than end_date."

    return None


def build_date_filter(filters, column="o.created_at"):
    time_filter = filters["time_filter"]
    start_date = filters["start_date"]
    end_date = filters["end_date"]

    if time_filter == "CUSTOM" and start_date and end_date:
        return f"{column}::date BETWEEN %s AND %s", [start_date, end_date]
    if time_filter == "7D":
        return f"{column} >= CURRENT_DATE - INTERVAL '7 days'", []
    if time_filter == "30D":
        return f"{column} >= CURRENT_DATE - INTERVAL '30 days'", []
    if time_filter == "1Y":
        return f"{column} >= CURRENT_DATE - INTERVAL '1 year'", []

    return "", []


def build_condition_list(filters):
    """SQL conditions + params for the common filters, without the WHERE keyword."""
    conditions = []
    params = []

    date_condition, date_params = build_date_filter(filters)
    if date_condition:
        conditions.append(date_condition)
        params.extend(date_params)

    if filters["organization_type"]:
        conditions.append(f"{NORMALIZED_ORG_TYPE} = %s")
        params.append(normalize_label(filters["organization_type"]))

    # Region matches either the state id (e.g. 'CA') or the state name
    # (e.g. 'California'), case-insensitively, so the same common filter the UI
    # already sends works whichever it carries.
    if filters["region"]:
        conditions.append(
            f"(o.state_id = %s OR EXISTS (SELECT 1 FROM {SCHEMA_NAME}.state s "
            "WHERE s.state_id = o.state_id AND LOWER(s.state_name) = LOWER(%s)))"
        )
        params.append(filters["region"])
        params.append(filters["region"])

    return conditions, params


def build_common_filters(filters):
    conditions, params = build_condition_list(filters)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where_clause, params


def _pct(part, whole):
    return round(part / whole * 100, 1) if whole else 0


# ---------------------------------------------------------------------------
# KPI summary cards
# ---------------------------------------------------------------------------

def fetch_summary(cursor, filters):
    where_clause, params = build_common_filters(filters)

    if filters.get("_has_contributor"):
        contributor_column = (
            f"COUNT(o.org_id) FILTER (WHERE o.{CONTRIBUTOR_COLUMN} IS TRUE)"
        )
    else:
        contributor_column = "0"

    query = f"""
        SELECT
            COUNT(o.org_id) AS total_organizations,
            COUNT(o.org_id) FILTER (WHERE o.is_collaborator IS TRUE) AS total_collaborators,
            {contributor_column} AS total_contributors,
            ROUND(AVG(o.org_rating)::numeric, 1) AS average_org_rating
        FROM {SCHEMA_NAME}.organizations o
        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    return {
        "total_organizations": int(row["total_organizations"]),
        "total_collaborators": int(row["total_collaborators"]),
        "total_contributors": int(row["total_contributors"]),
        "average_org_rating": (
            float(row["average_org_rating"]) if row["average_org_rating"] is not None else 0
        ),
    }


# ---------------------------------------------------------------------------
# Tab 1: Growth & Location
# ---------------------------------------------------------------------------

def fetch_growth_trend(cursor, filters):
    """Cumulative organizations and collaborators per period (line chart)."""
    where_clause, params = build_common_filters(filters)
    trunc_unit = GROUP_BY_TRUNC[filters["group_by"]]

    query = f"""
        SELECT
            DATE_TRUNC('{trunc_unit}', o.created_at)::date AS period,
            COUNT(o.org_id) AS new_organizations,
            COUNT(o.org_id) FILTER (WHERE o.is_collaborator IS TRUE) AS new_collaborators
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY period
        ORDER BY period;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    trend = []
    running_orgs = 0
    running_collabs = 0
    for row in rows:
        running_orgs += int(row["new_organizations"])
        running_collabs += int(row["new_collaborators"])
        trend.append({
            "period": str(row["period"]),
            "total_organizations": running_orgs,
            "total_collaborators": running_collabs,
        })
    return trend


def fetch_organizations_by_location(cursor, filters):
    """Organization count by state AND city.

    Grouped at the city grain in SQL, then rolled up in Python into one row per
    state (state_id, state_name, count, percentage) carrying a nested `cities`
    breakdown — so a single section serves both the state map and the city drill-down
    the dashboard needs.
    """
    where_clause, params = build_common_filters(filters)

    query = f"""
        SELECT
            o.state_id AS state_id,
            COALESCE(s.state_name, 'Unknown') AS state_name,
            COALESCE(o.city_name, 'Unknown') AS city_name,
            COUNT(o.org_id) AS organization_count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s
            ON o.state_id = s.state_id
        {where_clause}
        GROUP BY o.state_id, s.state_name, o.city_name
        ORDER BY organization_count DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    total = sum(int(row["organization_count"]) for row in rows)

    states = {}
    order = []
    for row in rows:
        key = (row["state_id"], row["state_name"])
        if key not in states:
            states[key] = {
                "state_id": row["state_id"],
                "state_name": row["state_name"],
                "organization_count": 0,
                "percentage": 0,
                "cities": [],
            }
            order.append(key)
        entry = states[key]
        count = int(row["organization_count"])
        entry["organization_count"] += count
        entry["cities"].append({
            "city_name": row["city_name"],
            "organization_count": count,
        })

    result = []
    for key in order:
        entry = states[key]
        entry["percentage"] = _pct(entry["organization_count"], total)
        entry["cities"].sort(key=lambda c: c["organization_count"], reverse=True)
        result.append(entry)

    result.sort(key=lambda e: e["organization_count"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# Tab 2: Size & Contribution
# ---------------------------------------------------------------------------

def fetch_organizations_by_size(cursor, filters):
    where_clause, params = build_common_filters(filters)

    query = f"""
        SELECT
            {NORMALIZED_ORG_SIZE} AS org_size,
            COUNT(o.org_id) AS organization_count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY {NORMALIZED_ORG_SIZE}
        ORDER BY organization_count DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "org_size": row["org_size"] if row["org_size"] is not None else "unknown",
            "organization_count": int(row["organization_count"]),
        }
        for row in rows
    ]


def fetch_collaborator_vs_contributor(cursor, filters):
    """Collaborator vs contributor counts with each side's share of the two."""
    where_clause, params = build_common_filters(filters)

    if filters.get("_has_contributor"):
        contributor_column = (
            f"COUNT(o.org_id) FILTER (WHERE o.{CONTRIBUTOR_COLUMN} IS TRUE)"
        )
    else:
        contributor_column = "0"

    query = f"""
        SELECT
            COUNT(o.org_id) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborators,
            {contributor_column} AS contributors
        FROM {SCHEMA_NAME}.organizations o
        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    collaborators = int(row["collaborators"])
    contributors = int(row["contributors"])
    denominator = collaborators + contributors

    return [
        {
            "type": "collaborator",
            "organization_count": collaborators,
            "percentage": _pct(collaborators, denominator),
        },
        {
            "type": "contributor",
            "organization_count": contributors,
            "percentage": _pct(contributors, denominator),
        },
    ]


# ---------------------------------------------------------------------------
# Tab 3: Ratings & Type
# ---------------------------------------------------------------------------

def fetch_rating_distribution(cursor, filters):
    # LEFT JOIN against generate_series so every rating 1-5 is present, including
    # the ones no organization currently holds (the dashboard charts all 5 bars).
    # NULL ratings simply do not match any bucket, so they never break the query.
    conditions, params = build_condition_list(filters)
    conditions.append("o.org_rating = r.rating")
    join_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            r.rating AS rating,
            COUNT(o.org_id) AS organization_count
        FROM generate_series({MIN_RATING}, {MAX_RATING}) AS r(rating)
        LEFT JOIN {SCHEMA_NAME}.organizations o
            ON {join_clause}
        GROUP BY r.rating
        ORDER BY r.rating;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "rating": int(row["rating"]),
            "organization_count": int(row["organization_count"]),
        }
        for row in rows
    ]


def fetch_organization_type_distribution(cursor, filters):
    """For-profit vs non-profit counts per period (stacked bar over time)."""
    where_clause, params = build_common_filters(filters)
    trunc_unit = GROUP_BY_TRUNC[filters["group_by"]]

    query = f"""
        SELECT
            DATE_TRUNC('{trunc_unit}', o.created_at)::date AS period,
            COUNT(o.org_id) FILTER (WHERE {NORMALIZED_ORG_TYPE} = 'for_profit') AS for_profit,
            COUNT(o.org_id) FILTER (WHERE {NORMALIZED_ORG_TYPE} = 'non_profit') AS non_profit
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY period
        ORDER BY period;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "period": str(row["period"]),
            "for_profit": int(row["for_profit"]),
            "non_profit": int(row["non_profit"]),
            "total": int(row["for_profit"]) + int(row["non_profit"]),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def run_metric(cursor, description, fetcher, filters):
    """Run one metric query, keeping the connection usable if it fails.

    PostgreSQL aborts the surrounding transaction on any error, so without the
    rollback below a single bad query would make every later metric fail with
    InFailedSqlTransaction. Returns None when the metric could not be produced,
    leaving the caller's safe default in place.
    """
    try:
        return fetcher(cursor, filters)
    except Exception as error:
        print(f"{description} query failed: {error}")
        try:
            cursor.connection.rollback()
        except Exception as rollback_error:
            print(f"Rollback after {description} failed: {rollback_error}")
        return None


def build_dashboard(cursor, filters):
    response_body = get_default_response()

    metrics = [
        ("summary", "Summary", fetch_summary),
        ("growth_trend", "Growth trend", fetch_growth_trend),
        ("organizations_by_location", "Organizations by location", fetch_organizations_by_location),
        ("organizations_by_size", "Organizations by size", fetch_organizations_by_size),
        ("collaborator_vs_contributor", "Collaborator vs contributor", fetch_collaborator_vs_contributor),
        ("rating_distribution", "Rating distribution", fetch_rating_distribution),
        ("organization_type_distribution", "Organization type distribution", fetch_organization_type_distribution),
    ]

    for key, description, fetcher in metrics:
        result = run_metric(cursor, description, fetcher, filters)
        if result is not None:
            response_body[key] = result

    return response_body


def lambda_handler(event, context):
    conn = None
    cursor = None

    request_body = parse_event_body(event)
    filters = parse_filters(request_body)

    validation_error = validate_filters(filters)
    if validation_error:
        return build_response(400, {"error": validation_error})

    response_body = get_default_response()

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        filters["_has_contributor"] = has_contributor_column(cursor)

        response_body = build_dashboard(cursor, filters)

        response_body["filters_applied"] = {
            key: value for key, value in filters.items() if not key.startswith("_")
        }
        if not filters["_has_contributor"]:
            response_body["schema_notes"] = [
                f"Column '{CONTRIBUTOR_COLUMN}' is not present in "
                f"{SCHEMA_NAME}.organizations; total_contributors and the "
                "contributor row return 0."
            ]
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
    result = lambda_handler({"time_filter": "ALL", "group_by": "monthly"}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))
