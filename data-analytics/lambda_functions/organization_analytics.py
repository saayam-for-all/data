import json
import os
import boto3
import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"

VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
VALID_GROUP_BY = {"daily", "weekly", "monthly", "yearly"}
VALID_DASHBOARDS = {"overview", "performance"}

GROUP_BY_TRUNC = {
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
    "yearly": "year"
}

TOP_N_LIMIT = 10


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
                "average_rating": 0,
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


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, default=str)
    }


def get_db_connection():
    if os.environ.get("LOCAL_DB", "").lower() == "true":
        return psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            database=os.environ.get("DB_NAME", "saayam_local"),
            user=os.environ.get("DB_USER", "saayam"),
            password=os.environ.get("DB_PASSWORD", "saayam_local"),
            port=os.environ.get("DB_PORT", "5432")
        )

    ssm = boto3.client("ssm", region_name="us-east-1")
    response = ssm.get_parameter(
        Name="/dev/saayam/db/Virginia/Analytics/user",
        WithDecryption=True
    )
    creds = json.loads(response["Parameter"]["Value"])
    return psycopg2.connect(
        host=creds["HOST"],
        database=creds["DATABASE NAME"],
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require"
    )


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


def parse_filters(request_body):
    time_filter = str(request_body.get("time_filter", "ALL")).upper()
    if time_filter not in VALID_TIME_FILTERS:
        time_filter = "ALL"

    group_by = str(request_body.get("group_by", "daily")).lower()
    if group_by not in VALID_GROUP_BY:
        group_by = "daily"

    org_rating = request_body.get("org_rating", None)
    if org_rating is not None:
        try:
            org_rating = int(org_rating)
            if org_rating < 1 or org_rating > 5:
                org_rating = None
        except (TypeError, ValueError):
            org_rating = None

    return {
        "time_filter": time_filter,
        "start_date": request_body.get("start_date", None),
        "end_date": request_body.get("end_date", None),
        "org_type": request_body.get("org_type", None),
        "org_size": request_body.get("org_size", None),
        "state_id": request_body.get("state_id", None),
        "city_name": request_body.get("city_name", None),
        "org_rating": org_rating,
        "is_collaborator": request_body.get("is_collaborator", None),
        "is_contributor": request_body.get("is_contributor", None),
        "group_by": group_by
    }


def build_date_filter(filters, column="o.created_at"):
    time_filter = filters["time_filter"]
    start_date = filters["start_date"]
    end_date = filters["end_date"]

    if time_filter == "CUSTOM" and start_date and end_date:
        return f"{column}::date BETWEEN %s AND %s", [start_date, end_date]
    if time_filter == "7D":
        return f"{column} >= CURRENT_DATE - INTERVAL '7 days'", []
    if time_filter == "30D":
        return f"{column} >= CURRENT_DATE - INTERVAL '30 days'", []
    if time_filter == "1Y":
        return f"{column} >= CURRENT_DATE - INTERVAL '1 year'", []

    return "", []


def build_common_filters(filters):
    conditions = []
    params = []

    date_condition, date_params = build_date_filter(filters)
    if date_condition:
        conditions.append(date_condition)
        params.extend(date_params)

    if filters["org_type"]:
        conditions.append("o.org_type = %s")
        params.append(filters["org_type"])

    if filters["org_size"]:
        conditions.append("o.org_size = %s")
        params.append(filters["org_size"])

    if filters["state_id"]:
        conditions.append("o.state_id = %s")
        params.append(filters["state_id"])

    if filters["city_name"]:
        conditions.append("LOWER(o.city_name) = LOWER(%s)")
        params.append(filters["city_name"])

    if filters["org_rating"] is not None:
        conditions.append("o.org_rating = %s")
        params.append(filters["org_rating"])

    if filters["is_collaborator"] is not None:
        conditions.append("o.is_collaborator = %s")
        params.append(bool(filters["is_collaborator"]))

    if filters["is_contributor"] is not None:
        conditions.append("o.is_contributor = %s")
        params.append(bool(filters["is_contributor"]))

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where_clause, params


