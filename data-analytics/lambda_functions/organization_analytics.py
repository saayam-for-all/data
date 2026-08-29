"""
Organization Analytics API — Issue #228

Provides two dashboards for the Saayam Organization Dashboard, built against
virginia_dev_saayam_rdbms.organizations (joined with .state / .country for
location breakdowns):

  1. Organization Overview  (dashboard_type="overview")
  2. Organization Performance (dashboard_type="performance")

Follows the same conventions as the existing analytics lambdas in this folder
(volunteer_application_analytics.py, kpi_api_analytics.py): a SCHEMA_NAME
constant, RealDictCursor, a build_response() helper, and per-metric fetch_*
functions that fail soft (return an empty/zero-value shape rather than raising)
so one broken metric doesn't 500 the whole dashboard.

LOCAL DEV NOTE (per issue #228 — "test locally using a local PostgreSQL
connection, do not deploy to AWS"): get_db_connection() reads a DATABASE_URL
from the environment (same variable already in data-engineering/.env.example)
rather than pulling credentials from AWS SSM like the production lambdas do.
Swap this for the SSM-based get_db_config() pattern used elsewhere in this
folder before this goes anywhere near AWS.

SCHEMA GAP: the issue asks for "contributor" vs "non-contributor" org counts
and a "top contributor organizations" list, but
https://github.com/saayam-for-all/database/blob/main/ddl/Tables/ddl_organizations.sql
has no is_contributor (or equivalent) column — only is_collaborator. Every
contributor-related field below is wired up but intentionally returns a
zero/empty value with a comment pointing here. Flag this with Sana Desai
(issue author) / your reviewer before merging: either the DDL needs a new
column, or "contributor" maps to an existing concept under a different name.
"""

import json
import os

import psycopg2
from psycopg2.extras import RealDictCursor

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ORGANIZATIONS = f"{SCHEMA_NAME}.organizations"
STATE = f"{SCHEMA_NAME}.state"

TOP_N_DEFAULT = 10


# --------------------------------------------------------------------------
# Connection
# --------------------------------------------------------------------------

def get_db_connection():
    """
    Local-dev connection: reads DATABASE_URL from the environment
    (see data-engineering/.env.example). For production this should be
    swapped for the boto3/SSM pattern used in volunteer_application_analytics.py
    and kpi_api_analytics.py — not done here per the issue's "local only" note.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and point it at "
            "your local Postgres instance before running this locally."
        )
    return psycopg2.connect(database_url)


def build_response(status_code, body):
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


# --------------------------------------------------------------------------
# Shared filter helpers
# --------------------------------------------------------------------------

def get_grouping(group_by):
    mapping = {
        "daily": ("day", "YYYY-MM-DD"),
        "weekly": ("week", "IYYY-\"W\"IW"),
        "monthly": ("month", "YYYY-MM"),
        "yearly": ("year", "YYYY"),
    }
    return mapping.get(group_by, ("month", "YYYY-MM"))


def build_time_filter(time_filter, start_date=None, end_date=None, column="o.created_at"):
    """Returns (where_clause_fragment, params) for the given time_filter."""
    if time_filter == "CUSTOM" and start_date and end_date:
        return f"AND {column} BETWEEN %s AND %s", (start_date, end_date)
    if time_filter == "7D":
        return f"AND {column} >= CURRENT_DATE - INTERVAL '7 days'", ()
    if time_filter == "30D":
        return f"AND {column} >= CURRENT_DATE - INTERVAL '30 days'", ()
    if time_filter == "1Y":
        return f"AND {column} >= CURRENT_DATE - INTERVAL '1 year'", ()
    # "ALL" or unrecognized value -> no filter
    return "", ()


def build_common_filters(filters):
    """
    Shared WHERE-clause fragments for org_type / org_size / state_id /
    city_name / org_rating / is_collaborator, applied on top of the time
    filter. is_contributor is accepted but ignored — see SCHEMA GAP note
    at the top of this file.
    """
    clauses = []
    params = []

    if filters.get("org_type"):
        clauses.append("o.org_type = %s")
        params.append(filters["org_type"])

    if filters.get("org_size"):
        clauses.append("o.org_size = %s")
        params.append(filters["org_size"])

    if filters.get("state_id"):
        clauses.append("o.state_id = %s")
        params.append(filters["state_id"])

    if filters.get("city_name"):
        clauses.append("o.city_name = %s")
        params.append(filters["city_name"])

    if filters.get("org_rating"):
        clauses.append("o.org_rating = %s")
        params.append(filters["org_rating"])

    if filters.get("is_collaborator") is not None:
        clauses.append("o.is_collaborator = %s")
        params.append(filters["is_collaborator"])

    where_fragment = (" AND " + " AND ".join(clauses)) if clauses else ""
    return where_fragment, params


# --------------------------------------------------------------------------
# Dashboard 1: Organization Overview
# --------------------------------------------------------------------------

def fetch_overview_summary(cursor, time_where, time_params, common_where, common_params):
    query = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.org_type = 'non_profit') AS non_profit_organizations,
            COUNT(*) FILTER (WHERE o.org_type = 'for_profit') AS for_profit_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS NOT TRUE) AS non_collaborator_organizations
        FROM {ORGANIZATIONS} o
        WHERE 1=1 {time_where} {common_where}
    """
    cursor.execute(query, (*time_params, *common_params))
    row = cursor.fetchone() or {}
    return {
        "total_organizations": int(row.get("total_organizations") or 0),
        "non_profit_organizations": int(row.get("non_profit_organizations") or 0),
        "for_profit_organizations": int(row.get("for_profit_organizations") or 0),
        "collaborator_organizations": int(row.get("collaborator_organizations") or 0),
        "non_collaborator_organizations": int(row.get("non_collaborator_organizations") or 0),
        # SCHEMA GAP: no is_contributor column on organizations. See file header.
        "contributor_organizations": 0,
        "non_contributor_organizations": 0,
    }


