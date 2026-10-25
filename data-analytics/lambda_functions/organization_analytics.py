"""
Organization Analytics API — Issue #228 (rewrite to match finalized dashboard
requirements, see PR #278 / #251 for the reference response shape)

Single combined endpoint (POST /analytics/organizations) returning all
Organization Dashboard sections in one response:

  - summary                          (4 KPI cards)
  - growth_trend                     (cumulative orgs + collaborators by period)
  - organizations_by_location        (state breakdown, with nested cities + %)
  - organizations_by_size            (small / medium / large)
  - collaborator_vs_contributor      (counts + percentages)
  - rating_distribution              (counts for ratings 1-5)
  - organization_type_distribution   (for-profit vs non-profit, per period)

Filters (per finalized spec):
  time_filter: 7D | 30D | 1Y | ALL | CUSTOM   (CUSTOM needs start_date/end_date)
  group_by: daily | weekly | monthly | yearly
  region: "ALL", a state name, or a state_id
  organization_type: "ALL" | "for_profit" | "non_profit"

LOCAL DEV NOTE (per issue #228): get_db_connection() reads DATABASE_URL from
the environment rather than pulling credentials from AWS SSM like the
production lambdas do — matches the issue's "test locally, do not deploy to
AWS" instruction.

SCHEMA COMPATIBILITY: virginia_dev_saayam_rdbms.organizations does not have an
is_contributor column yet (only is_collaborator exists). Rather than hardcode
a zero, has_contributor_column() checks information_schema.columns once per
request and only includes real contributor counts if the column is actually
there — so this keeps working with no code change once the column is added.
"""

import json
import os

import psycopg2
from psycopg2.extras import RealDictCursor

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ORGANIZATIONS = f"{SCHEMA_NAME}.organizations"
STATE = f"{SCHEMA_NAME}.state"


# --------------------------------------------------------------------------
# Connection / response helpers
# --------------------------------------------------------------------------

def get_db_connection():
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
# Schema compatibility check
# --------------------------------------------------------------------------

def has_contributor_column(cursor):
    cursor.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = %s AND table_name = 'organizations' AND column_name = 'is_contributor'
        """,
        (SCHEMA_NAME,),
    )
    return cursor.fetchone() is not None


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


def build_region_filter(region):
    """region can be "ALL"/None (no filter), a state_id (e.g. "CA"), or a
    state name (e.g. "California")."""
    if not region or region == "ALL":
        return "", []
    if len(region) <= 3:
        return "AND s.state_id = %s", [region]
    return "AND s.state_name = %s", [region]


def build_org_type_filter(organization_type):
    if not organization_type or organization_type == "ALL":
        return "", []
    return "AND o.org_type = %s", [organization_type]


def build_filters(filters):
    """Combines region + organization_type into one WHERE fragment/param list,
    applied on top of the time filter across every query below."""
    region_where, region_params = build_region_filter(filters.get("region"))
    type_where, type_params = build_org_type_filter(filters.get("organization_type"))
    return f"{region_where} {type_where}", [*region_params, *type_params]


# --------------------------------------------------------------------------
# Metric fetchers
# --------------------------------------------------------------------------

def fetch_summary(cursor, has_contributor, time_where, time_params, filter_where, filter_params):
    contributor_expr = "COUNT(*) FILTER (WHERE o.is_contributor IS TRUE)" if has_contributor else "0"
    query = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS total_collaborators,
            {contributor_expr} AS total_contributors,
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_org_rating
        FROM {ORGANIZATIONS} o
        LEFT JOIN {STATE} s ON o.state_id = s.state_id
        WHERE 1=1 {time_where} {filter_where}
    """
    cursor.execute(query, (*time_params, *filter_params))
    row = cursor.fetchone() or {}
    return {
        "total_organizations": int(row.get("total_organizations") or 0),
        "total_collaborators": int(row.get("total_collaborators") or 0),
        "total_contributors": int(row.get("total_contributors") or 0),
        "average_org_rating": float(row["average_org_rating"]) if row.get("average_org_rating") is not None else 0.0,
    }


