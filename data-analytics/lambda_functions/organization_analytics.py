"""
Organization Analytics API
Issue: https://github.com/saayam-for-all/data/issues/228

POST /analytics/organizations

Populates all three tabs of the Organization Dashboard:
    Tab 1 - Growth & Location   (growth_trend, organizations_by_location)
    Tab 2 - Size & Contribution (organizations_by_size, collaborator_vs_contributor)
    Tab 3 - Ratings & Type      (rating_distribution, organization_type_distribution)

Follows the same structure/conventions as kpi_api_analytics.py and
volunteer_application_analytics.py:
    - psycopg2 + RealDictCursor
    - build_response() / build_date_filter() helper pattern
    - common filters: time_filter, region, organization_type
    - NULL-safe aggregation
    - local Postgres connection via environment variables

NOTE: Per issue #228, AWS Parameter Store is intentionally NOT used here.
Local/dev credentials are read from environment variables instead.
"""

import json
import os

import psycopg2
from psycopg2.extras import RealDictCursor

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
TABLE_ORGANIZATIONS = f"{SCHEMA_NAME}.organizations"
TABLE_STATE = f"{SCHEMA_NAME}.state"

VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
VALID_GROUP_BY = {"daily", "weekly", "monthly", "yearly"}


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------
def get_default_response():
    """Empty-but-valid response shape, returned on failure so the dashboard
    never breaks on a 500."""
    return {
        "summary": {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": 0,
        },
        "growth_trend": [],
        "organizations_by_location": {"by_state": [], "by_city": []},
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


# ---------------------------------------------------------------------------
# DB connection (local Postgres only - no AWS Parameter Store, per issue)
# ---------------------------------------------------------------------------
def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "saayam_dev"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
        sslmode=os.environ.get("DB_SSLMODE", "prefer"),
    )


def column_exists(cursor, schema, table, column):
    """Guards against is_contributor not yet existing in the dev DB
    (see 'Database Note' in issue #228)."""
    query = """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = %s
        LIMIT 1;
    """
    cursor.execute(query, (schema, table, column))
    return cursor.fetchone() is not None


# ---------------------------------------------------------------------------
# Common filters
# ---------------------------------------------------------------------------
def get_grouping(group_by):
    mapping = {
        "daily": ("day", "YYYY-MM-DD"),
        "weekly": ("week", 'IYYY-"W"IW'),
        "monthly": ("month", "YYYY-MM"),
        "yearly": ("year", "YYYY"),
    }
    if group_by not in mapping:
        raise ValueError(
            "Invalid group_by. Must be one of: 'daily', 'weekly', 'monthly', 'yearly'."
        )
    return mapping[group_by]


def build_date_filter(time_filter, start_date=None, end_date=None):
    """Returns (sql_condition, params) filtering on o.created_at."""
    if time_filter == "CUSTOM":
        if not start_date or not end_date:
            raise ValueError("CUSTOM time_filter requires both start_date and end_date.")
        return "o.created_at::date BETWEEN %s AND %s", (start_date, end_date)
    if time_filter == "7D":
        return "o.created_at >= CURRENT_DATE - INTERVAL '7 days'", ()
    if time_filter == "30D":
        return "o.created_at >= CURRENT_DATE - INTERVAL '30 days'", ()
    if time_filter == "1Y":
        return "o.created_at >= CURRENT_DATE - INTERVAL '1 year'", ()
    if time_filter == "ALL":
        return "", ()
    raise ValueError("Invalid time_filter. Must be one of: 7D, 30D, 1Y, ALL, CUSTOM.")


