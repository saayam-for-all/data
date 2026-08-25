"""
Organization Analytics API

Provides the data backing the Saayam "Organization Dashboard":
  1. Organization Overview Dashboard  -> get_organization_overview()
  2. Organization Performance Dashboard -> get_organization_performance()

Source table: virginia_dev_saayam_rdbms.organizations
Reference:    virginia_dev_saayam_rdbms.state

Follows the same structure/coding standards used by the existing
Volunteer, Beneficiary, and KPI analytics lambda functions in this folder:
  - a single Virginia RDS connection pulled from SSM
  - small `fetch_*` functions, one per metric, each returning plain
    dict/list structures that map 1:1 onto the JSON response
  - every metric fetch is wrapped in its own try/except in the handler
    so a single failing query never breaks the whole dashboard response
  - a `__main__` block that runs the module against a local Postgres
    instance for manual/local testing (see bottom of file)

NOTE on `is_contributor`:
  The `organizations` table (see database/ddl/Tables/ddl_organizations.sql)
  currently only has `is_collaborator`. The dashboard spec (issue #228)
  additionally asks for a "Contributor" split. Until an `is_contributor`
  column is added to the table via a migration, every contributor-related
  fetch function below is isolated behind its own try/except and will
  degrade gracefully to empty/zeroed results instead of failing the whole
  request. Once the column exists, no code changes are required.
"""

import json
import boto3
import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ORGANIZATIONS_TABLE = f"{SCHEMA_NAME}.organizations"
STATE_TABLE = f"{SCHEMA_NAME}.state"

VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
GROUP_BY_TRUNC = {
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
    "yearly": "year",
}
GROUP_BY_FORMAT = {
    "daily": "YYYY-MM-DD",
    "weekly": "YYYY-MM-DD",
    "monthly": "YYYY-MM",
    "yearly": "YYYY",
}

TOP_N_DEFAULT = 10


def safe_rollback(cursor):
    """
    Rolls back the current transaction on `cursor`'s connection.
    Needed because Postgres aborts the whole transaction after a failed
    statement (e.g. a query referencing a column that doesn't exist yet,
    such as `is_contributor`) -- without a rollback, every subsequent
    query on that same connection would fail too, even unrelated ones.
    """
    try:
        cursor.connection.rollback()
    except Exception as rollback_error:
        print(f"rollback failed: {rollback_error}")


# ---------------------------------------------------------------------------
# Response / connection helpers (mirrors kpi_api_analytics.py)
# ---------------------------------------------------------------------------

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
    ssm = boto3.client("ssm", region_name="us-east-1")

    response = ssm.get_parameter(
        Name="/dev/saayam/db/Virginia/Analytics/user",
        WithDecryption=True,
    )

    creds = json.loads(response["Parameter"]["Value"])
    db_name = creds["DATABASE NAME"]
    return psycopg2.connect(
        host=creds["HOST"],
        database=db_name,
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require",
    )


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


def get_default_overview_response():
    return {
        "organization_overview": {
            "summary": {
                "total_organizations": 0,
                "non_profit_organizations": 0,
                "for_profit_organizations": 0,
                "collaborator_organizations": 0,
                "non_collaborator_organizations": 0,
                "contributor_organizations": 0,
                "non_contributor_organizations": 0,
            },
            "organization_activity_trend": [],
            "organizations_by_type": [],
            "organizations_by_size": [],
            "organizations_by_location": [],
            "collaborator_distribution": [],
            "contributor_distribution": [],
        }
    }


def get_default_performance_response():
    return {
        "organization_performance": {
            "summary": {
                "average_rating": 0,
                "rated_organizations": 0,
                "unrated_organizations": 0,
                "five_star_organizations": 0,
            },
            "rating_distribution": [],
            "top_rated_organizations": [],
            "top_collaborator_organizations": [],
            "top_contributor_organizations": [],
            "ratings_by_organization_type": [],
            "ratings_by_organization_size": [],
        }
    }


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------

def build_date_filter(time_filter, start_date=None, end_date=None, column="o.created_at"):
    """
    Returns (sql_condition, params_tuple) for the registration-date filter.

    time_filter values: "7D", "30D", "1Y", "ALL", "CUSTOM"
    """
    time_filter = (time_filter or "ALL").upper()

    if time_filter == "CUSTOM" and start_date and end_date:
        return f"{column} BETWEEN %s AND %s", (start_date, end_date)
    elif time_filter == "7D":
        return f"{column} >= CURRENT_DATE - INTERVAL '7 days'", ()
    elif time_filter == "30D":
        return f"{column} >= CURRENT_DATE - INTERVAL '30 days'", ()
    elif time_filter == "1Y":
        return f"{column} >= CURRENT_DATE - INTERVAL '1 year'", ()
    else:
        # "ALL" or unrecognized -> no date filter
        return "", ()