def fetch_growth_trend(cursor, group_by, time_where, time_params, filter_where, filter_params):
    period, date_format = get_grouping(group_by)
    query = f"""
        WITH periods AS (
            SELECT TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
                   COUNT(*) AS new_organizations,
                   COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS new_collaborators
            FROM {ORGANIZATIONS} o
            LEFT JOIN {STATE} s ON o.state_id = s.state_id
            WHERE o.created_at IS NOT NULL {time_where} {filter_where}
            GROUP BY 1
        )
        SELECT period,
               SUM(new_organizations) OVER (ORDER BY period) AS total_organizations,
               SUM(new_collaborators) OVER (ORDER BY period) AS total_collaborators
        FROM periods
        ORDER BY period
    """
    cursor.execute(query, (*time_params, *filter_params))
    return [
        {
            "period": row["period"],
            "total_organizations": int(row["total_organizations"]),
            "total_collaborators": int(row["total_collaborators"]),
        }
        for row in cursor.fetchall()
    ]


def fetch_organizations_by_location(cursor, total_organizations, time_where, time_params, filter_where, filter_params):
    state_query = f"""
        SELECT s.state_id, COALESCE(s.state_name, 'Unknown') AS state_name, COUNT(*) AS organization_count
        FROM {ORGANIZATIONS} o
        LEFT JOIN {STATE} s ON o.state_id = s.state_id
        WHERE 1=1 {time_where} {filter_where}
        GROUP BY s.state_id, s.state_name
        ORDER BY organization_count DESC
    """
    cursor.execute(state_query, (*time_params, *filter_params))
    states = cursor.fetchall()

    city_query = f"""
        SELECT s.state_id, COALESCE(o.city_name, 'Unknown') AS city_name, COUNT(*) AS organization_count
        FROM {ORGANIZATIONS} o
        LEFT JOIN {STATE} s ON o.state_id = s.state_id
        WHERE 1=1 {time_where} {filter_where}
        GROUP BY s.state_id, o.city_name
        ORDER BY s.state_id, organization_count DESC
    """
    cursor.execute(city_query, (*time_params, *filter_params))

    cities_by_state = {}
    for row in cursor.fetchall():
        cities_by_state.setdefault(row["state_id"], []).append(
            {"city_name": row["city_name"], "organization_count": int(row["organization_count"])}
        )

    result = []
    for row in states:
        count = int(row["organization_count"])
        percentage = round((count / total_organizations) * 100, 1) if total_organizations else 0.0
        result.append({
            "state_id": row["state_id"],
            "state_name": row["state_name"],
            "organization_count": count,
            "percentage": percentage,
            "cities": cities_by_state.get(row["state_id"], []),
        })
    return result


def fetch_organizations_by_size(cursor, time_where, time_params, filter_where, filter_params):
    query = f"""
        SELECT COALESCE(o.org_size::text, 'unknown') AS org_size, COUNT(*) AS organization_count
        FROM {ORGANIZATIONS} o
        LEFT JOIN {STATE} s ON o.state_id = s.state_id
        WHERE 1=1 {time_where} {filter_where}
        GROUP BY 1
        ORDER BY organization_count DESC
    """
    cursor.execute(query, (*time_params, *filter_params))
    return [{"org_size": row["org_size"], "organization_count": int(row["organization_count"])} for row in cursor.fetchall()]


def fetch_collaborator_vs_contributor(cursor, has_contributor, total_organizations, time_where, time_params, filter_where, filter_params):
    contributor_expr = "COUNT(*) FILTER (WHERE o.is_contributor IS TRUE)" if has_contributor else "0"
    query = f"""
        SELECT
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_count,
            {contributor_expr} AS contributor_count
        FROM {ORGANIZATIONS} o
        LEFT JOIN {STATE} s ON o.state_id = s.state_id
        WHERE 1=1 {time_where} {filter_where}
    """
    cursor.execute(query, (*time_params, *filter_params))
    row = cursor.fetchone() or {}
    collaborator_count = int(row.get("collaborator_count") or 0)
    contributor_count = int(row.get("contributor_count") or 0)

    def pct(count):
        return round((count / total_organizations) * 100, 1) if total_organizations else 0.0

    return [
        {"type": "collaborator", "organization_count": collaborator_count, "percentage": pct(collaborator_count)},
        {"type": "contributor", "organization_count": contributor_count, "percentage": pct(contributor_count)},
    ]