def build_common_where(time_filter, start_date, end_date, region, organization_type,
                        include_state_join=False):
    """
    Builds the shared WHERE clause (date range + region + organization_type)
    used by every query in this API, so all six charts respect the same
    common filters as the Request/Volunteer/Beneficiary/KPI dashboards.
    """
    conditions = []
    params = []

    date_condition, date_params = build_date_filter(time_filter, start_date, end_date)
    if date_condition:
        conditions.append(date_condition)
        params.extend(date_params)

    if region and region != "ALL":
        if include_state_join:
            conditions.append("UPPER(s.state_name) = UPPER(%s)")
        else:
            conditions.append(
                f"UPPER(o.state_id) IN (SELECT state_id FROM {TABLE_STATE} "
                f"WHERE UPPER(state_name) = UPPER(%s))"
            )
        params.append(region)

    if organization_type and organization_type != "ALL":
        conditions.append("LOWER(REPLACE(o.org_type, '-', '_')) = LOWER(%s)")
        params.append(organization_type)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where_clause, params


# ---------------------------------------------------------------------------
# 1. Summary KPI cards
# ---------------------------------------------------------------------------
def fetch_summary(cursor, has_contributor_col, time_filter, start_date, end_date,
                   region, organization_type):
    where_clause, params = build_common_where(
        time_filter, start_date, end_date, region, organization_type
    )

    contributor_expr = "o.is_contributor" if has_contributor_col else "FALSE"

    query = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS total_collaborators,
            COUNT(*) FILTER (WHERE {contributor_expr} IS TRUE) AS total_contributors,
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_org_rating
        FROM {TABLE_ORGANIZATIONS} o
        {where_clause};
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    if not row:
        return {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": 0,
        }
    return {
        "total_organizations": int(row["total_organizations"] or 0),
        "total_collaborators": int(row["total_collaborators"] or 0),
        "total_contributors": int(row["total_contributors"] or 0),
        "average_org_rating": float(row["average_org_rating"]) if row["average_org_rating"] is not None else 0,
    }