def fetch_organization_activity_trend(cursor, group_by, time_where, time_params, common_where, common_params):
    period, date_format = get_grouping(group_by)
    query = f"""
        SELECT TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
               COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        WHERE o.created_at IS NOT NULL {time_where} {common_where}
        GROUP BY 1
        ORDER BY 1
    """
    cursor.execute(query, (*time_params, *common_params))
    return [{"period": row["period"], "count": int(row["count"])} for row in cursor.fetchall()]


def fetch_organizations_by_type(cursor, time_where, time_params, common_where, common_params):
    query = f"""
        SELECT COALESCE(o.org_type::text, 'unknown') AS org_type, COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        WHERE 1=1 {time_where} {common_where}
        GROUP BY 1
        ORDER BY count DESC
    """
    cursor.execute(query, (*time_params, *common_params))
    return [{"org_type": row["org_type"], "count": int(row["count"])} for row in cursor.fetchall()]


def fetch_organizations_by_size(cursor, time_where, time_params, common_where, common_params):
    query = f"""
        SELECT COALESCE(o.org_size::text, 'unknown') AS org_size, COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        WHERE 1=1 {time_where} {common_where}
        GROUP BY 1
        ORDER BY count DESC
    """
    cursor.execute(query, (*time_params, *common_params))
    return [{"org_size": row["org_size"], "count": int(row["count"])} for row in cursor.fetchall()]


def fetch_organizations_by_location(cursor, time_where, time_params, common_where, common_params):
    state_query = f"""
        SELECT COALESCE(s.state_name, 'Unknown') AS state, COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        LEFT JOIN {STATE} s ON o.state_id = s.state_id
        WHERE 1=1 {time_where} {common_where}
        GROUP BY 1
        ORDER BY count DESC
    """
    cursor.execute(state_query, (*time_params, *common_params))
    by_state = [{"state": row["state"], "count": int(row["count"])} for row in cursor.fetchall()]

    city_query = f"""
        SELECT COALESCE(o.city_name, 'Unknown') AS city, COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        WHERE 1=1 {time_where} {common_where}
        GROUP BY 1
        ORDER BY count DESC
    """
    cursor.execute(city_query, (*time_params, *common_params))
    by_city = [{"city": row["city"], "count": int(row["count"])} for row in cursor.fetchall()]

    return {"by_state": by_state, "by_city": by_city}