def build_common_filters(filters):
    """
    Builds SQL conditions + params from the shared filter set described in
    issue #228 ("Common Filters for Both Dashboards"):
        org_type, org_size, state_id, city_name, org_rating,
        is_collaborator, is_contributor, time_filter/start_date/end_date.

    `is_contributor` is intentionally left out of the WHERE clause here
    (see module docstring) and is applied only by the isolated contributor
    fetch functions, guarded by their own try/except.
    """
    conditions = []
    params = []

    org_type = filters.get("org_type")
    if org_type:
        conditions.append("o.org_type = %s::org_type_enum")
        params.append(org_type)

    org_size = filters.get("org_size")
    if org_size:
        conditions.append("o.org_size = %s::org_size_enum")
        params.append(org_size)

    state_id = filters.get("state_id")
    if state_id:
        conditions.append("o.state_id = %s")
        params.append(state_id)

    city_name = filters.get("city_name")
    if city_name:
        conditions.append("o.city_name = %s")
        params.append(city_name)

    org_rating = filters.get("org_rating")
    if org_rating is not None:
        conditions.append("o.org_rating = %s")
        params.append(org_rating)

    is_collaborator = filters.get("is_collaborator")
    if is_collaborator is not None:
        conditions.append("o.is_collaborator = %s")
        params.append(bool(is_collaborator))

    date_condition, date_params = build_date_filter(
        filters.get("time_filter", "ALL"),
        filters.get("start_date"),
        filters.get("end_date"),
    )
    if date_condition:
        conditions.append(date_condition)
        params.extend(date_params)

    return conditions, params


def where_clause(conditions):
    return f"WHERE {' AND '.join(conditions)}" if conditions else ""


def get_group_by_unit(group_by):
    group_by = (group_by or "daily").lower()
    if group_by not in GROUP_BY_TRUNC:
        group_by = "daily"
    return GROUP_BY_TRUNC[group_by], GROUP_BY_FORMAT[group_by]


# ---------------------------------------------------------------------------
# Dashboard 1: Organization Overview
# ---------------------------------------------------------------------------

def fetch_overview_summary(cursor, filters):
    """total / org_type / collaborator counts (always present in schema)."""
    conditions, params = build_common_filters(filters)
    query = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.org_type = 'non_profit') AS non_profit_organizations,
            COUNT(*) FILTER (WHERE o.org_type = 'for_profit') AS for_profit_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS NOT TRUE) AS non_collaborator_organizations
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)};
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    return {
        "total_organizations": int(row["total_organizations"] or 0),
        "non_profit_organizations": int(row["non_profit_organizations"] or 0),
        "for_profit_organizations": int(row["for_profit_organizations"] or 0),
        "collaborator_organizations": int(row["collaborator_organizations"] or 0),
        "non_collaborator_organizations": int(row["non_collaborator_organizations"] or 0),
    }


def fetch_contributor_summary(cursor, filters):
    """
    Isolated so a missing `is_contributor` column only zeroes out this
    piece of the summary instead of failing the whole overview dashboard.
    """
    conditions, params = build_common_filters(filters)
    query = f"""
        SELECT
            COUNT(*) FILTER (WHERE o.is_contributor IS TRUE) AS contributor_organizations,
            COUNT(*) FILTER (WHERE o.is_contributor IS NOT TRUE) AS non_contributor_organizations
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)};
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    return {
        "contributor_organizations": int(row["contributor_organizations"] or 0),
        "non_contributor_organizations": int(row["non_contributor_organizations"] or 0),
    }


def fetch_organization_activity_trend(cursor, filters):
    """Registration trend, grouped daily/weekly/monthly/yearly."""
    conditions, params = build_common_filters(filters)
    trunc_unit, fmt = get_group_by_unit(filters.get("group_by"))

    query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{trunc_unit}', o.created_at), '{fmt}') AS period,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)}
        GROUP BY DATE_TRUNC('{trunc_unit}', o.created_at)
        ORDER BY DATE_TRUNC('{trunc_unit}', o.created_at);
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [{"period": row["period"], "count": int(row["count"])} for row in rows]


def fetch_organizations_by_type(cursor, filters):
    conditions, params = build_common_filters(filters)
    query = f"""
        SELECT
            COALESCE(o.org_type::text, 'unknown') AS org_type,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)}
        GROUP BY o.org_type
        ORDER BY count DESC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [{"org_type": row["org_type"], "count": int(row["count"])} for row in rows]


