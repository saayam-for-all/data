"""
organization_analytics.py
==========================

Organization Analytics API for the Saayam for All platform.

Implements TWO dashboards over the `virginia_dev_saayam_rdbms.organizations` table:

    Dashboard 1 -> Organization Overview
    Dashboard 2 -> Organization Performance

This module intentionally mirrors the structure and coding standards used by the
existing analytics lambdas in this repository:

    - data-analytics/lambda_functions/kpi_api_analytics.py
    - data-analytics/lambda_functions/volunteer_application_analytics.py

Design points that match those files:
    * SCHEMA_NAME constant (virginia_dev_saayam_rdbms)
    * get_db_connection() reads credentials from environment variables
      (NO hardcoded credentials anywhere)
    * build_date_filter(time_range, start_date, end_date) supports
      7D / 30D / 1Y / All / Custom
    * build_response(status_code, body) returns an API Gateway style JSON
      response WITH CORS headers
    * parse_event_body(event) tolerates raw dict events and API Gateway
      events whose payload sits inside a JSON string `body`
    * Every individual query is wrapped in its own try/except and falls back
      to an empty / default value so a single failing query never takes the
      whole dashboard down.

SCHEMA NOTE (important):
    The current DDL (ddl_organizations.sql) defines `is_collaborator` but does
    NOT define `is_contributor`. Issue #228, however, asks for contributor
    analytics (contributor_distribution, top_contributor_organizations, ...).
    This module therefore references `o.is_contributor`. Until that column
    exists in the real DB, the contributor functions will fall back to their
    empty/default values thanks to the per-query try/except.
"""

import json
import os
import psycopg2
from psycopg2.extras import RealDictCursor


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHEMA_NAME = "virginia_dev_saayam_rdbms"

# Human readable labels for the org_type / org_size enums.
ORG_TYPE_LABELS = {"non_profit": "Non-Profit", "for_profit": "For-Profit"}
ORG_SIZE_LABELS = {"small": "Small", "medium": "Medium", "large": "Large"}


# ===========================================================================
# SECTION 1 -- COMMON HELPERS
# ===========================================================================
def build_response(status_code, body):
    """Return an API Gateway style JSON response with CORS headers."""
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


def parse_event_body(event):
    """Normalise the incoming lambda event into a plain dict."""
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
    """Create a psycopg2 connection using environment variables.
    No credentials are hardcoded anywhere.

    Set these environment variables before running:
        PGHOST      (default: localhost)
        PGPORT      (default: 5432)
        PGDATABASE  (default: saayam_local)
        PGUSER      (default: postgres)
        PGPASSWORD  (default: postgres)
    """
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "saayam_local"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", "postgres"),
    )


def build_date_filter(time_range, start_date=None, end_date=None):
    """Build a SQL date condition on organizations.created_at.

    Supports: 7D, 30D, 1Y, All, Custom (case-insensitive).

    Returns:
        (clause, params)
        * clause -- a SQL condition WITHOUT the WHERE keyword (may be "")
        * params -- tuple of bound parameters for that clause
    """
    if not time_range:
        time_range = "All"
    tr = str(time_range).strip().upper()

    clause = ""
    params = ()

    if tr == "7D":
        clause = "o.created_at >= CURRENT_DATE - INTERVAL '7 days'"
    elif tr == "30D":
        clause = "o.created_at >= CURRENT_DATE - INTERVAL '30 days'"
    elif tr == "1Y":
        clause = "o.created_at >= CURRENT_DATE - INTERVAL '1 year'"
    elif tr == "CUSTOM":
        if start_date and end_date:
            clause = "o.created_at BETWEEN %s AND %s"
            params = (start_date, end_date)
        elif start_date:
            clause = "o.created_at >= %s"
            params = (start_date,)
        elif end_date:
            clause = "o.created_at <= %s"
            params = (end_date,)
    elif tr == "ALL":
        clause = ""

    return clause, params