# ---------------------------------------------------------------------------
# Dashboard 1: Organization Overview
# ---------------------------------------------------------------------------

def fetch_overview_summary(cursor, filters):
    where_clause, params = build_common_filters(filters)

    query = f"""
        SELECT
            COUNT(o.org_id) AS total_organizations,
            COUNT(o.org_id) FILTER (WHERE o.org_type = 'non_profit') AS non_profit_organizations,
            COUNT(o.org_id) FILTER (WHERE o.org_type = 'for_profit') AS for_profit_organizations,
            COUNT(o.org_id) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_organizations,
            COUNT(o.org_id) FILTER (WHERE o.is_collaborator IS NOT TRUE) AS non_collaborator_organizations,
            COUNT(o.org_id) FILTER (WHERE o.is_contributor IS TRUE) AS contributor_organizations,
            COUNT(o.org_id) FILTER (WHERE o.is_contributor IS NOT TRUE) AS non_contributor_organizations
        FROM {SCHEMA_NAME}.organizations o
        {where_clause};
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
        "non_contributor_organizations": int(row["non_contributor_organizations"])
    }


def fetch_organization_activity_trend(cursor, filters):
    where_clause, params = build_common_filters(filters)
    trunc_unit = GROUP_BY_TRUNC[filters["group_by"]]

    query = f"""
        SELECT
            DATE_TRUNC('{trunc_unit}', o.created_at)::date AS period,
            COUNT(o.org_id) AS new_organizations
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY period
        ORDER BY period;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    trend = []
    running_total = 0
    for row in rows:
        running_total += int(row["new_organizations"])
        trend.append({
            "period": str(row["period"]),
            "new_organizations": int(row["new_organizations"]),
            "total_organizations": running_total
        })
    return trend


def fetch_organizations_by_type(cursor, filters):
    where_clause, params = build_common_filters(filters)

    query = f"""
        SELECT
            o.org_type AS type,
            COUNT(o.org_id) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.org_type
        ORDER BY count DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "type": row["type"] if row["type"] is not None else "unknown",
            "count": int(row["count"])
        }
        for row in rows
    ]


def fetch_organizations_by_size(cursor, filters):
    where_clause, params = build_common_filters(filters)

    query = f"""
        SELECT
            o.org_size AS size,
            COUNT(o.org_id) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.org_size
        ORDER BY count DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "size": row["size"] if row["size"] is not None else "unknown",
            "count": int(row["count"])
        }
        for row in rows
    ]


def fetch_organizations_by_location(cursor, filters):
    where_clause, params = build_common_filters(filters)

    query = f"""
        SELECT
            COALESCE(s.state_name, 'Unknown') AS state,
            COALESCE(o.city_name, 'Unknown') AS city,
            COUNT(o.org_id) AS count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s
            ON o.state_id = s.state_id
        {where_clause}
        GROUP BY s.state_name, o.city_name
        ORDER BY count DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "state": row["state"],
            "city": row["city"],
            "count": int(row["count"])
        }
        for row in rows
    ]


def fetch_collaborator_distribution(cursor, filters):
    where_clause, params = build_common_filters(filters)

    query = f"""
        SELECT
            CASE WHEN o.is_collaborator IS TRUE
                 THEN 'collaborator' ELSE 'non_collaborator' END AS category,
            COUNT(o.org_id) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY category
        ORDER BY category;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "category": row["category"],
            "count": int(row["count"])
        }
        for row in rows
    ]


