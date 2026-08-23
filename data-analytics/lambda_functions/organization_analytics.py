import json
import boto3
import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": body
    }


def get_db_connection():
    ssm = boto3.client("ssm", region_name="us-east-1")

    response = ssm.get_parameter(
        Name="/dev/saayam/db/Virginia/Analytics/user",
        WithDecryption=True
    )

    creds = json.loads(response["Parameter"]["Value"])
    db_name = creds["DATABASE NAME"]
    return psycopg2.connect(
        host=creds["HOST"],
        database=db_name,
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require"
    )


def get_grouping(group_by):
    mapping = {
        "daily": ("day", "YYYY-MM-DD"),
        "weekly": ("week", "IYYY-IW"),
        "monthly": ("month", "YYYY-MM"),
        "yearly": ("year", "YYYY"),
    }
    return mapping.get(group_by, ("day", "YYYY-MM-DD"))


def build_date_filter(time_filter, start_date=None, end_date=None):
    """Filters on organizations.created_at (registration date)."""
    if time_filter == "CUSTOM" and start_date and end_date:
        return "o.created_at BETWEEN %s AND %s", (start_date, end_date)
    elif time_filter == "7D":
        return "o.created_at >= CURRENT_DATE - INTERVAL '7 days'", ()
    elif time_filter == "30D":
        return "o.created_at >= CURRENT_DATE - INTERVAL '30 days'", ()
    elif time_filter == "1Y":
        return "o.created_at >= CURRENT_DATE - INTERVAL '1 year'", ()
    else:  # ALL
        return "", ()


def build_filter_clauses(filters):
    """Common optional filters shared by both dashboards. Returns (sql_fragment, params)."""
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
    if filters.get("org_rating") is not None:
        clauses.append("o.org_rating = %s")
        params.append(filters["org_rating"])
    if filters.get("is_collaborator") is not None:
        clauses.append("o.is_collaborator = %s")
        params.append(filters["is_collaborator"])

    return clauses, params


def build_where(time_filter, start_date, end_date, filters):
    date_clause, date_params = build_date_filter(time_filter, start_date, end_date)
    extra_clauses, extra_params = build_filter_clauses(filters)

    all_clauses = ([date_clause] if date_clause else []) + extra_clauses
    all_params = list(date_params) + extra_params

    where_sql = f"WHERE {' AND '.join(all_clauses)}" if all_clauses else ""
    return where_sql, all_params


# ---------------------------------------------------------------------------
# Overview dashboard metrics
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
        "total_organizations": int(row["total_organizations"]),
        "non_profit_organizations": int(row["non_profit_organizations"]),
        "for_profit_organizations": int(row["for_profit_organizations"]),
        "collaborator_organizations": int(row["collaborator_organizations"]),
        "non_collaborator_organizations": int(row["non_collaborator_organizations"]),
        # is_contributor not in DDL yet (per task #228 note) - stubbed pending schema migration
        "contributor_organizations": None,
        "non_contributor_organizations": None,
    }


def fetch_organizations_by_type(cursor, where_sql, params):
    query = f"""
        SELECT o.org_type AS type, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY o.org_type
        ORDER BY o.org_type;
    """
    cursor.execute(query, params)
    return [{"type": r["type"], "count": int(r["count"])} for r in cursor.fetchall()]


def fetch_organizations_by_size(cursor, where_sql, params):
    query = f"""
        SELECT o.org_size AS size, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY o.org_size
        ORDER BY o.org_size;
    """
    cursor.execute(query, params)
    return [{"size": r["size"], "count": int(r["count"])} for r in cursor.fetchall()]


def fetch_organizations_by_location(cursor, where_sql, params):
    query = f"""
        SELECT o.state_id AS state_id, s.state_name AS state_name, o.city_name AS city, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        {where_sql}
        GROUP BY o.state_id, s.state_name, o.city_name
        ORDER BY count DESC;
    """
    cursor.execute(query, params)
    return [
        {"state_id": r["state_id"], "state_name": r["state_name"], "city": r["city"], "count": int(r["count"])}
        for r in cursor.fetchall()
    ]


def fetch_collaborator_distribution(cursor, where_sql, params):
    query = f"""
        SELECT
            CASE WHEN o.is_collaborator IS TRUE THEN 'collaborator' ELSE 'non_collaborator' END AS status,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY 1;
    """
    cursor.execute(query, params)
    return [{"status": r["status"], "count": int(r["count"])} for r in cursor.fetchall()]


def fetch_registration_trend(cursor, where_sql, params, group_by):
    period, date_format = get_grouping(group_by)
    query = f"""
        SELECT TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY 1
        ORDER BY 1;
    """
    cursor.execute(query, params)
    return [{"period": r["period"], "count": int(r["count"])} for r in cursor.fetchall()]


