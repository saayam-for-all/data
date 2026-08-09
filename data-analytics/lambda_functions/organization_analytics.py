import json
import os
from datetime import date

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"

# Name of the environment variable holding the Parameter Store name for the DB
# credentials. The path itself is configured on the Lambda, never in the code.
DB_CREDENTIALS_ENV_VAR = "DB_CREDENTIALS_PARAMETER"

# Column required by the analytics spec but not yet present in the deployed
# organizations table; contributor metrics degrade gracefully without it.
CONTRIBUTOR_COLUMN = "is_contributor"

VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
VALID_GROUP_BY = {"daily", "weekly", "monthly", "yearly"}
VALID_DASHBOARDS = {"overview", "performance"}

MIN_RATING = 1
MAX_RATING = 5

# ddl_organizations.sql declares org_type/org_size as lowercase enums
# ('non_profit', 'small'), but the source extracts in data-analytics/sql
# carry display labels ('Non-Profit', 'For-profit', 'Small'). Both are
# normalized to the enum form so the API reports the same buckets either way.
NORMALIZED_ORG_TYPE = "REPLACE(LOWER(o.org_type::text), '-', '_')"
NORMALIZED_ORG_SIZE = "REPLACE(LOWER(o.org_size::text), '-', '_')"


def normalize_label(value):
    """'Non-Profit' / 'non profit' / 'NON_PROFIT' -> 'non_profit'."""
    if value is None:
        return None
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")

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
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            database=os.environ.get("DB_NAME", "saayam_local"),
            user=os.environ.get("DB_USER", "saayam"),
            password=os.environ.get("DB_PASSWORD", "saayam_local"),
            port=os.environ.get("DB_PORT", "5432")
        )
        # Read-only workload: each statement stands alone, so one failed metric
        # cannot leave the connection in an aborted transaction.
        conn.autocommit = True
        return conn

    parameter_name = os.environ.get(DB_CREDENTIALS_ENV_VAR)
    if not parameter_name:
        raise RuntimeError(
            f"{DB_CREDENTIALS_ENV_VAR} is not set. Configure it on the Lambda with "
            "the Parameter Store name that holds the analytics DB credentials, "
            "or set LOCAL_DB=true for local PostgreSQL testing."
        )

    ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    response = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
    creds = json.loads(response["Parameter"]["Value"])
    conn = psycopg2.connect(
        host=creds["HOST"],
        database=creds["DATABASE NAME"],
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require"
    )
    conn.autocommit = True
    return conn


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


def has_contributor_column(cursor):
    """The organizations table may not carry is_contributor yet (see task notes)."""
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = 'organizations'
          AND column_name = %s;
        """,
        [SCHEMA_NAME, CONTRIBUTOR_COLUMN]
    )
    return cursor.fetchone() is not None


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
            if org_rating < MIN_RATING or org_rating > MAX_RATING:
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


def validate_filters(filters):
    """Return an error message for filter combinations that cannot be honoured."""
    if filters["time_filter"] != "CUSTOM":
        return None

    start_date = filters["start_date"]
    end_date = filters["end_date"]

    if not start_date or not end_date:
        return "time_filter 'CUSTOM' requires both start_date and end_date (YYYY-MM-DD)."

    try:
        parsed_start = date.fromisoformat(str(start_date))
        parsed_end = date.fromisoformat(str(end_date))
    except ValueError:
        return "start_date and end_date must be ISO dates in YYYY-MM-DD format."

    if parsed_start > parsed_end:
        return "start_date must not be later than end_date."

    return None


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


def build_condition_list(filters):
    """SQL conditions + params for every active filter, without the WHERE keyword."""
    conditions = []
    params = []

    date_condition, date_params = build_date_filter(filters)
    if date_condition:
        conditions.append(date_condition)
        params.extend(date_params)

    if filters["org_type"]:
        conditions.append(f"{NORMALIZED_ORG_TYPE} = %s")
        params.append(normalize_label(filters["org_type"]))

    if filters["org_size"]:
        conditions.append(f"{NORMALIZED_ORG_SIZE} = %s")
        params.append(normalize_label(filters["org_size"]))

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

    if filters["is_contributor"] is not None and filters.get("_has_contributor"):
        conditions.append(f"o.{CONTRIBUTOR_COLUMN} = %s")
        params.append(bool(filters["is_contributor"]))

    return conditions, params


def build_common_filters(filters):
    conditions, params = build_condition_list(filters)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where_clause, params


# ---------------------------------------------------------------------------
# Dashboard 1: Organization Overview
# ---------------------------------------------------------------------------

def fetch_overview_summary(cursor, filters):
    where_clause, params = build_common_filters(filters)

    if filters.get("_has_contributor"):
        contributor_columns = f"""
            COUNT(o.org_id) FILTER (WHERE o.{CONTRIBUTOR_COLUMN} IS TRUE) AS contributor_organizations,
            COUNT(o.org_id) FILTER (WHERE o.{CONTRIBUTOR_COLUMN} IS NOT TRUE) AS non_contributor_organizations"""
    else:
        contributor_columns = """
            0 AS contributor_organizations,
            0 AS non_contributor_organizations"""

    query = f"""
        SELECT
            COUNT(o.org_id) AS total_organizations,
            COUNT(o.org_id) FILTER (WHERE {NORMALIZED_ORG_TYPE} = 'non_profit') AS non_profit_organizations,
            COUNT(o.org_id) FILTER (WHERE {NORMALIZED_ORG_TYPE} = 'for_profit') AS for_profit_organizations,
            COUNT(o.org_id) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_organizations,
            COUNT(o.org_id) FILTER (WHERE o.is_collaborator IS NOT TRUE) AS non_collaborator_organizations,
            {contributor_columns}
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
            {NORMALIZED_ORG_TYPE} AS type,
            COUNT(o.org_id) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY {NORMALIZED_ORG_TYPE}
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
            {NORMALIZED_ORG_SIZE} AS size,
            COUNT(o.org_id) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY {NORMALIZED_ORG_SIZE}
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
    if not filters.get("_has_contributor"):
        return []

    where_clause, params = build_common_filters(filters)

    query = f"""
        SELECT
            CASE WHEN o.{CONTRIBUTOR_COLUMN} IS TRUE
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
    # LEFT JOIN against generate_series so every rating 1-5 is present, including
    # the ones no organization currently holds (the dashboard charts all 5 bars).
    conditions, params = build_condition_list(filters)
    conditions.append("o.org_rating = r.rating")
    join_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            r.rating AS rating,
            COUNT(o.org_id) AS count
        FROM generate_series({MIN_RATING}, {MAX_RATING}) AS r(rating)
        LEFT JOIN {SCHEMA_NAME}.organizations o
            ON {join_clause}
        GROUP BY r.rating
        ORDER BY r.rating;
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
            {NORMALIZED_ORG_TYPE} AS org_type,
            {NORMALIZED_ORG_SIZE} AS org_size,
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
            {NORMALIZED_ORG_TYPE} AS org_type,
            {NORMALIZED_ORG_SIZE} AS org_size,
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


def fetch_ratings_by_dimension(cursor, filters, dimension_expression, dimension_key):
    where_clause, params = build_common_filters(filters)
    rating_condition = "o.org_rating IS NOT NULL"
    where_clause = (f"{where_clause} AND {rating_condition}"
                    if where_clause else f"WHERE {rating_condition}")

    query = f"""
        SELECT
            {dimension_expression} AS dimension,
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(o.org_id) AS rated_organizations,
            COUNT(o.org_id) FILTER (WHERE o.org_rating = {MAX_RATING}) AS five_star_organizations
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY {dimension_expression}
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

