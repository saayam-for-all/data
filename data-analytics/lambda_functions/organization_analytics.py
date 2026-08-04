import json
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
DEFAULT_LIMIT = 10

# NOTE: is_contributor is a planned field per issue #228 but is NOT yet present in the
# organizations table. Contributor metrics are stubbed (null/empty) until that column
# (or a related contributions table) actually exists in the schema.
CONTRIBUTOR_WARNING = (
    "Contributor metrics are not computable yet: is_contributor does not exist on the "
    "organizations table in the current database. These fields are placeholders."
)


# ---------------------------------------------------------------------------
# DB connection - LOCAL POSTGRES ONLY. Per issue instructions, do not use the
# AWS Parameter Store path in this code. Configure via .env (see .env.example):
#   DATABASE_URL=postgresql://user:password@localhost:5432/saayam
# ---------------------------------------------------------------------------
def get_db_connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and fill it in."
        )
    return psycopg2.connect(database_url)


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, default=str)
    }


def get_default_overview_response():
    return {
        "organization_overview": {
            "summary": {
                "total_organizations": 0,
                "non_profit_organizations": 0,
                "for_profit_organizations": 0,
                "collaborator_organizations": 0,
                "non_collaborator_organizations": 0,
                "contributor_organizations": None,
                "non_contributor_organizations": None
            },
            "organization_activity_trend": [],
            "organizations_by_type": [],
            "organizations_by_size": [],
            "organizations_by_location": [],
            "collaborator_distribution": [],
            "contributor_distribution": []
        },
        "warnings": [CONTRIBUTOR_WARNING]
    }


def get_default_performance_response():
    return {
        "organization_performance": {
            "summary": {
                "average_rating": 0,
                "rated_organizations": 0,
                "unrated_organizations": 0,
                "five_star_organizations": 0
            },
            "rating_distribution": [],
            "top_rated_organizations": [],
            "organizations_without_ratings": [],
            "top_collaborator_organizations": [],
            "top_contributor_organizations": [],
            "ratings_by_organization_type": [],
            "ratings_by_organization_size": []
        },
        "warnings": [CONTRIBUTOR_WARNING]
    }


# ---------------------------------------------------------------------------
# Shared filters
# ---------------------------------------------------------------------------
def build_date_filter(time_filter, start_date=None, end_date=None, date_column="o.created_at"):
    time_filter = (time_filter or "ALL").upper()
    sql_date_condition = ""
    sql_params = ()

    if time_filter == "CUSTOM" and start_date and end_date:
        sql_date_condition = f"{date_column} BETWEEN %s AND %s"
        sql_params = (start_date, end_date)
    elif time_filter == "7D":
        sql_date_condition = f"{date_column} >= CURRENT_DATE - INTERVAL '7 days'"
    elif time_filter == "30D":
        sql_date_condition = f"{date_column} >= CURRENT_DATE - INTERVAL '30 days'"
    elif time_filter == "1Y":
        sql_date_condition = f"{date_column} >= CURRENT_DATE - INTERVAL '1 year'"
    # ALL -> no date condition

    return sql_date_condition, sql_params


def build_common_filters(event, alias="o"):
    """Shared filters for both dashboards. is_contributor is accepted in the request
    per the common filter spec, but currently ignored since the column doesn't exist."""
    clauses = []
    params = []

    org_type = event.get("org_type")
    if org_type:
        clauses.append(f"{alias}.org_type = %s")
        params.append(org_type)

    org_size = event.get("org_size")
    if org_size:
        clauses.append(f"{alias}.org_size = %s")
        params.append(org_size)

    state_id = event.get("state_id")
    if state_id:
        clauses.append(f"{alias}.state_id = %s")
        params.append(state_id)

    city_name = event.get("city_name")
    if city_name:
        clauses.append(f"{alias}.city_name = %s")
        params.append(city_name)

    org_rating = event.get("org_rating")
    if org_rating is not None:
        clauses.append(f"{alias}.org_rating = %s")
        params.append(org_rating)

    is_collaborator = event.get("is_collaborator")
    if is_collaborator is not None:
        clauses.append(f"{alias}.is_collaborator = %s")
        params.append(is_collaborator)

    return clauses, params


def build_where_clause(event, date_column="o.created_at"):
    time_filter = event.get("time_filter", "ALL")
    start_date = event.get("start_date")
    end_date = event.get("end_date")

    date_clause, date_params = build_date_filter(time_filter, start_date, end_date, date_column)
    common_clauses, common_params = build_common_filters(event)

    clauses = ([date_clause] if date_clause else []) + common_clauses
    params = list(date_params) + common_params

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