def build_org_filters(org_type=None, org_size=None, state_id=None,
                      city_name=None, org_rating=None,
                      is_collaborator=None, is_contributor=None):
    """Build the additional (non-date) organization filters.

    Returns:
        (clause, params)
        * clause -- SQL conditions joined by AND, WITHOUT the WHERE keyword
        * params -- tuple of bound parameters
    All comparisons are parameterised (%s) -- no value is ever interpolated
    directly into SQL.
    """
    conditions = []
    params = []

    if org_type:
        conditions.append("o.org_type = %s")
        params.append(org_type)
    if org_size:
        conditions.append("o.org_size = %s")
        params.append(org_size)
    if state_id:
        conditions.append("o.state_id = %s")
        params.append(state_id)
    if city_name:
        conditions.append("o.city_name = %s")
        params.append(city_name)
    if org_rating is not None:
        conditions.append("o.org_rating = %s")
        params.append(org_rating)
    if is_collaborator is not None:
        conditions.append("o.is_collaborator = %s")
        params.append(bool(is_collaborator))
    if is_contributor is not None:
        conditions.append("o.is_contributor = %s")
        params.append(bool(is_contributor))

    return " AND ".join(conditions), tuple(params)


def combine_filters(time_range, start_date, end_date, **org_filter_kwargs):
    """Merge the date filter and the org filters into a single filters dict."""
    date_clause, date_params = build_date_filter(time_range, start_date, end_date)
    org_clause, org_params = build_org_filters(**org_filter_kwargs)

    clauses = [c for c in (date_clause, org_clause) if c]
    combined_clause = " AND ".join(clauses)
    combined_params = tuple(date_params) + tuple(org_params)

    return {"clause": combined_clause, "params": combined_params}


def build_where(filters, *extra_conditions):
    """Assemble a full WHERE clause from the base filters plus extra conditions."""
    conditions = [c for c in ([filters.get("clause")] + list(extra_conditions)) if c]
    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where_sql, filters.get("params", ())


def get_grouping(group_by):
    """Map a group_by keyword to a (date_trunc period, TO_CHAR format).

    Supports: daily, weekly, monthly, yearly. Defaults to monthly.
    """
    mapping = {
        "daily": ("day", "YYYY-MM-DD"),
        "weekly": ("week", 'IYYY-"W"IW'),
        "monthly": ("month", "YYYY-MM"),
        "yearly": ("year", "YYYY"),
    }
    return mapping.get(str(group_by).strip().lower(), ("month", "YYYY-MM"))


# ===========================================================================
# SECTION 2 -- DASHBOARD 1: ORGANIZATION OVERVIEW
# ===========================================================================
def get_total_organizations(cursor, filters):
    """Total number of organizations matching the current filters."""
    where_sql, params = build_where(filters)
    query = f"""
        SELECT COUNT(*) AS total
        FROM {SCHEMA_NAME}.organizations o
        {where_sql};
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    return int(row["total"]) if row and row["total"] is not None else 0


def get_organizations_by_type(cursor, filters):
    """Distribution of organizations by type (non_profit vs for_profit)."""
    where_sql, params = build_where(filters, "o.org_type IS NOT NULL")
    query = f"""
        SELECT o.org_type AS org_type, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY o.org_type
        ORDER BY count DESC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {
            "org_type": row["org_type"],
            "label": ORG_TYPE_LABELS.get(row["org_type"], row["org_type"]),
            "count": int(row["count"]),
        }
        for row in rows
    ]


