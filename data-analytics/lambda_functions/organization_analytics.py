import json
import psycopg2
from psycopg2.extras import RealDictCursor

# Local PostgreSQL connection config for development/testing
LOCAL_DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "saayam_local",
    "user": "postgres",
    "password": ""
}

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
TABLE_ORGANIZATIONS = f"{SCHEMA_NAME}.organizations"
TABLE_STATE = f"{SCHEMA_NAME}.state"


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def get_db_connection():
    return psycopg2.connect(**LOCAL_DB_CONFIG)


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


def build_time_filter(time_filter, start_date=None, end_date=None, column="o.created_at"):
    time_filter = (time_filter or "ALL").upper()
    if time_filter == "7D":
        return f"{column} >= NOW() - INTERVAL '7 days'"
    elif time_filter == "30D":
        return f"{column} >= NOW() - INTERVAL '30 days'"
    elif time_filter == "1Y":
        return f"{column} >= NOW() - INTERVAL '1 year'"
    elif time_filter == "CUSTOM" and start_date and end_date:
        return f"{column} BETWEEN '{start_date}' AND '{end_date}'"
    else:
        return "1=1"


def get_trunc_format(group_by):
    group_by = (group_by or "monthly").lower()
    if group_by == "daily":
        return "day", "YYYY-MM-DD"
    elif group_by == "weekly":
        return "week", "YYYY-MM-DD"
    elif group_by == "yearly":
        return "year", "YYYY"
    else:
        return "month", "YYYY-MM"


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
        },
        "body": json.dumps(body, default=str)
    }


# ─────────────────────────────────────────────
# Default Responses
# ─────────────────────────────────────────────

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
                "non_contributor_organizations": 0
            },
            "organization_activity_trend": [],
            "organizations_by_type": [],
            "organizations_by_size": [],
            "organizations_by_location": [],
            "collaborator_distribution": [],
            "contributor_distribution": []
        }
    }


def get_default_performance_response():
    return {
        "organization_performance": {
            "summary": {
                "average_rating": 0.0,
                "rated_organizations": 0,
                "unrated_organizations": 0,
                "five_star_organizations": 0
            },
            "rating_distribution": [],
            "top_rated_organizations": [],
            "top_collaborator_organizations": [],
            "top_contributor_organizations": [],
            "ratings_by_organization_type": [],
            "ratings_by_organization_size": []
        }
    }


# ─────────────────────────────────────────────
# Dashboard 1: Overview Queries
# ─────────────────────────────────────────────

def get_overview_summary(cursor, time_clause):
    query = f"""
        SELECT
            COUNT(*)                                                       AS total_organizations,
            COUNT(*) FILTER (WHERE LOWER(org_type) = 'non-profit')        AS non_profit_organizations,
            COUNT(*) FILTER (WHERE LOWER(org_type) = 'for-profit')        AS for_profit_organizations,
            COUNT(*) FILTER (WHERE is_collaborator = TRUE)                AS collaborator_organizations,
            COUNT(*) FILTER (WHERE is_collaborator IS DISTINCT FROM TRUE) AS non_collaborator_organizations,
            COUNT(*) FILTER (WHERE is_contributor = TRUE)                 AS contributor_organizations,
            COUNT(*) FILTER (WHERE is_contributor IS DISTINCT FROM TRUE)  AS non_contributor_organizations
        FROM {TABLE_ORGANIZATIONS} o
        WHERE {time_clause};
    """
    cursor.execute(query)
    row = cursor.fetchone()
    if row:
        return {
            "total_organizations": int(row["total_organizations"]),
            "non_profit_organizations": int(row["non_profit_organizations"]),
            "for_profit_organizations": int(row["for_profit_organizations"]),
            "collaborator_organizations": int(row["collaborator_organizations"]),
            "non_collaborator_organizations": int(row["non_collaborator_organizations"]),
            "contributor_organizations": int(row["contributor_organizations"]),
            "non_contributor_organizations": int(row["non_contributor_organizations"])
        }
    return get_default_overview_response()["organization_overview"]["summary"]