# ---------------------------------------------------------------------------
# Dashboard 1: Overview
# ---------------------------------------------------------------------------
def fetch_overview_summary(cursor, where_sql, params):
    query = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.org_type = 'non_profit') AS non_profit_organizations,
            COUNT(*) FILTER (WHERE o.org_type = 'for_profit') AS for_profit_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS NOT TRUE) AS non_collaborator_organizations
        FROM {SCHEMA_NAME}.organizations o
        {where_sql};
    """
    cursor.execute(query, params)
    row = cursor.fetchone()

    return {
        "total_organizations": int(row["total_organizations"] or 0),
        "non_profit_organizations": int(row["non_profit_organizations"] or 0),
        "for_profit_organizations": int(row["for_profit_organizations"] or 0),
        "collaborator_organizations": int(row["collaborator_organizations"] or 0),
        "non_collaborator_organizations": int(row["non_collaborator_organizations"] or 0),
        "contributor_organizations": None,
        "non_contributor_organizations": None
    }


def fetch_organization_activity_trend(cursor, event, where_sql, params):
    group_by_map = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}
    group_by = group_by_map.get((event.get("group_by") or "daily").lower(), "day")

    query = f"""
        SELECT DATE_TRUNC('{group_by}', o.created_at) AS period, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY period
        ORDER BY period;
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {"period": row["period"].strftime("%Y-%m-%d") if row["period"] else None, "count": int(row["count"])}
        for row in rows
    ]


def fetch_organizations_by_type(cursor, where_sql, params):
    query = f"""
        SELECT o.org_type AS org_type, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY o.org_type
        ORDER BY o.org_type;
    """
    cursor.execute(query, params)
    return [{"org_type": row["org_type"], "count": int(row["count"])} for row in cursor.fetchall()]


def fetch_organizations_by_size(cursor, where_sql, params):
    query = f"""
        SELECT o.org_size AS org_size, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY o.org_size
        ORDER BY o.org_size;
    """
    cursor.execute(query, params)
    return [{"org_size": row["org_size"], "count": int(row["count"])} for row in cursor.fetchall()]


def fetch_organizations_by_location(cursor, where_sql, params):
    # NOTE: organizations.state_id FK references `states`, but the DDL creates the
    # table as `state` (singular). Joining against the table that actually exists.
    query = f"""
        SELECT o.state_id, st.state_name, o.city_name, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state st ON o.state_id = st.state_id
        {where_sql}
        GROUP BY o.state_id, st.state_name, o.city_name
        ORDER BY count DESC;
    """
    cursor.execute(query, params)
    return [
        {
            "state_id": row["state_id"],
            "state_name": row["state_name"],
            "city_name": row["city_name"],
            "count": int(row["count"])
        }
        for row in cursor.fetchall()
    ]


def fetch_collaborator_distribution(cursor, where_sql, params):
    query = f"""
        SELECT o.is_collaborator, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY o.is_collaborator;
    """
    cursor.execute(query, params)
    return [
        {
            "is_collaborator": bool(row["is_collaborator"]) if row["is_collaborator"] is not None else None,
            "count": int(row["count"])
        }
        for row in cursor.fetchall()
    ]


def handle_overview(cursor, event):
    response_body = get_default_overview_response()
    overview = response_body["organization_overview"]
    where_sql, params = build_where_clause(event)

    for key, fn in [
        ("summary", lambda: fetch_overview_summary(cursor, where_sql, params)),
        ("organization_activity_trend", lambda: fetch_organization_activity_trend(cursor, event, where_sql, params)),
        ("organizations_by_type", lambda: fetch_organizations_by_type(cursor, where_sql, params)),
        ("organizations_by_size", lambda: fetch_organizations_by_size(cursor, where_sql, params)),
        ("organizations_by_location", lambda: fetch_organizations_by_location(cursor, where_sql, params)),
        ("collaborator_distribution", lambda: fetch_collaborator_distribution(cursor, where_sql, params)),
    ]:
        try:
            overview[key] = fn()
        except Exception as error:
            print(f"[overview] {key} query failed: {error}")

    return response_body


