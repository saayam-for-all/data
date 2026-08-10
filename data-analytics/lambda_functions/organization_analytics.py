import json
import psycopg2
from psycopg2.extras import RealDictCursor
import boto3

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
REAL_TABLE_ORGANIZATIONS = f"{SCHEMA_NAME}.organizations"
REAL_TABLE_STATE = f"{SCHEMA_NAME}.state"


# ─────────────────────────────────────────────
# Utility Functions
# ─────────────────────────────────────────────

def get_db_config(db):
    ssm = boto3.client("ssm", region_name="us-east-1")

    if db == "Virginia":
        parameter_name = "/dev/saayam/db/Virginia/Analytics/user"
    elif db == "Ireland":
        parameter_name = "/dev/saayam/db/Ireland/Analytics/user"
    else:
        raise ValueError("Database must be either Virginia or Ireland")

    response = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
    config = response["Parameter"]["Value"]
    config_list = [line.strip() for line in config.splitlines()]

    host = config_list[1].split()[1][1:-2]
    port = int(config_list[5].split()[1][:-1])
    dbname = config_list[4].split()[2][1:-2]
    user = config_list[2].split()[1][1:-2]
    password = config_list[3].split()[1][1:-2]

    return {
        "host": host,
        "port": port,
        "dbname": dbname,
        "user": user,
        "password": password
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


def build_time_filter(time_filter, start_date, end_date, column="created_at"):
    """Returns a SQL WHERE clause snippet based on time_filter."""
    if time_filter == "7D":
        return f"{column} >= NOW() - INTERVAL '7 days'"
    elif time_filter == "30D":
        return f"{column} >= NOW() - INTERVAL '30 days'"
    elif time_filter == "1Y":
        return f"{column} >= NOW() - INTERVAL '1 year'"
    elif time_filter == "CUSTOM" and start_date and end_date:
        return f"{column} BETWEEN '{start_date}' AND '{end_date}'"
    else:
        return "1=1"  # ALL — no time filter


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

def fetch_overview_summary(cursor, time_clause):
    query = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE org_type = 'non_profit') AS non_profit_organizations,
            COUNT(*) FILTER (WHERE org_type = 'for_profit') AS for_profit_organizations,
            COUNT(*) FILTER (WHERE is_collaborator = TRUE) AS collaborator_organizations,
            COUNT(*) FILTER (WHERE is_collaborator = FALSE OR is_collaborator IS NULL) AS non_collaborator_organizations,
            0 AS contributor_organizations,
            0 AS non_contributor_organizations
        FROM {REAL_TABLE_ORGANIZATIONS}
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


def fetch_organization_activity_trend(cursor, time_clause, group_by="monthly"):
    if group_by == "daily":
        trunc = "day"
        fmt = "YYYY-MM-DD"
    elif group_by == "weekly":
        trunc = "week"
        fmt = "YYYY-MM-DD"
    elif group_by == "yearly":
        trunc = "year"
        fmt = "YYYY"
    else:
        trunc = "month"
        fmt = "YYYY-MM"

    query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{trunc}', created_at), '{fmt}') AS period,
            COUNT(*) AS count
        FROM {REAL_TABLE_ORGANIZATIONS}
        WHERE {time_clause}
          AND created_at IS NOT NULL
        GROUP BY 1
        ORDER BY 1 ASC;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [{"period": row["period"], "count": int(row["count"])} for row in rows]


def fetch_organizations_by_type(cursor, time_clause):
    query = f"""
        SELECT
            COALESCE(org_type::TEXT, 'unknown') AS org_type,
            COUNT(*) AS count
        FROM {REAL_TABLE_ORGANIZATIONS}
        WHERE {time_clause}
        GROUP BY org_type
        ORDER BY count DESC;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [{"org_type": row["org_type"], "count": int(row["count"])} for row in rows]


def fetch_organizations_by_size(cursor, time_clause):
    query = f"""
        SELECT
            COALESCE(org_size::TEXT, 'unknown') AS org_size,
            COUNT(*) AS count
        FROM {REAL_TABLE_ORGANIZATIONS}
        WHERE {time_clause}
        GROUP BY org_size
        ORDER BY count DESC;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [{"org_size": row["org_size"], "count": int(row["count"])} for row in rows]