def run_metric(cursor, description, fetcher, *args):
    """Run one metric query, keeping the connection usable if it fails.

    PostgreSQL aborts the surrounding transaction on any error, so without the
    rollback below a single bad query would make every later metric fail with
    InFailedSqlTransaction. Returns None when the metric could not be produced,
    leaving the caller's safe default in place.
    """
    try:
        return fetcher(cursor, *args)
    except Exception as error:
        print(f"{description} query failed: {error}")
        try:
            cursor.connection.rollback()
        except Exception as rollback_error:
            print(f"Rollback after {description} failed: {rollback_error}")
        return None


def assign_metric(target, key, cursor, description, fetcher, *args):
    result = run_metric(cursor, description, fetcher, *args)
    if result is not None:
        target[key] = result


def build_overview_dashboard(cursor, filters):
    response_body = get_default_overview_response()
    overview = response_body["organization_overview"]

    metrics = [
        ("summary", "Overview summary", fetch_overview_summary),
        ("organization_activity_trend", "Organization activity trend", fetch_organization_activity_trend),
        ("organizations_by_type", "Organizations by type", fetch_organizations_by_type),
        ("organizations_by_size", "Organizations by size", fetch_organizations_by_size),
        ("organizations_by_location", "Organizations by location", fetch_organizations_by_location),
        ("collaborator_distribution", "Collaborator distribution", fetch_collaborator_distribution),
        ("contributor_distribution", "Contributor distribution", fetch_contributor_distribution),
    ]

    for key, description, fetcher in metrics:
        assign_metric(overview, key, cursor, description, fetcher, filters)

    return response_body


def build_performance_dashboard(cursor, filters):
    response_body = get_default_performance_response()
    performance = response_body["organization_performance"]

    metrics = [
        ("summary", "Performance summary", fetch_performance_summary, (filters,)),
        ("rating_distribution", "Rating distribution", fetch_rating_distribution, (filters,)),
        ("top_rated_organizations", "Top rated organizations", fetch_top_rated_organizations, (filters,)),
        ("top_collaborator_organizations", "Top collaborator organizations",
         fetch_top_flagged_organizations, (filters, "is_collaborator")),
        ("ratings_by_organization_type", "Ratings by organization type",
         fetch_ratings_by_dimension, (filters, NORMALIZED_ORG_TYPE, "type")),
        ("ratings_by_organization_size", "Ratings by organization size",
         fetch_ratings_by_dimension, (filters, NORMALIZED_ORG_SIZE, "size")),
    ]

    if filters.get("_has_contributor"):
        metrics.insert(4, ("top_contributor_organizations", "Top contributor organizations",
                           fetch_top_flagged_organizations, (filters, CONTRIBUTOR_COLUMN)))

    for key, description, fetcher, args in metrics:
        assign_metric(performance, key, cursor, description, fetcher, *args)

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

    validation_error = validate_filters(filters)
    if validation_error:
        return build_response(400, {"error": validation_error})

    if dashboard_type == "overview":
        response_body = get_default_overview_response()
    else:
        response_body = get_default_performance_response()

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        filters["_has_contributor"] = has_contributor_column(cursor)

        if dashboard_type == "overview":
            response_body = build_overview_dashboard(cursor, filters)
        else:
            response_body = build_performance_dashboard(cursor, filters)

        response_body["filters_applied"] = {
            key: value for key, value in filters.items() if not key.startswith("_")
        }
        if not filters["_has_contributor"]:
            response_body["schema_notes"] = [
                f"Column '{CONTRIBUTOR_COLUMN}' is not present in "
                f"{SCHEMA_NAME}.organizations; contributor metrics return 0/empty "
                "and the is_contributor filter is ignored."
            ]
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
