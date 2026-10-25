import json
import os

import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = os.getenv("DB_SCHEMA", "virginia_dev_saayam_rdbms")

SUPPORTED_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
SUPPORTED_GROUP_BY = {"daily", "weekly", "monthly", "yearly"}


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
    """
    Local PostgreSQL connection.

    Required environment variables:
        DB_HOST
        DB_NAME
        DB_USER
        DB_PASSWORD

    Optional:
        DB_PORT
        DB_SCHEMA

    AWS Parameter Store is intentionally not used for Issue #228.
    """
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", "5432")
    )


def build_date_filter(time_filter="ALL", start_date=None, end_date=None):
    time_filter = (time_filter or "ALL").upper()

    if time_filter not in SUPPORTED_TIME_FILTERS:
        raise ValueError(
            "time_filter must be one of: 7D, 30D, 1Y, ALL, CUSTOM"
        )

    if time_filter == "7D":
        return "o.created_at >= CURRENT_DATE - INTERVAL '7 days'", []

    if time_filter == "30D":
        return "o.created_at >= CURRENT_DATE - INTERVAL '30 days'", []

    if time_filter == "1Y":
        return "o.created_at >= CURRENT_DATE - INTERVAL '1 year'", []

    if time_filter == "ALL":
        return "", []

    if not start_date or not end_date:
        raise ValueError(
            "start_date and end_date are required for CUSTOM time_filter"
        )

    return "o.created_at BETWEEN %s AND %s", [start_date, end_date]


def build_filters(filters):
    conditions = []
    params = []

    date_condition, date_params = build_date_filter(
        filters.get("time_filter", "ALL"),
        filters.get("start_date"),
        filters.get("end_date")
    )

    if date_condition:
        conditions.append(date_condition)
        params.extend(date_params)

    if filters.get("org_type"):
        conditions.append("o.org_type = %s")
        params.append(filters["org_type"])

    if filters.get("org_size"):
        conditions.append("o.org_size = %s")
        params.append(filters["org_size"])

    if filters.get("state_id"):
        conditions.append("o.state_id = %s")
        params.append(filters["state_id"])

    if filters.get("city_name"):
        conditions.append("o.city_name = %s")
        params.append(filters["city_name"])

    if filters.get("org_rating") is not None:
        conditions.append("o.org_rating = %s")
        params.append(filters["org_rating"])

    if filters.get("is_collaborator") is not None:
        conditions.append("o.is_collaborator = %s")
        params.append(filters["is_collaborator"])

    if filters.get("is_contributor") is not None:
        raise ValueError(
            "is_contributor filtering is not currently available because "
            "the is_contributor field has not yet been added to the database"
        )

    where_clause = ""

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    return where_clause, params


def execute_one(cursor, query, params):
    cursor.execute(query, params)
    return cursor.fetchone()


def execute_all(cursor, query, params):
    cursor.execute(query, params)
    return cursor.fetchall()


# ----------------------------------------------------------------------
# Organization Overview Dashboard
# ----------------------------------------------------------------------