def fetch_organizations_by_location(cursor, time_clause):
    query = f"""
        SELECT
            COALESCE(o.state_id, 'Unknown') AS state_id,
            COALESCE(s.state_name, 'Unknown') AS state_name,
            COALESCE(o.city_name, 'Unknown') AS city_name,
            COUNT(*) AS count
        FROM {REAL_TABLE_ORGANIZATIONS} o
        LEFT JOIN {REAL_TABLE_STATE} s ON o.state_id = s.state_id
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


def fetch_collaborator_distribution(cursor, time_clause):
    query = f"""
        SELECT
            CASE WHEN is_collaborator = TRUE THEN 'collaborator'
                 ELSE 'non_collaborator'
            END AS type,
            COUNT(*) AS count
        FROM {REAL_TABLE_ORGANIZATIONS}
        WHERE {time_clause}
        GROUP BY is_collaborator
        ORDER BY count DESC;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [{"type": row["type"], "count": int(row["count"])} for row in rows]


def fetch_contributor_distribution(cursor, time_clause):
    # is_contributor field not yet in DB — returning placeholder
    return [
        {"type": "contributor", "count": 0},
        {"type": "non_contributor", "count": 0}
    ]


# ─────────────────────────────────────────────
# Dashboard 2: Performance Queries
# ─────────────────────────────────────────────

def fetch_performance_summary(cursor, time_clause):
    query = f"""
        SELECT
            ROUND(AVG(org_rating)::NUMERIC, 2) AS average_rating,
            COUNT(*) FILTER (WHERE org_rating IS NOT NULL) AS rated_organizations,
            COUNT(*) FILTER (WHERE org_rating IS NULL) AS unrated_organizations,
            COUNT(*) FILTER (WHERE org_rating = 5) AS five_star_organizations
        FROM {REAL_TABLE_ORGANIZATIONS}
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


def fetch_rating_distribution(cursor, time_clause):
    query = f"""
        SELECT
            org_rating AS rating,
            COUNT(*) AS count
        FROM {REAL_TABLE_ORGANIZATIONS}
        WHERE org_rating IS NOT NULL
          AND {time_clause}
        GROUP BY org_rating
        ORDER BY org_rating ASC;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return [{"rating": int(row["rating"]), "count": int(row["count"])} for row in rows]


def fetch_top_rated_organizations(cursor, time_clause, limit=10):
    query = f"""
        SELECT
            org_id,
            org_name,
            org_type,
            org_size,
            org_rating,
            city_name,
            state_id
        FROM {REAL_TABLE_ORGANIZATIONS}
        WHERE org_rating IS NOT NULL
          AND {time_clause}
        ORDER BY org_rating DESC, org_name ASC
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


def fetch_top_collaborator_organizations(cursor, time_clause, limit=10):
    query = f"""
        SELECT
            org_id,
            org_name,
            org_type,
            org_size,
            org_rating,
            city_name,
            state_id
        FROM {REAL_TABLE_ORGANIZATIONS}
        WHERE is_collaborator = TRUE
          AND {time_clause}
        ORDER BY org_rating DESC NULLS LAST, org_name ASC
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
            "org_rating": int(row["org_rating"]) if row["org_rating"] else None,
            "city_name": row["city_name"],
            "state_id": row["state_id"]
        }
        for row in rows
    ]


def fetch_top_contributor_organizations(cursor, time_clause, limit=10):
    # is_contributor field not yet in DB — returning placeholder
    return []