def fetch_organizations_by_size(cursor, filters):
    conditions, params = build_common_filters(filters)
    query = f"""
        SELECT
            COALESCE(o.org_size::text, 'unknown') AS org_size,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)}
        GROUP BY o.org_size
        ORDER BY count DESC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [{"org_size": row["org_size"], "count": int(row["count"])} for row in rows]


def fetch_organizations_by_location(cursor, filters):
    conditions, params = build_common_filters(filters)
    query = f"""
        SELECT
            COALESCE(s.state_name, o.state_id, 'Unknown') AS state,
            COALESCE(o.city_name, 'Unknown') AS city,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        LEFT JOIN {STATE_TABLE} s ON o.state_id = s.state_id
        {where_clause(conditions)}
        GROUP BY COALESCE(s.state_name, o.state_id, 'Unknown'), COALESCE(o.city_name, 'Unknown')
        ORDER BY count DESC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {"state": row["state"], "city": row["city"], "count": int(row["count"])}
        for row in rows
    ]


def fetch_collaborator_distribution(cursor, filters):
    conditions, params = build_common_filters(filters)
    query = f"""
        SELECT
            CASE WHEN o.is_collaborator IS TRUE THEN 'collaborator' ELSE 'non_collaborator' END AS category,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)}
        GROUP BY 1
        ORDER BY 1;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [{"category": row["category"], "count": int(row["count"])} for row in rows]


def fetch_contributor_distribution(cursor, filters):
    """Isolated for the same `is_contributor` reason as fetch_contributor_summary."""
    conditions, params = build_common_filters(filters)
    query = f"""
        SELECT
            CASE WHEN o.is_contributor IS TRUE THEN 'contributor' ELSE 'non_contributor' END AS category,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)}
        GROUP BY 1
        ORDER BY 1;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [{"category": row["category"], "count": int(row["count"])} for row in rows]


def get_organization_overview(cursor, filters):
    response = get_default_overview_response()["organization_overview"]

    try:
        response["summary"].update(fetch_overview_summary(cursor, filters))
    except Exception as error:
        print(f"[overview] summary query failed: {error}")
        safe_rollback(cursor)

    try:
        response["summary"].update(fetch_contributor_summary(cursor, filters))
    except Exception as error:
        print(f"[overview] contributor summary query failed (is_contributor column may not exist yet): {error}")
        safe_rollback(cursor)

    try:
        response["organization_activity_trend"] = fetch_organization_activity_trend(cursor, filters)
    except Exception as error:
        print(f"[overview] activity trend query failed: {error}")
        safe_rollback(cursor)

    try:
        response["organizations_by_type"] = fetch_organizations_by_type(cursor, filters)
    except Exception as error:
        print(f"[overview] organizations_by_type query failed: {error}")
        safe_rollback(cursor)

    try:
        response["organizations_by_size"] = fetch_organizations_by_size(cursor, filters)
    except Exception as error:
        print(f"[overview] organizations_by_size query failed: {error}")
        safe_rollback(cursor)

    try:
        response["organizations_by_location"] = fetch_organizations_by_location(cursor, filters)
    except Exception as error:
        print(f"[overview] organizations_by_location query failed: {error}")
        safe_rollback(cursor)

    try:
        response["collaborator_distribution"] = fetch_collaborator_distribution(cursor, filters)
    except Exception as error:
        print(f"[overview] collaborator_distribution query failed: {error}")
        safe_rollback(cursor)

    try:
        response["contributor_distribution"] = fetch_contributor_distribution(cursor, filters)
    except Exception as error:
        print(f"[overview] contributor_distribution query failed (is_contributor column may not exist yet): {error}")
        safe_rollback(cursor)

    return response


# ---------------------------------------------------------------------------
# Dashboard 2: Organization Performance
# ---------------------------------------------------------------------------