def get_total_organizations(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT COUNT(*) AS total
        FROM {SCHEMA_NAME}.organizations o
        {where_clause};
    """

    row = execute_one(cursor, query, params)

    return int(row["total"] or 0)


def get_organizations_by_type(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            o.org_type,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.org_type
        ORDER BY count DESC;
    """

    rows = execute_all(cursor, query, params)

    return [
        {
            "org_type": row["org_type"],
            "count": int(row["count"])
        }
        for row in rows
    ]


def get_organizations_by_size(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            o.org_size,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.org_size
        ORDER BY count DESC;
    """

    rows = execute_all(cursor, query, params)

    return [
        {
            "org_size": row["org_size"],
            "count": int(row["count"])
        }
        for row in rows
    ]


def get_collaborator_distribution(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            o.is_collaborator,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.is_collaborator
        ORDER BY o.is_collaborator DESC;
    """

    rows = execute_all(cursor, query, params)

    return [
        {
            "is_collaborator": bool(row["is_collaborator"]),
            "count": int(row["count"])
        }
        for row in rows
    ]


def get_contributor_distribution(cursor, filters):
    """
    Issue #228 includes contributor analytics, but is_contributor is not
    currently available in the database. Return an empty result until
    the database field becomes available.
    """
    return []


def get_organizations_by_location(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            o.state_id,
            o.city_name,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.state_id, o.city_name
        ORDER BY count DESC, o.state_id, o.city_name;
    """

    rows = execute_all(cursor, query, params)

    return [
        {
            "state_id": row["state_id"],
            "city_name": row["city_name"],
            "count": int(row["count"])
        }
        for row in rows
    ]


def get_organization_registration_trend(cursor, filters):
    group_by = (filters.get("group_by") or "daily").lower()

    if group_by not in SUPPORTED_GROUP_BY:
        raise ValueError(
            "group_by must be one of: daily, weekly, monthly, yearly"
        )

    grouping = {
        "daily": ("day", "YYYY-MM-DD"),
        "weekly": ("week", "IYYY-IW"),
        "monthly": ("month", "YYYY-MM"),
        "yearly": ("year", "YYYY")
    }

    period, date_format = grouping[group_by]

    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            TO_CHAR(
                DATE_TRUNC('{period}', o.created_at),
                '{date_format}'
            ) AS period,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY 1
        ORDER BY 1;
    """

    rows = execute_all(cursor, query, params)

    return [
        {
            "period": row["period"],
            "count": int(row["count"])
        }
        for row in rows
    ]


def build_overview_dashboard(cursor, filters):
    total = get_total_organizations(cursor, filters)

    organizations_by_type = get_organizations_by_type(
        cursor,
        filters
    )

    organizations_by_size = get_organizations_by_size(
        cursor,
        filters
    )

    collaborator_distribution = get_collaborator_distribution(
        cursor,
        filters
    )

    contributor_distribution = get_contributor_distribution(
        cursor,
        filters
    )

    non_profit = 0
    for item in organizations_by_type:
        org_type = str(item["org_type"]).lower()

        if org_type in {
            "non-profit",
            "nonprofit",
            "non profit"
        }:
            non_profit += item["count"]

    for_profit = 0
    for item in organizations_by_type:
        org_type = str(item["org_type"]).lower()

        if org_type in {
            "for-profit",
            "for profit",
            "forprofit"
        }:
            for_profit += item["count"]

    collaborator = 0
    non_collaborator = 0

    for item in collaborator_distribution:
        if item["is_collaborator"]:
            collaborator += item["count"]
        else:
            non_collaborator += item["count"]

    return {
        "organization_overview": {
            "summary": {
                "total_organizations": total,
                "non_profit_organizations": non_profit,
                "for_profit_organizations": for_profit,
                "collaborator_organizations": collaborator,
                "non_collaborator_organizations": non_collaborator,
                "contributor_organizations": None,
                "non_contributor_organizations": None
            },
            "organization_activity_trend":
                get_organization_registration_trend(
                    cursor,
                    filters
                ),
            "organizations_by_type":
                organizations_by_type,
            "organizations_by_size":
                organizations_by_size,
            "organizations_by_location":
                get_organizations_by_location(
                    cursor,
                    filters
                ),
            "collaborator_distribution":
                collaborator_distribution,
            "contributor_distribution":
                contributor_distribution
        }
    }


# ----------------------------------------------------------------------
# Organization Performance Dashboard
# ----------------------------------------------------------------------

def get_rating_summary(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            ROUND(
                AVG(o.org_rating)::numeric,
                2
            ) AS average_rating,

            COUNT(*) FILTER (
                WHERE o.org_rating IS NOT NULL
            ) AS rated_organizations,

            COUNT(*) FILTER (
                WHERE o.org_rating IS NULL
            ) AS unrated_organizations,

            COUNT(*) FILTER (
                WHERE o.org_rating = 5
            ) AS five_star_organizations

        FROM {SCHEMA_NAME}.organizations o
        {where_clause};
    """

    row = execute_one(cursor, query, params)

    return {
        "average_rating": (
            float(row["average_rating"])
            if row["average_rating"] is not None
            else 0
        ),
        "rated_organizations":
            int(row["rated_organizations"] or 0),
        "unrated_organizations":
            int(row["unrated_organizations"] or 0),
        "five_star_organizations":
            int(row["five_star_organizations"] or 0)
    }


def get_rating_distribution(cursor, filters):
    where_clause, params = build_filters(filters)

    condition = "o.org_rating IS NOT NULL"

    if where_clause:
        where_clause += f" AND {condition}"
    else:
        where_clause = f"WHERE {condition}"

    query = f"""
        SELECT
            o.org_rating AS rating,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.org_rating
        ORDER BY o.org_rating;
    """

    rows = execute_all(cursor, query, params)

    counts = {
        int(row["rating"]): int(row["count"])
        for row in rows
    }

    return [
        {
            "rating": rating,
            "count": counts.get(rating, 0)
        }
        for rating in range(1, 6)
    ]


def get_top_rated_organizations(cursor, filters):
    where_clause, params = build_filters(filters)

    condition = "o.org_rating IS NOT NULL"

    if where_clause:
        where_clause += f" AND {condition}"
    else:
        where_clause = f"WHERE {condition}"

    query = f"""
        SELECT
            o.org_id,
            o.org_name,
            o.org_type,
            o.org_size,
            o.org_rating,
            o.city_name,
            o.state_id
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        ORDER BY o.org_rating DESC, o.org_name
        LIMIT 10;
    """

    rows = execute_all(cursor, query, params)

    return [dict(row) for row in rows]


def get_organizations_without_ratings(cursor, filters):
    where_clause, params = build_filters(filters)

    condition = "o.org_rating IS NULL"

    if where_clause:
        where_clause += f" AND {condition}"
    else:
        where_clause = f"WHERE {condition}"

    query = f"""
        SELECT
            o.org_id,
            o.org_name,
            o.org_type,
            o.org_size,
            o.city_name,
            o.state_id
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        ORDER BY o.org_name;
    """

    rows = execute_all(cursor, query, params)

    return [dict(row) for row in rows]


def get_top_collaborator_organizations(cursor, filters):
    where_clause, params = build_filters(filters)

    condition = "o.is_collaborator = TRUE"

    if where_clause:
        where_clause += f" AND {condition}"
    else:
        where_clause = f"WHERE {condition}"

    query = f"""
        SELECT
            o.org_id,
            o.org_name,
            o.org_type,
            o.org_size,
            o.org_rating,
            o.city_name,
            o.state_id
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name
        LIMIT 10;
    """

    rows = execute_all(cursor, query, params)

    return [dict(row) for row in rows]


def get_top_contributor_organizations(cursor, filters):
    """
    is_contributor has been added to the task requirements but is not
    yet available in the current database.
    """
    return []


def get_ratings_by_organization_type(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            o.org_type,

            ROUND(
                AVG(o.org_rating)::numeric,
                2
            ) AS average_rating,

            COUNT(*) FILTER (
                WHERE o.org_rating IS NOT NULL
            ) AS rated_organizations

        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.org_type
        ORDER BY average_rating DESC NULLS LAST;
    """

    rows = execute_all(cursor, query, params)

    return [
        {
            "org_type": row["org_type"],
            "average_rating": (
                float(row["average_rating"])
                if row["average_rating"] is not None
                else 0
            ),
            "rated_organizations":
                int(row["rated_organizations"] or 0)
        }
        for row in rows
    ]


def get_ratings_by_organization_size(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            o.org_size,

            ROUND(
                AVG(o.org_rating)::numeric,
                2
            ) AS average_rating,

            COUNT(*) FILTER (
                WHERE o.org_rating IS NOT NULL
            ) AS rated_organizations

        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.org_size
        ORDER BY average_rating DESC NULLS LAST;
    """

    rows = execute_all(cursor, query, params)

    return [
        {
            "org_size": row["org_size"],
            "average_rating": (
                float(row["average_rating"])
                if row["average_rating"] is not None
                else 0
            ),
            "rated_organizations":
                int(row["rated_organizations"] or 0)
        }
        for row in rows
    ]


def build_performance_dashboard(cursor, filters):
    return {
        "organization_performance": {
            "summary":
                get_rating_summary(
                    cursor,
                    filters
                ),

            "rating_distribution":
                get_rating_distribution(
                    cursor,
                    filters
                ),

            "top_rated_organizations":
                get_top_rated_organizations(
                    cursor,
                    filters
                ),

            "organizations_without_ratings":
                get_organizations_without_ratings(
                    cursor,
                    filters
                ),

            "top_collaborator_organizations":
                get_top_collaborator_organizations(
                    cursor,
                    filters
                ),

            "top_contributor_organizations":
                get_top_contributor_organizations(
                    cursor,
                    filters
                ),

            "ratings_by_organization_type":
                get_ratings_by_organization_type(
                    cursor,
                    filters
                ),

            "ratings_by_organization_size":
                get_ratings_by_organization_size(
                    cursor,
                    filters
                )
        }
    }


# ----------------------------------------------------------------------
# Lambda Handler
# ----------------------------------------------------------------------

def lambda_handler(event, context):
    event = event or {}

    dashboard_type = (
        event.get("dashboard_type", "overview")
        .strip()
        .lower()
    )

    if dashboard_type not in {
        "overview",
        "performance"
    }:
        return build_response(
            400,
            {
                "error":
                    "dashboard_type must be overview or performance"
            }
        )

    filters = {
        "time_filter":
            event.get("time_filter", "ALL"),

        "start_date":
            event.get("start_date"),

        "end_date":
            event.get("end_date"),

        "org_type":
            event.get("org_type"),

        "org_size":
            event.get("org_size"),

        "state_id":
            event.get("state_id"),

        "city_name":
            event.get("city_name"),

        "org_rating":
            event.get("org_rating"),

        "is_collaborator":
            event.get("is_collaborator"),

        "is_contributor":
            event.get("is_contributor"),

        "group_by":
            event.get("group_by", "daily")
    }

    conn = None
    cursor = None

    try:
        # Validate filters before opening the database connection.
        build_filters(filters)

        conn = get_db_connection()

        cursor = conn.cursor(
            cursor_factory=RealDictCursor
        )

        if dashboard_type == "overview":
            response_body = build_overview_dashboard(
                cursor,
                filters
            )
        else:
            response_body = build_performance_dashboard(
                cursor,
                filters
            )

        return build_response(
            200,
            response_body
        )

    except ValueError as exc:
        return build_response(
            400,
            {
                "error": str(exc)
            }
        )

    except Exception as exc:
        print(
            f"Organization analytics failed: {exc}"
        )

        return build_response(
            500,
            {
                "error":
                    "Unable to retrieve organization analytics"
            }
        )

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


if __name__ == "__main__":
    result = lambda_handler(
        {
            "dashboard_type": "overview",
            "time_filter": "30D",
            "group_by": "daily"
        },
        None
    )

    print(
        json.dumps(
            result,
            indent=2
        )
    )