import json

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ORGANIZATIONS = f"{SCHEMA_NAME}.organizations"
STATE = f"{SCHEMA_NAME}.state"

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
    ssm = boto3.client("ssm", region_name="us-east-1")

    response = ssm.get_parameter(
        Name="/dev/saayam/db/Virginia/Analytics/user",
        WithDecryption=True,
    )

    creds = json.loads(response["Parameter"]["Value"])
    return psycopg2.connect(
        host=creds["HOST"],
        database=creds["DATABASE NAME"],
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require",
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


def build_common_filters(filters):
    """
    WHERE-fragments + params for the shared filter block (org_type, org_size, state_id,
    city_name, org_rating, is_collaborator, is_contributor), reused by every metric
    query below.
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
        clauses.append("o.city_name ILIKE %s")
        params.append(filters["city_name"])

    # "is not None" (not a truthy check) because False/0 are valid filter values,
    # not "no filter" -- a truthy check would silently drop is_collaborator: false.
    if filters.get("org_rating") is not None:
        clauses.append("o.org_rating = %s")
        params.append(filters["org_rating"])

    if filters.get("is_collaborator") is not None:
        clauses.append("o.is_collaborator = %s")
        params.append(filters["is_collaborator"])

    if filters.get("is_contributor") is not None:
        clauses.append("o.is_contributor = %s")
        params.append(filters["is_contributor"])

    return clauses, params


def build_where_clause(time_filter, start_date, end_date, filters):
    time_clause, time_params = build_time_filter(time_filter, start_date, end_date)
    filter_clauses, filter_params = build_common_filters(filters)

    clauses = ([time_clause] if time_clause else []) + filter_clauses
    params = list(time_params) + filter_params

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


# ---------------------------------------------------------------------------
# Overview dashboard
# ---------------------------------------------------------------------------

def get_summary(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.org_type = 'non_profit') AS non_profit_organizations,
            COUNT(*) FILTER (WHERE o.org_type = 'for_profit') AS for_profit_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS NOT TRUE) AS non_collaborator_organizations,
            COUNT(*) FILTER (WHERE o.is_contributor IS TRUE) AS contributor_organizations,
            COUNT(*) FILTER (WHERE o.is_contributor IS NOT TRUE) AS non_contributor_organizations
        FROM {ORGANIZATIONS} o
        {where_sql}
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    return {
        "total_organizations": int(row["total_organizations"]),
        "non_profit_organizations": int(row["non_profit_organizations"]),
        "for_profit_organizations": int(row["for_profit_organizations"]),
        "collaborator_organizations": int(row["collaborator_organizations"]),
        "non_collaborator_organizations": int(row["non_collaborator_organizations"]),
        "contributor_organizations": int(row["contributor_organizations"]),
        "non_contributor_organizations": int(row["non_contributor_organizations"]),
    }


def get_activity_trend(cursor, time_filter, start_date, end_date, filters, group_by):
    period, date_format = get_grouping(group_by)
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
               COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY 1
        ORDER BY 1
    """
    cursor.execute(query, params)
    return [{"period": row["period"], "count": int(row["count"])} for row in cursor.fetchall()]


def get_by_type(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT o.org_type AS type, COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY o.org_type
        ORDER BY o.org_type
    """
    cursor.execute(query, params)
    return [{"type": row["type"], "count": int(row["count"])} for row in cursor.fetchall()]


def get_by_size(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT o.org_size AS size, COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY o.org_size
        ORDER BY o.org_size
    """
    cursor.execute(query, params)
    return [{"size": row["size"], "count": int(row["count"])} for row in cursor.fetchall()]


def get_by_location(cursor, time_filter, start_date, end_date, filters):
    # city_name lives directly on organizations (no city table FK), so it's grouped
    # as-is; state is joined for a readable name/code alongside the raw state_id.
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT s.state_name AS state, s.state_code AS state_code, o.city_name AS city,
               COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        LEFT JOIN {STATE} s ON o.state_id = s.state_id
        {where_sql}
        GROUP BY s.state_name, s.state_code, o.city_name
        ORDER BY count DESC
    """
    cursor.execute(query, params)
    return [
        {
            "state": row["state"],
            "state_code": row["state_code"],
            "city": row["city"],
            "count": int(row["count"]),
        }
        for row in cursor.fetchall()
    ]


def get_collaborator_distribution(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT COALESCE(o.is_collaborator, FALSE) AS is_collaborator, COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY COALESCE(o.is_collaborator, FALSE)
        ORDER BY is_collaborator DESC
    """
    cursor.execute(query, params)
    return [
        {"is_collaborator": bool(row["is_collaborator"]), "count": int(row["count"])}
        for row in cursor.fetchall()
    ]


def get_contributor_distribution(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT COALESCE(o.is_contributor, FALSE) AS is_contributor, COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY COALESCE(o.is_contributor, FALSE)
        ORDER BY is_contributor DESC
    """
    cursor.execute(query, params)
    return [
        {"is_contributor": bool(row["is_contributor"]), "count": int(row["count"])}
        for row in cursor.fetchall()
    ]


# ---------------------------------------------------------------------------
# Performance dashboard
# ---------------------------------------------------------------------------

def get_performance_summary(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_organizations,
            COUNT(*) FILTER (WHERE o.org_rating IS NULL) AS unrated_organizations,
            COUNT(*) FILTER (WHERE o.org_rating = 5) AS five_star_organizations
        FROM {ORGANIZATIONS} o
        {where_sql}
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    return {
        "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0,
        "rated_organizations": int(row["rated_organizations"]),
        "unrated_organizations": int(row["unrated_organizations"]),
        "five_star_organizations": int(row["five_star_organizations"]),
    }


def get_rating_distribution(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT o.org_rating AS rating, COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY o.org_rating
        ORDER BY o.org_rating NULLS LAST
    """
    cursor.execute(query, params)
    return [{"rating": row["rating"], "count": int(row["count"])} for row in cursor.fetchall()]


def _top_organizations(cursor, where_sql, params, extra_condition, limit):
    where_sql = f"{where_sql} AND {extra_condition}" if where_sql else f"WHERE {extra_condition}"
    query = f"""
        SELECT o.org_id, o.org_name, o.org_rating AS rating, o.org_type AS type, o.org_size AS size
        FROM {ORGANIZATIONS} o
        {where_sql}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
        LIMIT %s
    """
    cursor.execute(query, params + [limit])
    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "rating": row["rating"],
            "type": row["type"],
            "size": row["size"],
        }
        for row in cursor.fetchall()
    ]


def get_top_rated_organizations(cursor, time_filter, start_date, end_date, filters, limit=10):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    return _top_organizations(cursor, where_sql, params, "o.org_rating IS NOT NULL", limit)


def get_top_collaborator_organizations(cursor, time_filter, start_date, end_date, filters, limit=10):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    return _top_organizations(cursor, where_sql, params, "o.is_collaborator IS TRUE", limit)


def get_top_contributor_organizations(cursor, time_filter, start_date, end_date, filters, limit=10):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    return _top_organizations(cursor, where_sql, params, "o.is_contributor IS TRUE", limit)


def get_ratings_by_type(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT o.org_type AS type,
               ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
               COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY o.org_type
        ORDER BY o.org_type
    """
    cursor.execute(query, params)
    return [
        {
            "type": row["type"],
            "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0,
            "count": int(row["count"]),
        }
        for row in cursor.fetchall()
    ]


def get_ratings_by_size(cursor, time_filter, start_date, end_date, filters):
    where_sql, params = build_where_clause(time_filter, start_date, end_date, filters)
    query = f"""
        SELECT o.org_size AS size,
               ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
               COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY o.org_size
        ORDER BY o.org_size
    """
    cursor.execute(query, params)
    return [
        {
            "size": row["size"],
            "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0,
            "count": int(row["count"]),
        }
        for row in cursor.fetchall()
    ]


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def get_default_response(dashboard_type):
    if dashboard_type == "performance":
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


def lambda_handler(event, context):
    conn = None
    cursor = None

    request_body = parse_event_body(event)
    dashboard_type = request_body.get("dashboard_type", "overview")
    time_filter = request_body.get("time_filter", "30D")
    start_date = request_body.get("start_date")
    end_date = request_body.get("end_date")
    group_by = request_body.get("group_by", "daily")

    filters = {
        "org_type": request_body.get("org_type"),
        "org_size": request_body.get("org_size"),
        "state_id": request_body.get("state_id"),
        "city_name": request_body.get("city_name"),
        "org_rating": request_body.get("org_rating"),
        "is_collaborator": request_body.get("is_collaborator"),
        "is_contributor": request_body.get("is_contributor"),
    }

    response_body = get_default_response(dashboard_type)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        print("Database connected successfully.")

        # Each metric is wrapped individually so one bad query leaves its slot at the
        # safe default instead of blanking out the whole dashboard response.
        if dashboard_type == "performance":
            section = response_body["organization_performance"]

            try:
                section["summary"] = get_performance_summary(cursor, time_filter, start_date, end_date, filters)
            except Exception as e:
                print(f"performance summary failed: {e}")

            try:
                section["rating_distribution"] = get_rating_distribution(cursor, time_filter, start_date, end_date, filters)
            except Exception as e:
                print(f"rating_distribution failed: {e}")

            try:
                section["top_rated_organizations"] = get_top_rated_organizations(cursor, time_filter, start_date, end_date, filters)
            except Exception as e:
                print(f"top_rated_organizations failed: {e}")

            try:
                section["top_collaborator_organizations"] = get_top_collaborator_organizations(cursor, time_filter, start_date, end_date, filters)
            except Exception as e:
                print(f"top_collaborator_organizations failed: {e}")

            try:
                section["top_contributor_organizations"] = get_top_contributor_organizations(cursor, time_filter, start_date, end_date, filters)
            except Exception as e:
                print(f"top_contributor_organizations failed: {e}")

            try:
                section["ratings_by_organization_type"] = get_ratings_by_type(cursor, time_filter, start_date, end_date, filters)
            except Exception as e:
                print(f"ratings_by_organization_type failed: {e}")

            try:
                section["ratings_by_organization_size"] = get_ratings_by_size(cursor, time_filter, start_date, end_date, filters)
            except Exception as e:
                print(f"ratings_by_organization_size failed: {e}")

        else:
            section = response_body["organization_overview"]

            try:
                section["summary"] = get_summary(cursor, time_filter, start_date, end_date, filters)
            except Exception as e:
                print(f"summary failed: {e}")

            try:
                section["organization_activity_trend"] = get_activity_trend(cursor, time_filter, start_date, end_date, filters, group_by)
            except Exception as e:
                print(f"organization_activity_trend failed: {e}")

            try:
                section["organizations_by_type"] = get_by_type(cursor, time_filter, start_date, end_date, filters)
            except Exception as e:
                print(f"organizations_by_type failed: {e}")

            try:
                section["organizations_by_size"] = get_by_size(cursor, time_filter, start_date, end_date, filters)
            except Exception as e:
                print(f"organizations_by_size failed: {e}")

            try:
                section["organizations_by_location"] = get_by_location(cursor, time_filter, start_date, end_date, filters)
            except Exception as e:
                print(f"organizations_by_location failed: {e}")

            try:
                section["collaborator_distribution"] = get_collaborator_distribution(cursor, time_filter, start_date, end_date, filters)
            except Exception as e:
                print(f"collaborator_distribution failed: {e}")

            try:
                section["contributor_distribution"] = get_contributor_distribution(cursor, time_filter, start_date, end_date, filters)
            except Exception as e:
                print(f"contributor_distribution failed: {e}")

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