def fetch_ratings_by_organization_type(cursor, time_clause):
    query = f"""
        SELECT
            COALESCE(org_type::TEXT, 'unknown') AS org_type,
            ROUND(AVG(org_rating)::NUMERIC, 2) AS average_rating,
            COUNT(*) FILTER (WHERE org_rating IS NOT NULL) AS rated_count
        FROM {REAL_TABLE_ORGANIZATIONS}
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


def fetch_ratings_by_organization_size(cursor, time_clause):
    query = f"""
        SELECT
            COALESCE(org_size::TEXT, 'unknown') AS org_size,
            ROUND(AVG(org_rating)::NUMERIC, 2) AS average_rating,
            COUNT(*) FILTER (WHERE org_rating IS NOT NULL) AS rated_count
        FROM {REAL_TABLE_ORGANIZATIONS}
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
        request_body = parse_event_body(event)

        dashboard_type = request_body.get("dashboard_type", "overview")
        time_filter = request_body.get("time_filter", "30D")
        start_date = request_body.get("start_date", None)
        end_date = request_body.get("end_date", None)
        group_by = request_body.get("group_by", "monthly")

        time_clause = build_time_filter(time_filter, start_date, end_date)

        VIRGINIA_DB_CONFIG = get_db_config("Virginia")
        conn = psycopg2.connect(**VIRGINIA_DB_CONFIG)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        print("Virginia database connected successfully.")

        # ── Overview Dashboard ──
        if dashboard_type == "overview":
            response_body = get_default_overview_response()

            try:
                response_body["organization_overview"]["summary"] = fetch_overview_summary(cursor, time_clause)
            except Exception as e:
                print(f"Overview summary failed: {e}")

            try:
                response_body["organization_overview"]["organization_activity_trend"] = fetch_organization_activity_trend(cursor, time_clause, group_by)
            except Exception as e:
                print(f"Activity trend failed: {e}")

            try:
                response_body["organization_overview"]["organizations_by_type"] = fetch_organizations_by_type(cursor, time_clause)
            except Exception as e:
                print(f"Org by type failed: {e}")

            try:
                response_body["organization_overview"]["organizations_by_size"] = fetch_organizations_by_size(cursor, time_clause)
            except Exception as e:
                print(f"Org by size failed: {e}")

            try:
                response_body["organization_overview"]["organizations_by_location"] = fetch_organizations_by_location(cursor, time_clause)
            except Exception as e:
                print(f"Org by location failed: {e}")

            try:
                response_body["organization_overview"]["collaborator_distribution"] = fetch_collaborator_distribution(cursor, time_clause)
            except Exception as e:
                print(f"Collaborator distribution failed: {e}")

            try:
                response_body["organization_overview"]["contributor_distribution"] = fetch_contributor_distribution(cursor, time_clause)
            except Exception as e:
                print(f"Contributor distribution failed: {e}")

            return build_response(200, response_body)

        # ── Performance Dashboard ──
        elif dashboard_type == "performance":
            response_body = get_default_performance_response()

            try:
                response_body["organization_performance"]["summary"] = fetch_performance_summary(cursor, time_clause)
            except Exception as e:
                print(f"Performance summary failed: {e}")

            try:
                response_body["organization_performance"]["rating_distribution"] = fetch_rating_distribution(cursor, time_clause)
            except Exception as e:
                print(f"Rating distribution failed: {e}")

            try:
                response_body["organization_performance"]["top_rated_organizations"] = fetch_top_rated_organizations(cursor, time_clause)
            except Exception as e:
                print(f"Top rated orgs failed: {e}")

            try:
                response_body["organization_performance"]["top_collaborator_organizations"] = fetch_top_collaborator_organizations(cursor, time_clause)
            except Exception as e:
                print(f"Top collaborator orgs failed: {e}")

            try:
                response_body["organization_performance"]["top_contributor_organizations"] = fetch_top_contributor_organizations(cursor, time_clause)
            except Exception as e:
                print(f"Top contributor orgs failed: {e}")

            try:
                response_body["organization_performance"]["ratings_by_organization_type"] = fetch_ratings_by_organization_type(cursor, time_clause)
            except Exception as e:
                print(f"Ratings by type failed: {e}")

            try:
                response_body["organization_performance"]["ratings_by_organization_size"] = fetch_ratings_by_organization_size(cursor, time_clause)
            except Exception as e:
                print(f"Ratings by size failed: {e}")

            return build_response(200, response_body)

        else:
            return build_response(400, {"error": f"Invalid dashboard_type '{dashboard_type}'. Use 'overview' or 'performance'."})

    except Exception as e:
        print(f"DB connection failed: {e}")
        return build_response(500, {"error": str(e)})

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        print("Database connection closed.")


if __name__ == "__main__":
    # Test Overview Dashboard
    test_event_overview = {
        "dashboard_type": "overview",
        "time_filter": "ALL",
        "group_by": "monthly"
    }
    print("=== OVERVIEW DASHBOARD ===")
    result = lambda_handler(test_event_overview, None)
    print(json.dumps(json.loads(result["body"]), indent=2))

    # Test Performance Dashboard
    test_event_performance = {
        "dashboard_type": "performance",
        "time_filter": "ALL"
    }
    print("\n=== PERFORMANCE DASHBOARD ===")
    result = lambda_handler(test_event_performance, None)
    print(json.dumps(json.loads(result["body"]), indent=2))