def get_organizations_by_size(cursor, filters):
    """Distribution of organizations by size (small / medium / large)."""
    where_sql, params = build_where(filters, "o.org_size IS NOT NULL")
    query = f"""
        SELECT o.org_size AS org_size, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY o.org_size
        ORDER BY count DESC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {
            "org_size": row["org_size"],
            "label": ORG_SIZE_LABELS.get(row["org_size"], row["org_size"]),
            "count": int(row["count"]),
        }
        for row in rows
    ]


def get_collaborator_distribution(cursor, filters):
    """Collaborator vs Non-Collaborator counts."""
    where_sql, params = build_where(filters)
    query = f"""
        SELECT COALESCE(o.is_collaborator, FALSE) AS is_collaborator, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY COALESCE(o.is_collaborator, FALSE)
        ORDER BY is_collaborator DESC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {
            "category": "Collaborator" if row["is_collaborator"] else "Non-Collaborator",
            "is_collaborator": bool(row["is_collaborator"]),
            "count": int(row["count"]),
        }
        for row in rows
    ]


def get_contributor_distribution(cursor, filters):
    """Contributor vs Non-Contributor counts.

    Depends on the is_contributor column (see SCHEMA NOTE at top of file).
    """
    where_sql, params = build_where(filters)
    query = f"""
        SELECT COALESCE(o.is_contributor, FALSE) AS is_contributor, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY COALESCE(o.is_contributor, FALSE)
        ORDER BY is_contributor DESC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {
            "category": "Contributor" if row["is_contributor"] else "Non-Contributor",
            "is_contributor": bool(row["is_contributor"]),
            "count": int(row["count"]),
        }
        for row in rows
    ]


def get_organizations_by_location(cursor, filters):
    """Organization counts grouped by state and city."""
    where_sql, params = build_where(filters)
    query = f"""
        SELECT
            o.state_id AS state_id,
            COALESCE(s.state_name, 'Unknown') AS state_name,
            COALESCE(o.city_name, 'Unknown') AS city_name,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        {where_sql}
        GROUP BY o.state_id, s.state_name, o.city_name
        ORDER BY count DESC, state_name, city_name;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {
            "state_id": row["state_id"],
            "state_name": row["state_name"],
            "city_name": row["city_name"],
            "count": int(row["count"]),
        }
        for row in rows
    ]


def get_organization_registration_trend(cursor, filters, group_by="monthly"):
    """Registration trend of organizations over time.

    group_by supports: daily, weekly, monthly, yearly.
    """
    period, date_string = get_grouping(group_by)
    where_sql, params = build_where(filters, "o.created_at IS NOT NULL")
    query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_string}') AS period,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY 1
        ORDER BY 1 ASC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {"period": row["period"], "count": int(row["count"])}
        for row in rows
    ]


# ===========================================================================
# SECTION 3 -- DASHBOARD 2: ORGANIZATION PERFORMANCE
# ===========================================================================
def get_average_rating(cursor, filters):
    """Average org_rating across rated organizations (rounded to 2 dp)."""
    where_sql, params = build_where(filters, "o.org_rating IS NOT NULL")
    query = f"""
        SELECT ROUND(AVG(o.org_rating)::numeric, 2) AS avg_rating
        FROM {SCHEMA_NAME}.organizations o
        {where_sql};
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    return float(row["avg_rating"]) if row and row["avg_rating"] is not None else 0.0


def get_rating_distribution(cursor, filters):
    """Count of organizations per rating value (1 through 5).

    Always returns all five buckets so the front-end chart has a stable shape.
    """
    where_sql, params = build_where(filters, "o.org_rating IS NOT NULL")
    query = f"""
        SELECT o.org_rating AS rating, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY o.org_rating
        ORDER BY o.org_rating;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    counts = {int(row["rating"]): int(row["count"]) for row in rows}
    return [{"rating": r, "count": counts.get(r, 0)} for r in range(1, 6)]


def get_top_rated_organizations(cursor, filters, limit=10):
    """Top N organizations by rating (ties broken by name)."""
    where_sql, params = build_where(filters, "o.org_rating IS NOT NULL")
    query = f"""
        SELECT o.org_id, o.org_name, o.org_type, o.org_size,
               o.city_name, o.state_id, o.org_rating
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        ORDER BY o.org_rating DESC, o.org_name ASC
        LIMIT {int(limit)};
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "org_type": row["org_type"],
            "org_size": row["org_size"],
            "city_name": row["city_name"],
            "state_id": row["state_id"],
            "org_rating": int(row["org_rating"]),
        }
        for row in rows
    ]


def get_unrated_organizations(cursor, filters):
    """Count of organizations with no rating (org_rating IS NULL)."""
    where_sql, params = build_where(filters, "o.org_rating IS NULL")
    query = f"""
        SELECT COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql};
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    return int(row["count"]) if row and row["count"] is not None else 0