# ---------------------------------------------------------------------------
# Dashboard 2: Performance
# ---------------------------------------------------------------------------
def fetch_performance_summary(cursor, where_sql, params):
    query = f"""
        SELECT
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_organizations,
            COUNT(*) FILTER (WHERE o.org_rating IS NULL) AS unrated_organizations,
            COUNT(*) FILTER (WHERE o.org_rating = 5) AS five_star_organizations
        FROM {SCHEMA_NAME}.organizations o
        {where_sql};
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    return {
        "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0,
        "rated_organizations": int(row["rated_organizations"] or 0),
        "unrated_organizations": int(row["unrated_organizations"] or 0),
        "five_star_organizations": int(row["five_star_organizations"] or 0)
    }


def fetch_rating_distribution(cursor, where_sql, params):
    query = f"""
        SELECT o.org_rating AS rating, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        {"AND" if where_sql else "WHERE"} o.org_rating IS NOT NULL
        GROUP BY o.org_rating
        ORDER BY o.org_rating;
    """
    cursor.execute(query, params)
    return [{"rating": int(row["rating"]), "count": int(row["count"])} for row in cursor.fetchall()]


def fetch_top_rated_organizations(cursor, where_sql, params, limit):
    query = f"""
        SELECT o.org_id, o.org_name, o.org_rating, o.org_type, o.org_size, o.city_name, o.state_id
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        {"AND" if where_sql else "WHERE"} o.org_rating IS NOT NULL
        ORDER BY o.org_rating DESC, o.org_name ASC
        LIMIT %s;
    """
    cursor.execute(query, params + [limit])
    return [
        {
            "org_id": row["org_id"], "org_name": row["org_name"], "org_rating": int(row["org_rating"]),
            "org_type": row["org_type"], "org_size": row["org_size"],
            "city_name": row["city_name"], "state_id": row["state_id"]
        }
        for row in cursor.fetchall()
    ]


def fetch_organizations_without_ratings(cursor, where_sql, params, limit):
    query = f"""
        SELECT o.org_id, o.org_name, o.org_type, o.org_size, o.city_name, o.state_id
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        {"AND" if where_sql else "WHERE"} o.org_rating IS NULL
        ORDER BY o.created_at DESC
        LIMIT %s;
    """
    cursor.execute(query, params + [limit])
    return [
        {
            "org_id": row["org_id"], "org_name": row["org_name"],
            "org_type": row["org_type"], "org_size": row["org_size"],
            "city_name": row["city_name"], "state_id": row["state_id"]
        }
        for row in cursor.fetchall()
    ]


def fetch_top_collaborator_organizations(cursor, where_sql, params, limit):
    query = f"""
        SELECT o.org_id, o.org_name, o.org_rating, o.org_type, o.org_size
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        {"AND" if where_sql else "WHERE"} o.is_collaborator IS TRUE
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
        LIMIT %s;
    """
    cursor.execute(query, params + [limit])
    return [
        {
            "org_id": row["org_id"], "org_name": row["org_name"], "org_rating": row["org_rating"],
            "org_type": row["org_type"], "org_size": row["org_size"]
        }
        for row in cursor.fetchall()
    ]


def fetch_ratings_by_organization_type(cursor, where_sql, params):
    query = f"""
        SELECT o.org_type, ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY o.org_type
        ORDER BY o.org_type;
    """
    cursor.execute(query, params)
    return [
        {
            "org_type": row["org_type"],
            "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0,
            "count": int(row["count"])
        }
        for row in cursor.fetchall()
    ]


def fetch_ratings_by_organization_size(cursor, where_sql, params):
    query = f"""
        SELECT o.org_size, ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY o.org_size
        ORDER BY o.org_size;
    """
    cursor.execute(query, params)
    return [
        {
            "org_size": row["org_size"],
            "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0,
            "count": int(row["count"])
        }
        for row in cursor.fetchall()
    ]


def handle_performance(cursor, event):
    response_body = get_default_performance_response()
    performance = response_body["organization_performance"]
    where_sql, params = build_where_clause(event)
    limit = int(event.get("limit", DEFAULT_LIMIT))

    for key, fn in [
        ("summary", lambda: fetch_performance_summary(cursor, where_sql, params)),
        ("rating_distribution", lambda: fetch_rating_distribution(cursor, where_sql, params)),
        ("top_rated_organizations", lambda: fetch_top_rated_organizations(cursor, where_sql, params, limit)),
        ("organizations_without_ratings", lambda: fetch_organizations_without_ratings(cursor, where_sql, params, limit)),
        ("top_collaborator_organizations", lambda: fetch_top_collaborator_organizations(cursor, where_sql, params, limit)),
        ("ratings_by_organization_type", lambda: fetch_ratings_by_organization_type(cursor, where_sql, params)),
        ("ratings_by_organization_size", lambda: fetch_ratings_by_organization_size(cursor, where_sql, params)),
    ]:
        try:
            performance[key] = fn()
        except Exception as error:
            print(f"[performance] {key} query failed: {error}")

    return response_body


# ---------------------------------------------------------------------------
# Entry point - single endpoint, routed by dashboard_type
#   POST /analytics/organizations  { "dashboard_type": "overview" | "performance", ... }
# ---------------------------------------------------------------------------
def lambda_handler(event, context):
    conn = None
    cursor = None
    dashboard_type = (event.get("dashboard_type") or "overview").lower()
    default_response = (
        get_default_overview_response() if dashboard_type == "overview"
        else get_default_performance_response()
    )

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if dashboard_type == "performance":
            response_body = handle_performance(cursor, event)
        else:
            response_body = handle_overview(cursor, event)

        return build_response(200, response_body)

    except Exception as error:
        print(f"DB connection failed: {error}")
        return build_response(500, default_response)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    print("Overview:")
    print(json.dumps(lambda_handler({"dashboard_type": "overview"}, None), indent=2))
    print("\nPerformance:")
    print(json.dumps(lambda_handler({"dashboard_type": "performance"}, None), indent=2))