def fetch_contributor_distribution(cursor, filters):
    where_clause, params = build_common_filters(filters)

    query = f"""
        SELECT
            CASE WHEN o.is_contributor IS TRUE
                 THEN 'contributor' ELSE 'non_contributor' END AS category,
            COUNT(o.org_id) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY category
        ORDER BY category;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "category": row["category"],
            "count": int(row["count"])
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Dashboard 2: Organization Performance
# ---------------------------------------------------------------------------

def fetch_performance_summary(cursor, filters):
    where_clause, params = build_common_filters(filters)

    query = f"""
        SELECT
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(o.org_id) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_organizations,
            COUNT(o.org_id) FILTER (WHERE o.org_rating IS NULL) AS unrated_organizations,
            COUNT(o.org_id) FILTER (WHERE o.org_rating = 5) AS five_star_organizations
        FROM {SCHEMA_NAME}.organizations o
        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    return {
        "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0,
        "rated_organizations": int(row["rated_organizations"]),
        "unrated_organizations": int(row["unrated_organizations"]),
        "five_star_organizations": int(row["five_star_organizations"])
    }


def fetch_rating_distribution(cursor, filters):
    where_clause, params = build_common_filters(filters)
    rating_condition = "o.org_rating IS NOT NULL"
    where_clause = (f"{where_clause} AND {rating_condition}"
                    if where_clause else f"WHERE {rating_condition}")

    query = f"""
        SELECT
            o.org_rating AS rating,
            COUNT(o.org_id) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.org_rating
        ORDER BY o.org_rating;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "rating": int(row["rating"]),
            "count": int(row["count"])
        }
        for row in rows
    ]


def fetch_top_rated_organizations(cursor, filters):
    where_clause, params = build_common_filters(filters)
    rating_condition = "o.org_rating IS NOT NULL"
    where_clause = (f"{where_clause} AND {rating_condition}"
                    if where_clause else f"WHERE {rating_condition}")

    query = f"""
        SELECT
            o.org_id,
            o.org_name,
            o.org_type,
            o.org_size,
            o.org_rating,
            COALESCE(s.state_name, 'Unknown') AS state,
            COALESCE(o.city_name, 'Unknown') AS city
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s
            ON o.state_id = s.state_id
        {where_clause}
        ORDER BY o.org_rating DESC, o.org_name ASC
        LIMIT {TOP_N_LIMIT};
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "org_type": row["org_type"],
            "org_size": row["org_size"],
            "org_rating": int(row["org_rating"]),
            "state": row["state"],
            "city": row["city"]
        }
        for row in rows
    ]


def fetch_top_flagged_organizations(cursor, filters, flag_column):
    where_clause, params = build_common_filters(filters)
    flag_condition = f"o.{flag_column} IS TRUE AND o.org_rating IS NOT NULL"
    where_clause = (f"{where_clause} AND {flag_condition}"
                    if where_clause else f"WHERE {flag_condition}")

    query = f"""
        SELECT
            o.org_id,
            o.org_name,
            o.org_type,
            o.org_size,
            o.org_rating,
            COALESCE(s.state_name, 'Unknown') AS state,
            COALESCE(o.city_name, 'Unknown') AS city
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s
            ON o.state_id = s.state_id
        {where_clause}
        ORDER BY o.org_rating DESC, o.org_name ASC
        LIMIT {TOP_N_LIMIT};
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "org_type": row["org_type"],
            "org_size": row["org_size"],
            "org_rating": int(row["org_rating"]),
            "state": row["state"],
            "city": row["city"]
        }
        for row in rows
    ]


def fetch_ratings_by_dimension(cursor, filters, dimension_column, dimension_key):
    where_clause, params = build_common_filters(filters)
    rating_condition = "o.org_rating IS NOT NULL"
    where_clause = (f"{where_clause} AND {rating_condition}"
                    if where_clause else f"WHERE {rating_condition}")

    query = f"""
        SELECT
            o.{dimension_column} AS dimension,
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(o.org_id) AS rated_organizations,
            COUNT(o.org_id) FILTER (WHERE o.org_rating = 5) AS five_star_organizations
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.{dimension_column}
        ORDER BY average_rating DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            dimension_key: row["dimension"] if row["dimension"] is not None else "unknown",
            "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0,
            "rated_organizations": int(row["rated_organizations"]),
            "five_star_organizations": int(row["five_star_organizations"])
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Dashboard builders
# ---------------------------------------------------------------------------