def get_top_collaborator_organizations(cursor, filters, limit=10):
    """Top collaborator organizations (ordered by rating, then name)."""
    where_sql, params = build_where(filters, "o.is_collaborator = TRUE")
    query = f"""
        SELECT o.org_id, o.org_name, o.org_type, o.org_size,
               o.city_name, o.state_id, o.org_rating
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
        LIMIT {int(limit)};
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "org_type": row["org_type"],
            "org_size": row["org_size"],
            "city_name": row["city_name"],
            "state_id": row["state_id"],
            "org_rating": int(row["org_rating"]) if row["org_rating"] is not None else None,
        }
        for row in rows
    ]


def get_top_contributor_organizations(cursor, filters, limit=10):
    """Top contributor organizations (ordered by rating, then name).

    Depends on the is_contributor column (see SCHEMA NOTE at top of file).
    """
    where_sql, params = build_where(filters, "o.is_contributor = TRUE")
    query = f"""
        SELECT o.org_id, o.org_name, o.org_type, o.org_size,
               o.city_name, o.state_id, o.org_rating
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
        LIMIT {int(limit)};
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "org_type": row["org_type"],
            "org_size": row["org_size"],
            "city_name": row["city_name"],
            "state_id": row["state_id"],
            "org_rating": int(row["org_rating"]) if row["org_rating"] is not None else None,
        }
        for row in rows
    ]


def get_ratings_by_organization_type(cursor, filters):
    """Average rating and rated count grouped by organization type."""
    where_sql, params = build_where(filters, "o.org_rating IS NOT NULL",
                                    "o.org_type IS NOT NULL")
    query = f"""
        SELECT o.org_type AS org_type,
               ROUND(AVG(o.org_rating)::numeric, 2) AS avg_rating,
               COUNT(*) AS rated_count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY o.org_type
        ORDER BY avg_rating DESC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {
            "org_type": row["org_type"],
            "label": ORG_TYPE_LABELS.get(row["org_type"], row["org_type"]),
            "average_rating": float(row["avg_rating"]) if row["avg_rating"] is not None else 0.0,
            "rated_count": int(row["rated_count"]),
        }
        for row in rows
    ]


def get_ratings_by_organization_size(cursor, filters):
    """Average rating and rated count grouped by organization size."""
    where_sql, params = build_where(filters, "o.org_rating IS NOT NULL",
                                    "o.org_size IS NOT NULL")
    query = f"""
        SELECT o.org_size AS org_size,
               ROUND(AVG(o.org_rating)::numeric, 2) AS avg_rating,
               COUNT(*) AS rated_count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY o.org_size
        ORDER BY avg_rating DESC;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {
            "org_size": row["org_size"],
            "label": ORG_SIZE_LABELS.get(row["org_size"], row["org_size"]),
            "average_rating": float(row["avg_rating"]) if row["avg_rating"] is not None else 0.0,
            "rated_count": int(row["rated_count"]),
        }
        for row in rows
    ]