def get_organization_activity_trend(cursor, time_clause, group_by):
    trunc, fmt = get_trunc_format(group_by)
    query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{trunc}', o.created_at), '{fmt}') AS period,
            COUNT(*) AS count
        FROM {TABLE_ORGANIZATIONS} o
        WHERE {time_clause}
          AND o.created_at IS NOT NULL
        GROUP BY 1
        ORDER BY 1 ASC;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [{"period": row["period"], "count": int(row["count"])} for row in rows]


def get_organizations_by_type(cursor, time_clause):
    query = f"""
        SELECT
            COALESCE(org_type, 'Unknown') AS org_type,
            COUNT(*) AS count
        FROM {TABLE_ORGANIZATIONS} o
        WHERE {time_clause}
        GROUP BY org_type
        ORDER BY count DESC;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [{"org_type": row["org_type"], "count": int(row["count"])} for row in rows]


def get_organizations_by_size(cursor, time_clause):
    query = f"""
        SELECT
            COALESCE(org_size, 'Unknown') AS org_size,
            COUNT(*) AS count
        FROM {TABLE_ORGANIZATIONS} o
        WHERE {time_clause}
        GROUP BY org_size
        ORDER BY count DESC;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [{"org_size": row["org_size"], "count": int(row["count"])} for row in rows]


def get_organizations_by_location(cursor, time_clause):
    query = f"""
        SELECT
            COALESCE(o.state_id, 'Unknown')   AS state_id,
            COALESCE(s.state_name, 'Unknown') AS state_name,
            COALESCE(o.city_name, 'Unknown')  AS city_name,
            COUNT(*) AS count
        FROM {TABLE_ORGANIZATIONS} o
        LEFT JOIN {TABLE_STATE} s ON o.state_id = s.state_id
        WHERE {time_clause}
        GROUP BY o.state_id, s.state_name, o.city_name
        ORDER BY count DESC;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [
        {
            "state_id": row["state_id"],
            "state_name": row["state_name"],
            "city_name": row["city_name"],
            "count": int(row["count"])
        }
        for row in rows
    ]


def get_collaborator_distribution(cursor, time_clause):
    query = f"""
        SELECT
            CASE WHEN is_collaborator = TRUE THEN 'Collaborator'
                 ELSE 'Non-Collaborator'
            END AS type,
            COUNT(*) AS count
        FROM {TABLE_ORGANIZATIONS} o
        WHERE {time_clause}
        GROUP BY is_collaborator
        ORDER BY count DESC;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [{"type": row["type"], "count": int(row["count"])} for row in rows]


def get_contributor_distribution(cursor, time_clause):
    # NOTE: is_contributor is in the CSV. If not yet in live DB this returns []
    # gracefully via the per-query try/except in lambda_handler.
    query = f"""
        SELECT
            CASE WHEN is_contributor = TRUE THEN 'Contributor'
                 ELSE 'Non-Contributor'
            END AS type,
            COUNT(*) AS count
        FROM {TABLE_ORGANIZATIONS} o
        WHERE {time_clause}
        GROUP BY is_contributor
        ORDER BY count DESC;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [{"type": row["type"], "count": int(row["count"])} for row in rows]


# ─────────────────────────────────────────────
# Dashboard 2: Performance Queries
# ─────────────────────────────────────────────

def get_performance_summary(cursor, time_clause):
    query = f"""
        SELECT
            ROUND(AVG(org_rating)::NUMERIC, 2)                          AS average_rating,
            COUNT(*) FILTER (WHERE org_rating IS NOT NULL)              AS rated_organizations,
            COUNT(*) FILTER (WHERE org_rating IS NULL)                  AS unrated_organizations,
            COUNT(*) FILTER (WHERE org_rating = 5)                      AS five_star_organizations
        FROM {TABLE_ORGANIZATIONS} o
        WHERE {time_clause};
    """
    cursor.execute(query)
    row = cursor.fetchone()
    if row:
        return {
            "average_rating": float(row["average_rating"]) if row["average_rating"] else 0.0,
            "rated_organizations": int(row["rated_organizations"]),
            "unrated_organizations": int(row["unrated_organizations"]),
            "five_star_organizations": int(row["five_star_organizations"])
        }
    return get_default_performance_response()["organization_performance"]["summary"]


def get_rating_distribution(cursor, time_clause):
    query = f"""
        SELECT
            org_rating AS rating,
            COUNT(*) AS count
        FROM {TABLE_ORGANIZATIONS} o
        WHERE org_rating IS NOT NULL
          AND {time_clause}
        GROUP BY org_rating
        ORDER BY org_rating ASC;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [{"rating": int(row["rating"]), "count": int(row["count"])} for row in rows]