def build_overview_response(cursor, time_filter, start_date, end_date, filters, group_by):
    where_sql, params = build_where(time_filter, start_date, end_date, filters)

    return {
        "summary": fetch_overview_summary(cursor, where_sql, params),
        "organization_activity_trend": fetch_registration_trend(cursor, where_sql, params, group_by),
        "organizations_by_type": fetch_organizations_by_type(cursor, where_sql, params),
        "organizations_by_size": fetch_organizations_by_size(cursor, where_sql, params),
        "organizations_by_location": fetch_organizations_by_location(cursor, where_sql, params),
        "collaborator_distribution": fetch_collaborator_distribution(cursor, where_sql, params),
        # is_contributor not in DDL yet - stubbed pending schema migration
        "contributor_distribution": [],
    }


# ---------------------------------------------------------------------------
# Performance dashboard metrics
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
        "rated_organizations": int(row["rated_organizations"]),
        "unrated_organizations": int(row["unrated_organizations"]),
        "five_star_organizations": int(row["five_star_organizations"]),
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
    return [{"rating": r["rating"], "count": int(r["count"])} for r in cursor.fetchall()]


def fetch_top_rated_organizations(cursor, where_sql, params, limit=10):
    query = f"""
        SELECT o.org_id, o.org_name, o.org_rating, o.org_type, o.org_size
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        {"AND" if where_sql else "WHERE"} o.org_rating IS NOT NULL
        ORDER BY o.org_rating DESC, o.org_name ASC
        LIMIT %s;
    """
    cursor.execute(query, params + [limit])
    return [
        {
            "org_id": r["org_id"], "org_name": r["org_name"], "org_rating": r["org_rating"],
            "org_type": r["org_type"], "org_size": r["org_size"]
        }
        for r in cursor.fetchall()
    ]


def fetch_top_collaborator_organizations(cursor, where_sql, params, limit=10):
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
            "org_id": r["org_id"], "org_name": r["org_name"], "org_rating": r["org_rating"],
            "org_type": r["org_type"], "org_size": r["org_size"]
        }
        for r in cursor.fetchall()
    ]


def fetch_ratings_by_type(cursor, where_sql, params):
    query = f"""
        SELECT o.org_type AS type, ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY o.org_type
        ORDER BY o.org_type;
    """
    cursor.execute(query, params)
    return [
        {"type": r["type"], "average_rating": float(r["average_rating"]) if r["average_rating"] is not None else 0, "count": int(r["count"])}
        for r in cursor.fetchall()
    ]


def fetch_ratings_by_size(cursor, where_sql, params):
    query = f"""
        SELECT o.org_size AS size, ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_sql}
        GROUP BY o.org_size
        ORDER BY o.org_size;
    """
    cursor.execute(query, params)
    return [
        {"size": r["size"], "average_rating": float(r["average_rating"]) if r["average_rating"] is not None else 0, "count": int(r["count"])}
        for r in cursor.fetchall()
    ]


def build_performance_response(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where(time_filter, start_date, end_date, filters)

    return {
        "summary": fetch_performance_summary(cursor, where_sql, params),
        "rating_distribution": fetch_rating_distribution(cursor, where_sql, params),
        "top_rated_organizations": fetch_top_rated_organizations(cursor, where_sql, params),
        "top_collaborator_organizations": fetch_top_collaborator_organizations(cursor, where_sql, params),
        # is_contributor not in DDL yet - stubbed pending schema migration
        "top_contributor_organizations": [],
        "ratings_by_organization_type": fetch_ratings_by_type(cursor, where_sql, params),
        "ratings_by_organization_size": fetch_ratings_by_size(cursor, where_sql, params),
    }


# ---------------------------------------------------------------------------
# Lambda entrypoint
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    conn = None
    cursor = None

    dashboard_type = event.get("dashboard_type", "overview")
    time_filter = event.get("time_filter", "30D")
    start_date = event.get("start_date")
    end_date = event.get("end_date")
    group_by = event.get("group_by", "daily")

    filters = {
        "org_type": event.get("org_type"),
        "org_size": event.get("org_size"),
        "state_id": event.get("state_id"),
        "city_name": event.get("city_name"),
        "org_rating": event.get("org_rating"),
        "is_collaborator": event.get("is_collaborator"),
    }

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if dashboard_type == "performance":
            body = {"organization_performance": build_performance_response(cursor, time_filter, start_date, end_date, filters)}
        else:
            body = {"organization_overview": build_overview_response(cursor, time_filter, start_date, end_date, filters, group_by)}

        return build_response(200, body)

    except Exception as e:
        print(f"organization_analytics failed: {e}")
        return build_response(500, {"error": str(e)})

    finally:
        if cursor: cursor.close()
        if conn: conn.close()


if __name__ == "__main__":
    result_overview = lambda_handler({"dashboard_type": "overview", "time_filter": "ALL"}, None)
    print(json.dumps(result_overview, indent=2, default=str))

    result_performance = lambda_handler({"dashboard_type": "performance", "time_filter": "ALL"}, None)
    print(json.dumps(result_performance, indent=2, default=str))