# ===========================================================================
# SECTION 4 -- DASHBOARD BUILDERS
# Each individual query is wrapped in try/except and falls back to an empty /
# default value so one failing query never breaks the whole response.
# ===========================================================================
def build_overview_dashboard(cursor, filters, group_by="monthly"):
    """Assemble the Dashboard 1 (Organization Overview) payload."""
    summary = {
        "total_organizations": 0,
        "non_profit_organizations": 0,
        "for_profit_organizations": 0,
        "collaborator_organizations": 0,
        "non_collaborator_organizations": 0,
        "contributor_organizations": 0,
        "non_contributor_organizations": 0,
    }

    try:
        summary["total_organizations"] = get_total_organizations(cursor, filters)
    except Exception as e:
        print(f"[overview] total_organizations failed: {e}")

    organizations_by_type = []
    try:
        organizations_by_type = get_organizations_by_type(cursor, filters)
        for row in organizations_by_type:
            if row["org_type"] == "non_profit":
                summary["non_profit_organizations"] = row["count"]
            elif row["org_type"] == "for_profit":
                summary["for_profit_organizations"] = row["count"]
    except Exception as e:
        print(f"[overview] organizations_by_type failed: {e}")

    organizations_by_size = []
    try:
        organizations_by_size = get_organizations_by_size(cursor, filters)
    except Exception as e:
        print(f"[overview] organizations_by_size failed: {e}")

    collaborator_distribution = []
    try:
        collaborator_distribution = get_collaborator_distribution(cursor, filters)
        for row in collaborator_distribution:
            if row["is_collaborator"]:
                summary["collaborator_organizations"] = row["count"]
            else:
                summary["non_collaborator_organizations"] = row["count"]
    except Exception as e:
        print(f"[overview] collaborator_distribution failed: {e}")

    contributor_distribution = []
    try:
        contributor_distribution = get_contributor_distribution(cursor, filters)
        for row in contributor_distribution:
            if row["is_contributor"]:
                summary["contributor_organizations"] = row["count"]
            else:
                summary["non_contributor_organizations"] = row["count"]
    except Exception as e:
        print(f"[overview] contributor_distribution failed: {e}")

    organizations_by_location = []
    try:
        organizations_by_location = get_organizations_by_location(cursor, filters)
    except Exception as e:
        print(f"[overview] organizations_by_location failed: {e}")

    organization_activity_trend = []
    try:
        organization_activity_trend = get_organization_registration_trend(
            cursor, filters, group_by
        )
    except Exception as e:
        print(f"[overview] organization_activity_trend failed: {e}")

    return {
        "organization_overview": {
            "summary": summary,
            "organization_activity_trend": organization_activity_trend,
            "organizations_by_type": organizations_by_type,
            "organizations_by_size": organizations_by_size,
            "organizations_by_location": organizations_by_location,
            "collaborator_distribution": collaborator_distribution,
            "contributor_distribution": contributor_distribution,
        }
    }


def build_performance_dashboard(cursor, filters):
    """Assemble the Dashboard 2 (Organization Performance) payload."""
    summary = {
        "average_rating": 0,
        "rated_organizations": 0,
        "unrated_organizations": 0,
        "five_star_organizations": 0,
    }

    try:
        summary["average_rating"] = get_average_rating(cursor, filters)
    except Exception as e:
        print(f"[performance] average_rating failed: {e}")

    rating_distribution = []
    try:
        rating_distribution = get_rating_distribution(cursor, filters)
        summary["rated_organizations"] = sum(r["count"] for r in rating_distribution)
        summary["five_star_organizations"] = next(
            (r["count"] for r in rating_distribution if r["rating"] == 5), 0
        )
    except Exception as e:
        print(f"[performance] rating_distribution failed: {e}")

    try:
        summary["unrated_organizations"] = get_unrated_organizations(cursor, filters)
    except Exception as e:
        print(f"[performance] unrated_organizations failed: {e}")

    top_rated_organizations = []
    try:
        top_rated_organizations = get_top_rated_organizations(cursor, filters)
    except Exception as e:
        print(f"[performance] top_rated_organizations failed: {e}")

    top_collaborator_organizations = []
    try:
        top_collaborator_organizations = get_top_collaborator_organizations(cursor, filters)
    except Exception as e:
        print(f"[performance] top_collaborator_organizations failed: {e}")

    top_contributor_organizations = []
    try:
        top_contributor_organizations = get_top_contributor_organizations(cursor, filters)
    except Exception as e:
        print(f"[performance] top_contributor_organizations failed: {e}")

    ratings_by_organization_type = []
    try:
        ratings_by_organization_type = get_ratings_by_organization_type(cursor, filters)
    except Exception as e:
        print(f"[performance] ratings_by_organization_type failed: {e}")

    ratings_by_organization_size = []
    try:
        ratings_by_organization_size = get_ratings_by_organization_size(cursor, filters)
    except Exception as e:
        print(f"[performance] ratings_by_organization_size failed: {e}")

    return {
        "organization_performance": {
            "summary": summary,
            "rating_distribution": rating_distribution,
            "top_rated_organizations": top_rated_organizations,
            "top_collaborator_organizations": top_collaborator_organizations,
            "top_contributor_organizations": top_contributor_organizations,
            "ratings_by_organization_type": ratings_by_organization_type,
            "ratings_by_organization_size": ratings_by_organization_size,
        }
    }


