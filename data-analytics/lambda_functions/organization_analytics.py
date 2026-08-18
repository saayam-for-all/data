import json
import os

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ORGANIZATIONS = f"{SCHEMA_NAME}.organizations"
STATE = f"{SCHEMA_NAME}.state"
FROM_CLAUSE = f"FROM {ORGANIZATIONS} o LEFT JOIN {STATE} s ON o.state_id = s.state_id"

# org_type/org_size are stored as-is from the real sample data ("Non-Profit", "For-profit",
# "Small"/"Medium"/"Large" -- see organizations_local_setup.sql). These expressions normalize
# them to the clean lowercase vocabulary the ticket's filters/response examples use
# ("non_profit", "for_profit", "small"/"medium"/"large").
ORG_TYPE_EXPR = "LOWER(REPLACE(o.org_type, '-', '_'))"
ORG_SIZE_EXPR = "LOWER(o.org_size)"

VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
VALID_GROUP_BY = {"daily", "weekly", "monthly", "yearly"}


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


def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("HOST"),
        dbname=os.getenv("DATABASE_NAME"),
        user=os.getenv("USERNAME"),
        password=os.getenv("PASSWORD"),
        port=os.getenv("PORT"),
    )


def get_grouping(group_by):
    """Maps the API's group_by value to a Postgres DATE_TRUNC period + TO_CHAR format."""
    mapping = {
        "daily": ("day", "YYYY-MM-DD"),
        "weekly": ("week", 'IYYY-"W"IW'),
        "monthly": ("month", "YYYY-MM"),
        "yearly": ("year", "YYYY"),
    }
    if group_by not in mapping:
        raise ValueError(f"Invalid group_by. Must be one of: {sorted(VALID_GROUP_BY)}")
    return mapping[group_by]


def build_time_filter(time_filter, start_date=None, end_date=None):
    """WHERE-fragment + params filtering organizations.created_at by time_filter."""
    if time_filter == "7D":
        return "o.created_at >= CURRENT_DATE - INTERVAL '7 days'", ()
    if time_filter == "30D":
        return "o.created_at >= CURRENT_DATE - INTERVAL '30 days'", ()
    if time_filter == "1Y":
        return "o.created_at >= CURRENT_DATE - INTERVAL '1 year'", ()
    if time_filter == "ALL":
        return "", ()
    if time_filter == "CUSTOM":
        if start_date and end_date:
            return "o.created_at BETWEEN %s AND %s", (start_date, end_date)
        if start_date:
            return "o.created_at >= %s", (start_date,)
        if end_date:
            return "o.created_at <= %s", (end_date,)
        return "", ()
    raise ValueError(f"Invalid time_filter. Must be one of: {sorted(VALID_TIME_FILTERS)}")


def normalize_org_type(value):
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def build_common_filters(filters):
    """
    WHERE-fragments + params for the shared filter block (region, organization_type).
    "ALL" is the sentinel the frontend sends for "no filter" on either field, matching
    the ticket's sample payloads.
    """
    clauses = []
    params = []

    region = filters.get("region")
    if region and region.upper() != "ALL":
        clauses.append("LOWER(s.state_name) = LOWER(%s)")
        params.append(region)

    organization_type = filters.get("organization_type")
    if organization_type and organization_type.upper() != "ALL":
        clauses.append(f"{ORG_TYPE_EXPR} = %s")
        params.append(normalize_org_type(organization_type))

    return clauses, params


def build_where_clause(time_filter, start_date, end_date, filters):
    time_clause, time_params = build_time_filter(time_filter, start_date, end_date)
    filter_clauses, filter_params = build_common_filters(filters)

    clauses = ([time_clause] if time_clause else []) + filter_clauses
    params = list(time_params) + filter_params

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


def and_condition(where_sql, condition):
    return f"{where_sql} AND {condition}" if where_sql else f"WHERE {condition}"


# ---------------------------------------------------------------------------
# Metric queries
# ---------------------------------------------------------------------------