def fetch_performance_summary(cursor, filters):
    conditions, params = build_common_filters(filters)
    query = f"""
        SELECT
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_organizations,
            COUNT(*) FILTER (WHERE o.org_rating IS NULL) AS unrated_organizations,
            COUNT(*) FILTER (WHERE o.org_rating = 5) AS five_star_organizations
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)};
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    return {
        "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0,
        "rated_organizations": int(row["rated_organizations"] or 0),
        "unrated_organizations": int(row["unrated_organizations"] or 0),
        "five_star_organizations": int(row["five_star_organizations"] or 0),
    }


def fetch_rating_distribution(cursor, filters):
    conditions, params = build_common_filters(filters)
    query = f"""
        SELECT
            o.org_rating AS rating,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)}
        GROUP BY o.org_rating
        ORDER BY o.org_rating NULLS LAST;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {"rating": row["rating"], "count": int(row["count"])}
        for row in rows
    ]


def fetch_top_rated_organizations(cursor, filters, limit=TOP_N_DEFAULT):
    conditions, params = build_common_filters(filters)
    conditions = conditions + ["o.org_rating IS NOT NULL"]
    query = f"""
        SELECT
            o.org_id,
            o.org_name,
            o.org_type::text AS org_type,
            o.org_size::text AS org_size,
            o.org_rating,
            o.city_name,
            o.state_id
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)}
        ORDER BY o.org_rating DESC, o.org_name ASC
        LIMIT %s;
    """
    cursor.execute(query, params + [limit])
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def fetch_top_collaborator_organizations(cursor, filters, limit=TOP_N_DEFAULT):
    conditions, params = build_common_filters(filters)
    conditions = conditions + ["o.is_collaborator IS TRUE"]
    query = f"""
        SELECT
            o.org_id,
            o.org_name,
            o.org_type::text AS org_type,
            o.org_size::text AS org_size,
            o.org_rating,
            o.city_name,
            o.state_id
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
        LIMIT %s;
    """
    cursor.execute(query, params + [limit])
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def fetch_top_contributor_organizations(cursor, filters, limit=TOP_N_DEFAULT):
    """Isolated: relies on the not-yet-existing `is_contributor` column."""
    conditions, params = build_common_filters(filters)
    conditions = conditions + ["o.is_contributor IS TRUE"]
    query = f"""
        SELECT
            o.org_id,
            o.org_name,
            o.org_type::text AS org_type,
            o.org_size::text AS org_size,
            o.org_rating,
            o.city_name,
            o.state_id
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
        LIMIT %s;
    """
    cursor.execute(query, params + [limit])
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def fetch_ratings_by_organization_type(cursor, filters):
    conditions, params = build_common_filters(filters)
    query = f"""
        SELECT
            COALESCE(o.org_type::text, 'unknown') AS org_type,
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)}
        GROUP BY o.org_type
        ORDER BY average_rating DESC NULLS LAST;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {
            "org_type": row["org_type"],
            "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0,
            "rated_count": int(row["rated_count"] or 0),
        }
        for row in rows
    ]


def fetch_ratings_by_organization_size(cursor, filters):
    conditions, params = build_common_filters(filters)
    query = f"""
        SELECT
            COALESCE(o.org_size::text, 'unknown') AS org_size,
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)}
        GROUP BY o.org_size
        ORDER BY average_rating DESC NULLS LAST;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {
            "org_size": row["org_size"],
            "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0,
            "rated_count": int(row["rated_count"] or 0),
        }
        for row in rows
    ]


def get_organization_performance(cursor, filters):
    response = get_default_performance_response()["organization_performance"]

    try:
        response["summary"].update(fetch_performance_summary(cursor, filters))
    except Exception as error:
        print(f"[performance] summary query failed: {error}")
        safe_rollback(cursor)

    try:
        response["rating_distribution"] = fetch_rating_distribution(cursor, filters)
    except Exception as error:
        print(f"[performance] rating_distribution query failed: {error}")
        safe_rollback(cursor)

    try:
        response["top_rated_organizations"] = fetch_top_rated_organizations(cursor, filters)
    except Exception as error:
        print(f"[performance] top_rated_organizations query failed: {error}")
        safe_rollback(cursor)

    try:
        response["top_collaborator_organizations"] = fetch_top_collaborator_organizations(cursor, filters)
    except Exception as error:
        print(f"[performance] top_collaborator_organizations query failed: {error}")
        safe_rollback(cursor)

    try:
        response["top_contributor_organizations"] = fetch_top_contributor_organizations(cursor, filters)
    except Exception as error:
        print(f"[performance] top_contributor_organizations query failed (is_contributor column may not exist yet): {error}")
        safe_rollback(cursor)

    try:
        response["ratings_by_organization_type"] = fetch_ratings_by_organization_type(cursor, filters)
    except Exception as error:
        print(f"[performance] ratings_by_organization_type query failed: {error}")
        safe_rollback(cursor)

    try:
        response["ratings_by_organization_size"] = fetch_ratings_by_organization_size(cursor, filters)
    except Exception as error:
        print(f"[performance] ratings_by_organization_size query failed: {error}")
        safe_rollback(cursor)

    return response