# ===========================================================================
# SECTION 5 -- LAMBDA HANDLER
# ===========================================================================
def resolve_dashboard_type(event, params):
    """Decide which dashboard to serve.

    Supports BOTH endpoint styles:
      * Route based:  POST /analytics/organizations/overview
                      POST /analytics/organizations/performance
      * Single endpoint with a dashboard_type body param.
    Route (if present) wins; otherwise fall back to the body param; default
    is "overview".
    """
    path = ""
    if isinstance(event, dict):
        path = (event.get("path")
                or event.get("rawPath")
                or event.get("resource")
                or "")
        if not path:
            rc = event.get("requestContext") or {}
            http = rc.get("http") or {}
            path = http.get("path", "") or rc.get("resourcePath", "")
    path = (path or "").lower()

    if "performance" in path:
        return "performance"
    if "overview" in path:
        return "overview"

    return str(params.get("dashboard_type", "overview")).strip().lower()


def lambda_handler(event, context):
    """Entry point.

    Reads from the (parsed) event payload:
        dashboard_type   -> "overview" | "performance"  (default "overview")
        time_filter      -> 7D | 30D | 1Y | All | Custom (default "ALL")
        start_date, end_date  (for Custom range)
        org_type, org_size, state_id, city_name, org_rating
        is_collaborator, is_contributor
        group_by         -> daily | weekly | monthly | yearly (default "monthly")
    """
    conn = None
    cursor = None

    params = parse_event_body(event)

    dashboard_type = resolve_dashboard_type(event, params)
    time_filter = params.get("time_filter", "ALL")
    start_date = params.get("start_date")
    end_date = params.get("end_date")
    group_by = params.get("group_by", "monthly")

    filters = combine_filters(
        time_filter,
        start_date,
        end_date,
        org_type=params.get("org_type"),
        org_size=params.get("org_size"),
        state_id=params.get("state_id"),
        city_name=params.get("city_name"),
        org_rating=params.get("org_rating"),
        is_collaborator=params.get("is_collaborator"),
        is_contributor=params.get("is_contributor"),
    )

    if dashboard_type == "performance":
        safe_body = {
            "organization_performance": {
                "summary": {"average_rating": 0, "rated_organizations": 0,
                            "unrated_organizations": 0, "five_star_organizations": 0},
                "rating_distribution": [],
                "top_rated_organizations": [],
                "top_collaborator_organizations": [],
                "top_contributor_organizations": [],
                "ratings_by_organization_type": [],
                "ratings_by_organization_size": [],
            }
        }
    else:
        safe_body = {
            "organization_overview": {
                "summary": {"total_organizations": 0, "non_profit_organizations": 0,
                            "for_profit_organizations": 0, "collaborator_organizations": 0,
                            "non_collaborator_organizations": 0, "contributor_organizations": 0,
                            "non_contributor_organizations": 0},
                "organization_activity_trend": [],
                "organizations_by_type": [],
                "organizations_by_size": [],
                "organizations_by_location": [],
                "collaborator_distribution": [],
                "contributor_distribution": [],
            }
        }

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if dashboard_type == "performance":
            body = build_performance_dashboard(cursor, filters)
        else:
            body = build_overview_dashboard(cursor, filters, group_by)

        return build_response(200, body)

    except Exception as e:
        print(f"DB connection / handler failed: {e}")
        return build_response(500, safe_body)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ===========================================================================