# ---------------------------------------------------------------------------
# 2. Growth trend (Tab 1)
# ---------------------------------------------------------------------------
def fetch_growth_trend(cursor, group_by, time_filter, start_date, end_date,
                        region, organization_type):
    period, date_string = get_grouping(group_by)
    where_clause, params = build_common_where(
        time_filter, start_date, end_date, region, organization_type
    )

    # Aggregate per period first, then run a cumulative window sum (mirrors
    # the rolling-total pattern used in volunteer_application_analytics.py).
    query = f"""
        SELECT period, SUM(org_count) OVER (ORDER BY period) AS total_organizations,
               SUM(collab_count) OVER (ORDER BY period) AS total_collaborators
        FROM (
            SELECT
                TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_string}') AS period,
                COUNT(*) AS org_count,
                COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collab_count
            FROM {TABLE_ORGANIZATIONS} o
            {where_clause}
            GROUP BY 1
        ) sub
        ORDER BY period;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {
            "period": row["period"],
            "total_organizations": int(row["total_organizations"] or 0),
            "total_collaborators": int(row["total_collaborators"] or 0),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# 3. Organizations by location (Tab 1)
# ---------------------------------------------------------------------------
def fetch_organizations_by_location(cursor, time_filter, start_date, end_date,
                                     region, organization_type):
    where_clause, params = build_common_where(
        time_filter, start_date, end_date, region, organization_type,
        include_state_join=True,
    )

    state_query = f"""
        SELECT
            o.state_id,
            COALESCE(s.state_name, 'Unknown') AS state_name,
            COUNT(*) AS organization_count,
            ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 1) AS percentage
        FROM {TABLE_ORGANIZATIONS} o
        LEFT JOIN {TABLE_STATE} s ON o.state_id = s.state_id
        {where_clause}
        GROUP BY o.state_id, s.state_name
        ORDER BY organization_count DESC;
    """
    cursor.execute(state_query, params)
    by_state = [
        {
            "state_id": row["state_id"],
            "state_name": row["state_name"],
            "organization_count": int(row["organization_count"] or 0),
            "percentage": float(row["percentage"]) if row["percentage"] is not None else 0,
        }
        for row in cursor.fetchall()
    ]

    city_query = f"""
        SELECT
            COALESCE(o.city_name, 'Unknown') AS city_name,
            COUNT(*) AS organization_count,
            ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 1) AS percentage
        FROM {TABLE_ORGANIZATIONS} o
        LEFT JOIN {TABLE_STATE} s ON o.state_id = s.state_id
        {where_clause}
        GROUP BY o.city_name
        ORDER BY organization_count DESC;
    """
    cursor.execute(city_query, params)
    by_city = [
        {
            "city_name": row["city_name"],
            "organization_count": int(row["organization_count"] or 0),
            "percentage": float(row["percentage"]) if row["percentage"] is not None else 0,
        }
        for row in cursor.fetchall()
    ]

    return {"by_state": by_state, "by_city": by_city}


# ---------------------------------------------------------------------------
# 4. Organizations by size (Tab 2)
# ---------------------------------------------------------------------------
def fetch_organizations_by_size(cursor, time_filter, start_date, end_date,
                                 region, organization_type):
    where_clause, params = build_common_where(
        time_filter, start_date, end_date, region, organization_type
    )
    query = f"""
        SELECT LOWER(COALESCE(o.org_size, 'unknown')) AS org_size, COUNT(*) AS organization_count
        FROM {TABLE_ORGANIZATIONS} o
        {where_clause}
        GROUP BY 1
        ORDER BY CASE LOWER(COALESCE(o.org_size, 'unknown'))
                    WHEN 'small' THEN 1 WHEN 'medium' THEN 2 WHEN 'large' THEN 3 ELSE 4 END;
    """
    cursor.execute(query, params)
    return [
        {"org_size": row["org_size"], "organization_count": int(row["organization_count"] or 0)}
        for row in cursor.fetchall()
    ]


# ---------------------------------------------------------------------------
# 5. Collaborator vs Contributor (Tab 2)
# ---------------------------------------------------------------------------
def fetch_collaborator_vs_contributor(cursor, has_contributor_col, time_filter, start_date,
                                       end_date, region, organization_type):
    where_clause, params = build_common_where(
        time_filter, start_date, end_date, region, organization_type
    )
    contributor_expr = "o.is_contributor" if has_contributor_col else "FALSE"

    query = f"""
        SELECT
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_count,
            COUNT(*) FILTER (WHERE {contributor_expr} IS TRUE) AS contributor_count
        FROM {TABLE_ORGANIZATIONS} o
        {where_clause};
    """
    cursor.execute(query, params)
    row = cursor.fetchone() or {}
    collaborator_count = int(row.get("collaborator_count") or 0)
    contributor_count = int(row.get("contributor_count") or 0)
    total = collaborator_count + contributor_count

    def pct(count):
        return round(100.0 * count / total, 1) if total else 0

    return [
        {"type": "collaborator", "organization_count": collaborator_count, "percentage": pct(collaborator_count)},
        {"type": "contributor", "organization_count": contributor_count, "percentage": pct(contributor_count)},
    ]


# ---------------------------------------------------------------------------
# 6. Rating distribution (Tab 3) - NULLs handled safely
# ---------------------------------------------------------------------------
def fetch_rating_distribution(cursor, time_filter, start_date, end_date,
                               region, organization_type):
    where_clause, params = build_common_where(
        time_filter, start_date, end_date, region, organization_type
    )
    # Exclude NULL ratings from the 1-5 buckets instead of letting them break the query.
    null_guard = "o.org_rating IS NOT NULL"
    where_clause = f"{where_clause} AND {null_guard}" if where_clause else f"WHERE {null_guard}"

    query = f"""
        SELECT o.org_rating AS rating, COUNT(*) AS organization_count
        FROM {TABLE_ORGANIZATIONS} o
        {where_clause}
        GROUP BY o.org_rating
        ORDER BY o.org_rating;
    """
    cursor.execute(query, params)
    rows = {int(row["rating"]): int(row["organization_count"]) for row in cursor.fetchall()}
    # Always return all 5 buckets, even if a rating has zero organizations.
    return [{"rating": r, "organization_count": rows.get(r, 0)} for r in range(1, 6)]


# ---------------------------------------------------------------------------
# 7. For-Profit vs Non-Profit trend (Tab 3)
# ---------------------------------------------------------------------------
def fetch_organization_type_distribution(cursor, group_by, time_filter, start_date, end_date,
                                          region, organization_type):
    period, date_string = get_grouping(group_by)
    where_clause, params = build_common_where(
        time_filter, start_date, end_date, region, organization_type
    )
    query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_string}') AS period,
            COUNT(*) FILTER (WHERE LOWER(REPLACE(o.org_type, '-', '_')) = 'for_profit') AS for_profit,
            COUNT(*) FILTER (WHERE LOWER(REPLACE(o.org_type, '-', '_')) = 'non_profit') AS non_profit,
            COUNT(*) AS total
        FROM {TABLE_ORGANIZATIONS} o
        {where_clause}
        GROUP BY 1
        ORDER BY 1;
    """
    cursor.execute(query, params)
    return [
        {
            "period": row["period"],
            "for_profit": int(row["for_profit"] or 0),
            "non_profit": int(row["non_profit"] or 0),
            "total": int(row["total"] or 0),
        }
        for row in cursor.fetchall()
    ]