def get_summary(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS total_collaborators,
            COUNT(*) FILTER (WHERE o.is_contributor IS TRUE) AS total_contributors,
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_org_rating
        {FROM_CLAUSE}
        {where_sql}
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    return {
        "total_organizations": int(row["total_organizations"]),
        "total_collaborators": int(row["total_collaborators"]),
        "total_contributors": int(row["total_contributors"]),
        "average_org_rating": float(row["average_org_rating"]) if row["average_org_rating"] is not None else 0,
    }


def get_growth_trend(cursor, time_filter, start_date, end_date, filters, group_by):
    """
    Cumulative running totals per period (not new-orgs-per-period), matching the
    ticket's own example numbers and the SUM(...) OVER (ORDER BY period) pattern
    already used in volunteer_application_analytics.py's total_volunteers.
    """
    period, date_format = get_grouping(group_by)
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT period,
               SUM(new_count) OVER (ORDER BY period) AS total_organizations,
               SUM(new_collaborators) OVER (ORDER BY period) AS total_collaborators
        FROM (
            SELECT TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
                   COUNT(*) AS new_count,
                   COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS new_collaborators
            {FROM_CLAUSE}
            {where_sql}
            GROUP BY 1
        ) sub
        ORDER BY period
    """
    cursor.execute(query, params)
    return [
        {
            "period": row["period"],
            "total_organizations": int(row["total_organizations"]),
            "total_collaborators": int(row["total_collaborators"]),
        }
        for row in cursor.fetchall()
    ]


def get_organizations_by_location(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)

    state_query = f"""
        SELECT COALESCE(s.state_id, 'UNKNOWN') AS state_id,
               COALESCE(s.state_name, 'Unknown') AS state_name,
               COUNT(*) AS organization_count,
               ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS percentage
        {FROM_CLAUSE}
        {where_sql}
        GROUP BY COALESCE(s.state_id, 'UNKNOWN'), COALESCE(s.state_name, 'Unknown')
        ORDER BY organization_count DESC
    """
    cursor.execute(state_query, params)
    state_rows = cursor.fetchall()

    city_query = f"""
        SELECT COALESCE(s.state_id, 'UNKNOWN') AS state_id,
               o.city_name AS city_name,
               COUNT(*) AS organization_count
        {FROM_CLAUSE}
        {where_sql}
        GROUP BY COALESCE(s.state_id, 'UNKNOWN'), o.city_name
        ORDER BY organization_count DESC
    """
    cursor.execute(city_query, params)
    cities_by_state = {}
    for row in cursor.fetchall():
        cities_by_state.setdefault(row["state_id"], []).append(
            {"city_name": row["city_name"], "organization_count": int(row["organization_count"])}
        )

    return [
        {
            "state_id": row["state_id"],
            "state_name": row["state_name"],
            "organization_count": int(row["organization_count"]),
            "percentage": float(row["percentage"]),
            "cities": cities_by_state.get(row["state_id"], []),
        }
        for row in state_rows
    ]


def get_organizations_by_size(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT {ORG_SIZE_EXPR} AS org_size, COUNT(*) AS organization_count
        {FROM_CLAUSE}
        {where_sql}
        GROUP BY {ORG_SIZE_EXPR}
        ORDER BY organization_count DESC
    """
    cursor.execute(query, params)
    return [
        {"org_size": row["org_size"], "organization_count": int(row["organization_count"])}
        for row in cursor.fetchall()
    ]


def get_collaborator_vs_contributor(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborators,
            COUNT(*) FILTER (WHERE o.is_contributor IS TRUE) AS contributors
        {FROM_CLAUSE}
        {where_sql}
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    total = int(row["total"])
    collaborators = int(row["collaborators"])
    contributors = int(row["contributors"])

    # is_collaborator/is_contributor are independent booleans (an org can be both, or
    # neither), so these percentages are each out of total_organizations and won't
    # necessarily sum to 100 -- that's expected, not a bug.
    def pct(count):
        return round(100.0 * count / total, 1) if total else 0

    return [
        {"type": "collaborator", "organization_count": collaborators, "percentage": pct(collaborators)},
        {"type": "contributor", "organization_count": contributors, "percentage": pct(contributors)},
    ]


def get_rating_distribution(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    # NULL ratings are excluded here (not a crash -- just not part of a 1-5 distribution),
    # per the ticket's acceptance criteria: "Rating Distribution returns ratings from 1 to 5."
    where_sql = and_condition(where_sql, "o.org_rating IS NOT NULL")
    query = f"""
        SELECT o.org_rating AS rating, COUNT(*) AS organization_count
        {FROM_CLAUSE}
        {where_sql}
        GROUP BY o.org_rating
        ORDER BY o.org_rating
    """
    cursor.execute(query, params)
    return [
        {"rating": row["rating"], "organization_count": int(row["organization_count"])}
        for row in cursor.fetchall()
    ]


def get_organization_type_distribution(cursor, time_filter, start_date, end_date, filters, group_by):
    """Cumulative running totals per period, split by org_type (stacked-bar-chart data)."""
    period, date_format = get_grouping(group_by)
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT period,
               SUM(new_for_profit) OVER (ORDER BY period) AS for_profit,
               SUM(new_non_profit) OVER (ORDER BY period) AS non_profit,
               SUM(new_for_profit + new_non_profit) OVER (ORDER BY period) AS total
        FROM (
            SELECT TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
                   COUNT(*) FILTER (WHERE {ORG_TYPE_EXPR} = 'for_profit') AS new_for_profit,
                   COUNT(*) FILTER (WHERE {ORG_TYPE_EXPR} = 'non_profit') AS new_non_profit
            {FROM_CLAUSE}
            {where_sql}
            GROUP BY 1
        ) sub
        ORDER BY period
    """
    cursor.execute(query, params)
    return [
        {
            "period": row["period"],
            "for_profit": int(row["for_profit"]),
            "non_profit": int(row["non_profit"]),
            "total": int(row["total"]),
        }
        for row in cursor.fetchall()
    ]


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def get_default_response():
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


def lambda_handler(event, context):
    conn = None
    cursor = None

    request_body = parse_event_body(event)
    time_filter = request_body.get("time_filter", "30D")
    start_date = request_body.get("start_date")
    end_date = request_body.get("end_date")
    group_by = request_body.get("group_by", "daily")

    filters = {
        "region": request_body.get("region"),
        "organization_type": request_body.get("organization_type"),
    }

    response_body = get_default_response()

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        print("Database connected successfully.")

        # Each metric is wrapped individually so one bad query leaves its slot at the
        # safe default instead of blanking out the whole dashboard response.
        try:
            response_body["summary"] = get_summary(cursor, time_filter, start_date, end_date, filters)
        except Exception as e:
            print(f"summary failed: {e}")

        try:
            response_body["growth_trend"] = get_growth_trend(cursor, time_filter, start_date, end_date, filters, group_by)
        except Exception as e:
            print(f"growth_trend failed: {e}")

        try:
            response_body["organizations_by_location"] = get_organizations_by_location(cursor, time_filter, start_date, end_date, filters)
        except Exception as e:
            print(f"organizations_by_location failed: {e}")

        try:
            response_body["organizations_by_size"] = get_organizations_by_size(cursor, time_filter, start_date, end_date, filters)
        except Exception as e:
            print(f"organizations_by_size failed: {e}")

        try:
            response_body["collaborator_vs_contributor"] = get_collaborator_vs_contributor(cursor, time_filter, start_date, end_date, filters)
        except Exception as e:
            print(f"collaborator_vs_contributor failed: {e}")

        try:
            response_body["rating_distribution"] = get_rating_distribution(cursor, time_filter, start_date, end_date, filters)
        except Exception as e:
            print(f"rating_distribution failed: {e}")

        try:
            response_body["organization_type_distribution"] = get_organization_type_distribution(cursor, time_filter, start_date, end_date, filters, group_by)
        except Exception as e:
            print(f"organization_type_distribution failed: {e}")

        return build_response(200, response_body)

    except Exception as e:
        print("ERROR:", str(e))
        return build_response(500, response_body)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        print("Database connection closed")


if __name__ == "__main__":
    print(json.dumps(lambda_handler({}, None), indent=2))