def fetch_rating_distribution(cursor, time_where, time_params, filter_where, filter_params):
    query = f"""
        SELECT o.org_rating AS rating, COUNT(*) AS organization_count
        FROM {ORGANIZATIONS} o
        LEFT JOIN {STATE} s ON o.state_id = s.state_id
        WHERE o.org_rating IS NOT NULL {time_where} {filter_where}
        GROUP BY 1
        ORDER BY 1
    """
    cursor.execute(query, (*time_params, *filter_params))
    return [{"rating": int(row["rating"]), "organization_count": int(row["organization_count"])} for row in cursor.fetchall()]


def fetch_organization_type_distribution(cursor, group_by, time_where, time_params, filter_where, filter_params):
    period, date_format = get_grouping(group_by)
    query = f"""
        SELECT TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
               COUNT(*) FILTER (WHERE o.org_type = 'for_profit') AS for_profit,
               COUNT(*) FILTER (WHERE o.org_type = 'non_profit') AS non_profit,
               COUNT(*) AS total
        FROM {ORGANIZATIONS} o
        LEFT JOIN {STATE} s ON o.state_id = s.state_id
        WHERE o.created_at IS NOT NULL {time_where} {filter_where}
        GROUP BY 1
        ORDER BY 1
    """
    cursor.execute(query, (*time_params, *filter_params))
    return [
        {
            "period": row["period"],
            "for_profit": int(row["for_profit"]),
            "non_profit": int(row["non_profit"]),
            "total": int(row["total"]),
        }
        for row in cursor.fetchall()
    ]


# --------------------------------------------------------------------------
# Combined dashboard
# --------------------------------------------------------------------------

def get_organization_dashboard(cursor, filters):
    time_where, time_params = build_time_filter(
        filters.get("time_filter", "30D"), filters.get("start_date"), filters.get("end_date")
    )
    filter_where, filter_params = build_filters(filters)
    group_by = filters.get("group_by", "monthly")

    has_contributor = has_contributor_column(cursor)

    summary = fetch_summary(cursor, has_contributor, time_where, time_params, filter_where, filter_params)
    total_organizations = summary["total_organizations"]

    return {
        "summary": summary,
        "growth_trend": fetch_growth_trend(cursor, group_by, time_where, time_params, filter_where, filter_params),
        "organizations_by_location": fetch_organizations_by_location(
            cursor, total_organizations, time_where, time_params, filter_where, filter_params
        ),
        "organizations_by_size": fetch_organizations_by_size(cursor, time_where, time_params, filter_where, filter_params),
        "collaborator_vs_contributor": fetch_collaborator_vs_contributor(
            cursor, has_contributor, total_organizations, time_where, time_params, filter_where, filter_params
        ),
        "rating_distribution": fetch_rating_distribution(cursor, time_where, time_params, filter_where, filter_params),
        "organization_type_distribution": fetch_organization_type_distribution(
            cursor, group_by, time_where, time_params, filter_where, filter_params
        ),
    }


def empty_dashboard():
    return {
        "summary": {
            "total_organizations": 0, "total_collaborators": 0,
            "total_contributors": 0, "average_org_rating": 0.0,
        },
        "growth_trend": [],
        "organizations_by_location": [],
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
        "rating_distribution": [],
        "organization_type_distribution": [],
    }


# --------------------------------------------------------------------------
# Lambda entrypoint
# --------------------------------------------------------------------------

def lambda_handler(event, context):
    conn = None
    cursor = None
    filters = parse_event_body(event)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        body = get_organization_dashboard(cursor, filters)
        return build_response(200, body)

    except Exception as e:
        print(f"ERROR in organization_analytics.lambda_handler: {e}")
        return build_response(500, empty_dashboard())

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    # Local smoke test — requires DATABASE_URL set
    sample_filters = {
        "time_filter": "ALL",
        "start_date": None,
        "end_date": None,
        "group_by": "monthly",
        "region": "ALL",
        "organization_type": "ALL",
    }
    print(json.dumps(lambda_handler(sample_filters, None), indent=2))