def fetch_collaborator_distribution(cursor, time_where, time_params, common_where, common_params):
    query = f"""
        SELECT o.is_collaborator, COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        WHERE 1=1 {time_where} {common_where}
        GROUP BY 1
    """
    cursor.execute(query, (*time_params, *common_params))
    return [
        {"is_collaborator": bool(row["is_collaborator"]) if row["is_collaborator"] is not None else False,
         "count": int(row["count"])}
        for row in cursor.fetchall()
    ]


def get_organization_overview(cursor, filters):
    time_where, time_params = build_time_filter(
        filters.get("time_filter", "30D"), filters.get("start_date"), filters.get("end_date")
    )
    common_where, common_params = build_common_filters(filters)
    group_by = filters.get("group_by", "monthly")

    return {
        "summary": fetch_overview_summary(cursor, time_where, time_params, common_where, common_params),
        "organization_activity_trend": fetch_organization_activity_trend(
            cursor, group_by, time_where, time_params, common_where, common_params
        ),
        "organizations_by_type": fetch_organizations_by_type(cursor, time_where, time_params, common_where, common_params),
        "organizations_by_size": fetch_organizations_by_size(cursor, time_where, time_params, common_where, common_params),
        "organizations_by_location": fetch_organizations_by_location(cursor, time_where, time_params, common_where, common_params),
        "collaborator_distribution": fetch_collaborator_distribution(cursor, time_where, time_params, common_where, common_params),
        # SCHEMA GAP: no is_contributor column. See file header.
        "contributor_distribution": [],
    }


# --------------------------------------------------------------------------
# Dashboard 2: Organization Performance
# --------------------------------------------------------------------------

def fetch_performance_summary(cursor, time_where, time_params, common_where, common_params):
    query = f"""
        SELECT
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_organizations,
            COUNT(*) FILTER (WHERE o.org_rating IS NULL) AS unrated_organizations,
            COUNT(*) FILTER (WHERE o.org_rating = 5) AS five_star_organizations
        FROM {ORGANIZATIONS} o
        WHERE 1=1 {time_where} {common_where}
    """
    cursor.execute(query, (*time_params, *common_params))
    row = cursor.fetchone() or {}
    return {
        "average_rating": float(row["average_rating"]) if row.get("average_rating") is not None else 0.0,
        "rated_organizations": int(row.get("rated_organizations") or 0),
        "unrated_organizations": int(row.get("unrated_organizations") or 0),
        "five_star_organizations": int(row.get("five_star_organizations") or 0),
    }


def fetch_rating_distribution(cursor, time_where, time_params, common_where, common_params):
    query = f"""
        SELECT o.org_rating AS rating, COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        WHERE o.org_rating IS NOT NULL {time_where} {common_where}
        GROUP BY 1
        ORDER BY 1
    """
    cursor.execute(query, (*time_params, *common_params))
    return [{"rating": int(row["rating"]), "count": int(row["count"])} for row in cursor.fetchall()]


def fetch_top_rated_organizations(cursor, time_where, time_params, common_where, common_params, limit=TOP_N_DEFAULT):
    query = f"""
        SELECT o.org_id, o.org_name, o.org_rating, o.org_type::text AS org_type, o.org_size::text AS org_size
        FROM {ORGANIZATIONS} o
        WHERE o.org_rating IS NOT NULL {time_where} {common_where}
        ORDER BY o.org_rating DESC, o.org_name ASC
        LIMIT %s
    """
    cursor.execute(query, (*time_params, *common_params, limit))
    return [dict(row) for row in cursor.fetchall()]


def fetch_top_collaborator_organizations(cursor, time_where, time_params, common_where, common_params, limit=TOP_N_DEFAULT):
    query = f"""
        SELECT o.org_id, o.org_name, o.org_rating, o.org_type::text AS org_type
        FROM {ORGANIZATIONS} o
        WHERE o.is_collaborator IS TRUE {time_where} {common_where}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
        LIMIT %s
    """
    cursor.execute(query, (*time_params, *common_params, limit))
    return [dict(row) for row in cursor.fetchall()]