def get_top_rated_organizations(cursor, time_clause, limit=10):
    query = f"""
        SELECT
            o.org_id, o.org_name, o.org_type, o.org_size,
            o.org_rating, o.city_name, o.state_id
        FROM {TABLE_ORGANIZATIONS} o
        WHERE o.org_rating IS NOT NULL
          AND {time_clause}
        ORDER BY o.org_rating DESC, o.org_name ASC
        LIMIT {limit};
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "org_type": row["org_type"],
            "org_size": row["org_size"],
            "org_rating": int(row["org_rating"]),
            "city_name": row["city_name"],
            "state_id": row["state_id"]
        }
        for row in rows
    ]


def get_top_collaborator_organizations(cursor, time_clause, limit=10):
    query = f"""
        SELECT
            o.org_id, o.org_name, o.org_type, o.org_size,
            o.org_rating, o.city_name, o.state_id
        FROM {TABLE_ORGANIZATIONS} o
        WHERE o.is_collaborator = TRUE
          AND {time_clause}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
        LIMIT {limit};
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "org_type": row["org_type"],
            "org_size": row["org_size"],
            "org_rating": int(row["org_rating"]) if row["org_rating"] is not None else None,
            "city_name": row["city_name"],
            "state_id": row["state_id"]
        }
        for row in rows
    ]


def get_top_contributor_organizations(cursor, time_clause, limit=10):
    # NOTE: is_contributor is in the CSV. If not yet in live DB this returns []
    # gracefully via the per-query try/except in lambda_handler.
    query = f"""
        SELECT
            o.org_id, o.org_name, o.org_type, o.org_size,
            o.org_rating, o.city_name, o.state_id
        FROM {TABLE_ORGANIZATIONS} o
        WHERE o.is_contributor = TRUE
          AND {time_clause}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
        LIMIT {limit};
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "org_type": row["org_type"],
            "org_size": row["org_size"],
            "org_rating": int(row["org_rating"]) if row["org_rating"] is not None else None,
            "city_name": row["city_name"],
            "state_id": row["state_id"]
        }
        for row in rows
    ]


def get_ratings_by_organization_type(cursor, time_clause):
    query = f"""
        SELECT
            COALESCE(org_type, 'Unknown')                                  AS org_type,
            ROUND(AVG(org_rating)::NUMERIC, 2)                            AS average_rating,
            COUNT(*) FILTER (WHERE org_rating IS NOT NULL)                AS rated_count
        FROM {TABLE_ORGANIZATIONS} o
        WHERE {time_clause}
        GROUP BY org_type
        ORDER BY average_rating DESC NULLS LAST;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [
        {
            "org_type": row["org_type"],
            "average_rating": float(row["average_rating"]) if row["average_rating"] else 0.0,
            "rated_count": int(row["rated_count"])
        }
        for row in rows
    ]