# ---------------------------------------------------------------------------
# Lambda handlers
#
# Supports both endpoint designs suggested in issue #228:
#   - two separate endpoints: /analytics/organizations/overview
#                              /analytics/organizations/performance
#     -> overview_lambda_handler / performance_lambda_handler
#   - one endpoint + "dashboard_type": /analytics/organizations
#     -> lambda_handler (dashboard_type: "overview" | "performance" | "both")
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    conn = None
    cursor = None

    filters = parse_event_body(event)
    dashboard_type = (filters.get("dashboard_type") or "overview").lower()

    response_body = {}
    if dashboard_type in ("overview", "both"):
        response_body.update(get_default_overview_response())
    if dashboard_type in ("performance", "both"):
        response_body.update(get_default_performance_response())
    if dashboard_type not in ("overview", "performance", "both"):
        return build_response(400, {
            "error": "Invalid dashboard_type. Expected 'overview', 'performance', or 'both'."
        })

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if dashboard_type in ("overview", "both"):
            response_body["organization_overview"] = get_organization_overview(cursor, filters)

        if dashboard_type in ("performance", "both"):
            response_body["organization_performance"] = get_organization_performance(cursor, filters)

        return build_response(200, response_body)

    except Exception as error:
        print(f"DB connection failed: {error}")
        return build_response(500, response_body)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def overview_lambda_handler(event, context):
    filters = parse_event_body(event)
    filters["dashboard_type"] = "overview"
    return lambda_handler({"body": json.dumps(filters, default=str)}, context)


def performance_lambda_handler(event, context):
    filters = parse_event_body(event)
    filters["dashboard_type"] = "performance"
    return lambda_handler({"body": json.dumps(filters, default=str)}, context)


# ---------------------------------------------------------------------------
# Local testing
#
# Run against a local PostgreSQL instance (no AWS/SSM required):
#
#   export LOCAL_DB_HOST=localhost
#   export LOCAL_DB_NAME=saayam_local
#   export LOCAL_DB_USER=postgres
#   export LOCAL_DB_PASSWORD=postgres
#   export LOCAL_DB_PORT=5432
#   python organization_analytics.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    conn = psycopg2.connect(
        host=os.environ.get("LOCAL_DB_HOST", "localhost"),
        database=os.environ.get("LOCAL_DB_NAME", "saayam_local"),
        user=os.environ.get("LOCAL_DB_USER", "postgres"),
        password=os.environ.get("LOCAL_DB_PASSWORD", "postgres"),
        port=os.environ.get("LOCAL_DB_PORT", "5432"),
    )
    local_cursor = conn.cursor(cursor_factory=RealDictCursor)

    print("=" * 70)
    print("LOCAL TESTING — organization_analytics.py")
    print("=" * 70)

    test_scenarios = [
        ("Overview - ALL time", {"dashboard_type": "overview", "time_filter": "ALL", "group_by": "monthly"}),
        ("Overview - 30D", {"dashboard_type": "overview", "time_filter": "30D", "group_by": "daily"}),
        ("Overview - filtered (non_profit, VA)", {
            "dashboard_type": "overview", "org_type": "non_profit", "state_id": "VA"
        }),
        ("Performance - ALL", {"dashboard_type": "performance", "time_filter": "ALL"}),
        ("Performance - filtered (rating=5)", {"dashboard_type": "performance", "org_rating": 5}),
        ("Both dashboards", {"dashboard_type": "both", "time_filter": "1Y", "group_by": "yearly"}),
    ]

    for label, filters in test_scenarios:
        print(f"\n--- Scenario: {label} ---")
        dashboard_type = filters.get("dashboard_type", "overview")
        result = {}
        if dashboard_type in ("overview", "both"):
            result["organization_overview"] = get_organization_overview(local_cursor, filters)
        if dashboard_type in ("performance", "both"):
            result["organization_performance"] = get_organization_performance(local_cursor, filters)
        print(json.dumps(result, indent=2, default=str))

    cursor_close_ok = True
    try:
        local_cursor.close()
        conn.close()
    except Exception:
        cursor_close_ok = False

    print("\n" + "=" * 70)
    print("LOCAL TESTING COMPLETE" if cursor_close_ok else "LOCAL TESTING COMPLETE (cleanup warning)")
    print("=" * 70)