def build_overview_dashboard(cursor, filters):
    response_body = get_default_overview_response()
    overview = response_body["organization_overview"]

    try:
        overview["summary"] = fetch_overview_summary(cursor, filters)
    except Exception as error:
        print(f"Overview summary query failed: {error}")

    try:
        overview["organization_activity_trend"] = fetch_organization_activity_trend(cursor, filters)
    except Exception as error:
        print(f"Organization activity trend query failed: {error}")

    try:
        overview["organizations_by_type"] = fetch_organizations_by_type(cursor, filters)
    except Exception as error:
        print(f"Organizations by type query failed: {error}")

    try:
        overview["organizations_by_size"] = fetch_organizations_by_size(cursor, filters)
    except Exception as error:
        print(f"Organizations by size query failed: {error}")

    try:
        overview["organizations_by_location"] = fetch_organizations_by_location(cursor, filters)
    except Exception as error:
        print(f"Organizations by location query failed: {error}")

    try:
        overview["collaborator_distribution"] = fetch_collaborator_distribution(cursor, filters)
    except Exception as error:
        print(f"Collaborator distribution query failed: {error}")

    try:
        overview["contributor_distribution"] = fetch_contributor_distribution(cursor, filters)
    except Exception as error:
        print(f"Contributor distribution query failed: {error}")

    return response_body


def build_performance_dashboard(cursor, filters):
    response_body = get_default_performance_response()
    performance = response_body["organization_performance"]

    try:
        performance["summary"] = fetch_performance_summary(cursor, filters)
    except Exception as error:
        print(f"Performance summary query failed: {error}")

    try:
        performance["rating_distribution"] = fetch_rating_distribution(cursor, filters)
    except Exception as error:
        print(f"Rating distribution query failed: {error}")

    try:
        performance["top_rated_organizations"] = fetch_top_rated_organizations(cursor, filters)
    except Exception as error:
        print(f"Top rated organizations query failed: {error}")

    try:
        performance["top_collaborator_organizations"] = fetch_top_flagged_organizations(cursor, filters, "is_collaborator")
    except Exception as error:
        print(f"Top collaborator organizations query failed: {error}")

    try:
        performance["top_contributor_organizations"] = fetch_top_flagged_organizations(cursor, filters, "is_contributor")
    except Exception as error:
        print(f"Top contributor organizations query failed: {error}")

    try:
        performance["ratings_by_organization_type"] = fetch_ratings_by_dimension(cursor, filters, "org_type", "type")
    except Exception as error:
        print(f"Ratings by organization type query failed: {error}")

    try:
        performance["ratings_by_organization_size"] = fetch_ratings_by_dimension(cursor, filters, "org_size", "size")
    except Exception as error:
        print(f"Ratings by organization size query failed: {error}")

    return response_body


def lambda_handler(event, context):
    conn = None
    cursor = None

    request_body = parse_event_body(event)

    dashboard_type = str(request_body.get("dashboard_type", "overview")).lower()
    if dashboard_type not in VALID_DASHBOARDS:
        return build_response(400, {
            "error": f"Invalid dashboard_type '{dashboard_type}'. "
                     f"Supported values: {sorted(VALID_DASHBOARDS)}"
        })

    filters = parse_filters(request_body)

    if dashboard_type == "overview":
        response_body = get_default_overview_response()
    else:
        response_body = get_default_performance_response()

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if dashboard_type == "overview":
            response_body = build_overview_dashboard(cursor, filters)
        else:
            response_body = build_performance_dashboard(cursor, filters)

        response_body["filters_applied"] = filters
        return build_response(200, response_body)

    except Exception as error:
        print(f"DB connection failed: {error}")
        return build_response(500, response_body)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    os.environ["LOCAL_DB"] = "true"

    result_overview = lambda_handler({"dashboard_type": "overview", "time_filter": "ALL"}, None)
    print(json.dumps(json.loads(result_overview["body"]), indent=2))

    result_performance = lambda_handler({"dashboard_type": "performance", "time_filter": "ALL"}, None)
    print(json.dumps(json.loads(result_performance["body"]), indent=2))