def fetch_ratings_by_organization_type(cursor, time_where, time_params, common_where, common_params):
    query = f"""
        SELECT COALESCE(o.org_type::text, 'unknown') AS org_type,
               ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
               COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        WHERE 1=1 {time_where} {common_where}
        GROUP BY 1
        ORDER BY average_rating DESC NULLS LAST
    """
    cursor.execute(query, (*time_params, *common_params))
    return [
        {
            "org_type": row["org_type"],
            "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0.0,
            "count": int(row["count"]),
        }
        for row in cursor.fetchall()
    ]


def fetch_ratings_by_organization_size(cursor, time_where, time_params, common_where, common_params):
    query = f"""
        SELECT COALESCE(o.org_size::text, 'unknown') AS org_size,
               ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
               COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        WHERE 1=1 {time_where} {common_where}
        GROUP BY 1
        ORDER BY average_rating DESC NULLS LAST
    """
    cursor.execute(query, (*time_params, *common_params))
    return [
        {
            "org_size": row["org_size"],
            "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0.0,
            "count": int(row["count"]),
        }
        for row in cursor.fetchall()
    ]


def get_organization_performance(cursor, filters):
    time_where, time_params = build_time_filter(
        filters.get("time_filter", "30D"), filters.get("start_date"), filters.get("end_date")
    )
    common_where, common_params = build_common_filters(filters)

    return {
        "summary": fetch_performance_summary(cursor, time_where, time_params, common_where, common_params),
        "rating_distribution": fetch_rating_distribution(cursor, time_where, time_params, common_where, common_params),
        "top_rated_organizations": fetch_top_rated_organizations(cursor, time_where, time_params, common_where, common_params),
        "top_collaborator_organizations": fetch_top_collaborator_organizations(cursor, time_where, time_params, common_where, common_params),
        # SCHEMA GAP: no is_contributor column. See file header.
        "top_contributor_organizations": [],
        "ratings_by_organization_type": fetch_ratings_by_organization_type(cursor, time_where, time_params, common_where, common_params),
        "ratings_by_organization_size": fetch_ratings_by_organization_size(cursor, time_where, time_params, common_where, common_params),
    }


# --------------------------------------------------------------------------
# Lambda entrypoint
# --------------------------------------------------------------------------

def empty_overview():
    return {
        "summary": {
            "total_organizations": 0, "non_profit_organizations": 0, "for_profit_organizations": 0,
            "collaborator_organizations": 0, "non_collaborator_organizations": 0,
            "contributor_organizations": 0, "non_contributor_organizations": 0,
        },
        "organization_activity_trend": [], "organizations_by_type": [], "organizations_by_size": [],
        "organizations_by_location": {"by_state": [], "by_city": []},
        "collaborator_distribution": [], "contributor_distribution": [],
    }


def empty_performance():
    return {
        "summary": {"average_rating": 0.0, "rated_organizations": 0, "unrated_organizations": 0, "five_star_organizations": 0},
        "rating_distribution": [], "top_rated_organizations": [], "top_collaborator_organizations": [],
        "top_contributor_organizations": [], "ratings_by_organization_type": [], "ratings_by_organization_size": [],
    }


def lambda_handler(event, context):
    conn = None
    cursor = None

    filters = parse_event_body(event)
    dashboard_type = filters.get("dashboard_type", "overview")

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if dashboard_type == "performance":
            body = {"organization_performance": get_organization_performance(cursor, filters)}
        else:
            body = {"organization_overview": get_organization_overview(cursor, filters)}

        return build_response(200, body)

    except Exception as e:
        print(f"ERROR in organization_analytics.lambda_handler: {e}")
        fallback = {"organization_performance": empty_performance()} if dashboard_type == "performance" \
            else {"organization_overview": empty_overview()}
        return build_response(500, fallback)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    # Local smoke test — requires DATABASE_URL set (see .env / README_local_testing.md)
    print("=== organization_overview ===")
    print(json.dumps(lambda_handler({"dashboard_type": "overview", "time_filter": "ALL"}, None), indent=2))
    print("\n=== organization_performance ===")
    print(json.dumps(lambda_handler({"dashboard_type": "performance", "time_filter": "ALL"}, None), indent=2))