def get_ratings_by_organization_size(cursor, time_clause):
    query = f"""
        SELECT
            COALESCE(org_size, 'Unknown')                                  AS org_size,
            ROUND(AVG(org_rating)::NUMERIC, 2)                            AS average_rating,
            COUNT(*) FILTER (WHERE org_rating IS NOT NULL)                AS rated_count
        FROM {TABLE_ORGANIZATIONS} o
        WHERE {time_clause}
        GROUP BY org_size
        ORDER BY average_rating DESC NULLS LAST;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [
        {
            "org_size": row["org_size"],
            "average_rating": float(row["average_rating"]) if row["average_rating"] else 0.0,
            "rated_count": int(row["rated_count"])
        }
        for row in rows
    ]


# ─────────────────────────────────────────────
# Lambda Handler
# ─────────────────────────────────────────────

def lambda_handler(event, context):
    conn = None
    cursor = None

    try:
        request_body   = parse_event_body(event)
        dashboard_type = request_body.get("dashboard_type", "overview").lower()
        time_filter    = request_body.get("time_filter", "ALL")
        start_date     = request_body.get("start_date", None)
        end_date       = request_body.get("end_date", None)
        group_by       = request_body.get("group_by", "monthly")

        time_clause = build_time_filter(time_filter, start_date, end_date)

        conn   = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        print("Database connected successfully.")

        # ── Overview Dashboard ──────────────────────────
        if dashboard_type == "overview":
            response_body = get_default_overview_response()

            try:
                response_body["organization_overview"]["summary"] = \
                    get_overview_summary(cursor, time_clause)
            except Exception as e:
                print(f"overview summary error: {e}")

            try:
                response_body["organization_overview"]["organization_activity_trend"] = \
                    get_organization_activity_trend(cursor, time_clause, group_by)
            except Exception as e:
                print(f"activity trend error: {e}")

            try:
                response_body["organization_overview"]["organizations_by_type"] = \
                    get_organizations_by_type(cursor, time_clause)
            except Exception as e:
                print(f"by type error: {e}")

            try:
                response_body["organization_overview"]["organizations_by_size"] = \
                    get_organizations_by_size(cursor, time_clause)
            except Exception as e:
                print(f"by size error: {e}")

            try:
                response_body["organization_overview"]["organizations_by_location"] = \
                    get_organizations_by_location(cursor, time_clause)
            except Exception as e:
                print(f"by location error: {e}")

            try:
                response_body["organization_overview"]["collaborator_distribution"] = \
                    get_collaborator_distribution(cursor, time_clause)
            except Exception as e:
                print(f"collaborator distribution error: {e}")

            try:
                response_body["organization_overview"]["contributor_distribution"] = \
                    get_contributor_distribution(cursor, time_clause)
            except Exception as e:
                print(f"contributor distribution error: {e}")

            return build_response(200, response_body)

        # ── Performance Dashboard ───────────────────────
        elif dashboard_type == "performance":
            response_body = get_default_performance_response()

            try:
                response_body["organization_performance"]["summary"] = \
                    get_performance_summary(cursor, time_clause)
            except Exception as e:
                print(f"performance summary error: {e}")

            try:
                response_body["organization_performance"]["rating_distribution"] = \
                    get_rating_distribution(cursor, time_clause)
            except Exception as e:
                print(f"rating distribution error: {e}")

            try:
                response_body["organization_performance"]["top_rated_organizations"] = \
                    get_top_rated_organizations(cursor, time_clause)
            except Exception as e:
                print(f"top rated error: {e}")

            try:
                response_body["organization_performance"]["top_collaborator_organizations"] = \
                    get_top_collaborator_organizations(cursor, time_clause)
            except Exception as e:
                print(f"top collaborator error: {e}")

            try:
                response_body["organization_performance"]["top_contributor_organizations"] = \
                    get_top_contributor_organizations(cursor, time_clause)
            except Exception as e:
                print(f"top contributor error: {e}")

            try:
                response_body["organization_performance"]["ratings_by_organization_type"] = \
                    get_ratings_by_organization_type(cursor, time_clause)
            except Exception as e:
                print(f"ratings by type error: {e}")

            try:
                response_body["organization_performance"]["ratings_by_organization_size"] = \
                    get_ratings_by_organization_size(cursor, time_clause)
            except Exception as e:
                print(f"ratings by size error: {e}")

            return build_response(200, response_body)

        else:
            return build_response(400, {
                "error": f"Invalid dashboard_type '{dashboard_type}'. Use 'overview' or 'performance'."
            })

    except Exception as e:
        print(f"Fatal error: {e}")
        return build_response(500, {"error": str(e)})

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        print("Database connection closed.")


if __name__ == "__main__":
    print("=== OVERVIEW (ALL) ===")
    result = lambda_handler({"dashboard_type": "overview", "time_filter": "ALL", "group_by": "monthly"}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))

    print("\n=== PERFORMANCE (ALL) ===")
    result = lambda_handler({"dashboard_type": "performance", "time_filter": "ALL"}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))