# Local entry point. Uses environment variables for DB connection.
# For full local testing use test_organization_analytics.py directly.
# ===========================================================================
if __name__ == "__main__":
    print(json.dumps(lambda_handler({"dashboard_type": "overview"}, None), indent=2))


# ===========================================================================
# SAMPLE API RESPONSES
# ===========================================================================
#
# REQUEST 1 -- Overview, All time, monthly trend
#   POST /analytics/organizations/overview
#   body: { "time_filter": "All", "group_by": "monthly" }
#
# {
#   "organization_overview": {
#     "summary": {
#       "total_organizations": 40,
#       "non_profit_organizations": 25,
#       "for_profit_organizations": 15,
#       "collaborator_organizations": 24,
#       "non_collaborator_organizations": 16,
#       "contributor_organizations": 16,
#       "non_contributor_organizations": 24
#     },
#     "organization_activity_trend": [
#       {"period": "2025-08", "count": 3},
#       {"period": "2025-09", "count": 4},
#       ...
#     ],
#     "organizations_by_type": [
#       {"org_type": "non_profit", "label": "Non-Profit", "count": 25},
#       {"org_type": "for_profit", "label": "For-Profit", "count": 15}
#     ],
#     "organizations_by_size": [
#       {"org_size": "medium", "label": "Medium", "count": 15},
#       {"org_size": "small",  "label": "Small",  "count": 15},
#       {"org_size": "large",  "label": "Large",  "count": 10}
#     ],
#     "organizations_by_location": [
#       {"state_id": "VA", "state_name": "Virginia", "city_name": "Arlington", "count": 4},
#       ...
#     ],
#     "collaborator_distribution": [
#       {"category": "Collaborator",     "is_collaborator": true,  "count": 24},
#       {"category": "Non-Collaborator", "is_collaborator": false, "count": 16}
#     ],
#     "contributor_distribution": [
#       {"category": "Contributor",     "is_contributor": true,  "count": 16},
#       {"category": "Non-Contributor", "is_contributor": false, "count": 24}
#     ]
#   }
# }
#
# REQUEST 2 -- Performance, All time
#   POST /analytics/organizations/performance
#   body: { "time_filter": "All" }
#
# {
#   "organization_performance": {
#     "summary": {
#       "average_rating": 3.0,
#       "rated_organizations": 35,
#       "unrated_organizations": 5,
#       "five_star_organizations": 7
#     },
#     "rating_distribution": [
#       {"rating": 1, "count": 7},
#       {"rating": 2, "count": 7},
#       {"rating": 3, "count": 7},
#       {"rating": 4, "count": 7},
#       {"rating": 5, "count": 7}
#     ],
#     "top_rated_organizations": [
#       {"org_id": "ORG-001", "org_name": "...", "org_rating": 5, ...}
#     ],
#     "top_collaborator_organizations": [...],
#     "top_contributor_organizations": [...],
#     "ratings_by_organization_type": [
#       {"org_type": "non_profit", "label": "Non-Profit", "average_rating": 3.05, "rated_count": 22},
#       {"org_type": "for_profit", "label": "For-Profit", "average_rating": 2.92, "rated_count": 13}
#     ],
#     "ratings_by_organization_size": [
#       {"org_size": "small",  "label": "Small",  "average_rating": 3.23, "rated_count": 13},
#       {"org_size": "medium", "label": "Medium", "average_rating": 2.92, "rated_count": 13},
#       {"org_size": "large",  "label": "Large",  "average_rating": 2.78, "rated_count": 9}
#     ]
#   }
# }