# ---------------------------------------------------------------------------
# Lambda entrypoint
# ---------------------------------------------------------------------------
def lambda_handler(event, context):
    conn = None
    cursor = None
    response_body = get_default_response()

    request_body = parse_event_body(event)

    time_filter = request_body.get("time_filter", "ALL")
    start_date = request_body.get("start_date")
    end_date = request_body.get("end_date")
    group_by = request_body.get("group_by", "monthly")
    region = request_body.get("region", "ALL")
    organization_type = request_body.get("organization_type", "ALL")

    # --- Validate filters up front (mirrors "Test invalid filters" requirement) ---
    if time_filter not in VALID_TIME_FILTERS:
        return build_response(400, {"error": f"Invalid time_filter: {time_filter}"})
    if time_filter == "CUSTOM" and (not start_date or not end_date):
        return build_response(400, {"error": "CUSTOM time_filter requires start_date and end_date."})
    if group_by not in VALID_GROUP_BY:
        return build_response(400, {"error": f"Invalid group_by: {group_by}"})

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        has_contributor_col = column_exists(
            cursor, SCHEMA_NAME, "organizations", "is_contributor"
        )

        response_body["summary"] = fetch_summary(
            cursor, has_contributor_col, time_filter, start_date, end_date, region, organization_type
        )
        response_body["growth_trend"] = fetch_growth_trend(
            cursor, group_by, time_filter, start_date, end_date, region, organization_type
        )
        response_body["organizations_by_location"] = fetch_organizations_by_location(
            cursor, time_filter, start_date, end_date, region, organization_type
        )
        response_body["organizations_by_size"] = fetch_organizations_by_size(
            cursor, time_filter, start_date, end_date, region, organization_type
        )
        response_body["collaborator_vs_contributor"] = fetch_collaborator_vs_contributor(
            cursor, has_contributor_col, time_filter, start_date, end_date, region, organization_type
        )
        response_body["rating_distribution"] = fetch_rating_distribution(
            cursor, time_filter, start_date, end_date, region, organization_type
        )
        response_body["organization_type_distribution"] = fetch_organization_type_distribution(
            cursor, group_by, time_filter, start_date, end_date, region, organization_type
        )

        return build_response(200, response_body)

    except ValueError as e:
        return build_response(400, {"error": str(e)})
    except Exception as e:
        print("ERROR:", str(e))
        return build_response(500, response_body)
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    test_event = {
        "time_filter": "30D",
        "start_date": None,
        "end_date": None,
        "group_by": "daily",
        "region": "ALL",
        "organization_type": "ALL",
    }
    print(json.dumps(lambda_handler(test_event, None), indent=2))
