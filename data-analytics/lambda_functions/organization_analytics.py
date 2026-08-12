import json
import os

import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"


GROUP_BY_MAP = {
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
    "yearly": "year"
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
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", "5432")
    )


def get_event_body(event):
    if not event:
        return {}

    if "body" in event:
        body = event.get("body")

        if isinstance(body, str):
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {}

        if isinstance(body, dict):
            return body

    return event


def build_filters(filters, include_rating=True):
    conditions = []
    params = []

    time_filter = filters.get("time_filter", "ALL")

    if time_filter == "7D":
        conditions.append(
            "o.created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'"
        )

    elif time_filter == "30D":
        conditions.append(
            "o.created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'"
        )

    elif time_filter == "1Y":
        conditions.append(
            "o.created_at >= CURRENT_TIMESTAMP - INTERVAL '1 year'"
        )

    elif time_filter == "CUSTOM":
        start_date = filters.get("start_date")
        end_date = filters.get("end_date")

        if start_date:
            conditions.append("o.created_at >= %s")
            params.append(start_date)

        if end_date:
            conditions.append("o.created_at <= %s")
            params.append(end_date)

    org_type = filters.get("org_type")
    if org_type:
        conditions.append("o.org_type = %s")
        params.append(org_type)

    org_size = filters.get("org_size")
    if org_size:
        conditions.append("o.org_size = %s")
        params.append(org_size)

    state_id = filters.get("state_id")
    if state_id:
        conditions.append("o.state_id = %s")
        params.append(state_id)

    city_name = filters.get("city_name")
    if city_name:
        conditions.append("o.city_name = %s")
        params.append(city_name)

    if include_rating and filters.get("org_rating") is not None:
        conditions.append("o.org_rating = %s")
        params.append(filters["org_rating"])

    if filters.get("is_collaborator") is not None:
        conditions.append("o.is_collaborator = %s")
        params.append(filters["is_collaborator"])

    # Keep this only if the target DB already has is_contributor.
    if filters.get("is_contributor") is not None:
        conditions.append("o.is_contributor = %s")
        params.append(filters["is_contributor"])

    where_clause = ""

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    return where_clause, params


# ----------------------------
# OVERVIEW DASHBOARD
# ----------------------------

def fetch_overview_summary(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            COUNT(*) AS total_organizations,

            COUNT(*) FILTER (
                WHERE LOWER(o.org_type) = 'non-profit'
            ) AS non_profit_organizations,

            COUNT(*) FILTER (
                WHERE LOWER(o.org_type) = 'for-profit'
            ) AS for_profit_organizations,

            COUNT(*) FILTER (
                WHERE o.is_collaborator = TRUE
            ) AS collaborator_organizations,

            COUNT(*) FILTER (
                WHERE o.is_collaborator = FALSE
            ) AS non_collaborator_organizations,

            COUNT(*) FILTER (
                WHERE o.is_contributor = TRUE
            ) AS contributor_organizations,

            COUNT(*) FILTER (
                WHERE o.is_contributor = FALSE
            ) AS non_contributor_organizations

        FROM {SCHEMA_NAME}.organizations o
        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    return {
        "total_organizations": int(row["total_organizations"] or 0),
        "non_profit_organizations": int(row["non_profit_organizations"] or 0),
        "for_profit_organizations": int(row["for_profit_organizations"] or 0),
        "collaborator_organizations": int(row["collaborator_organizations"] or 0),
        "non_collaborator_organizations": int(row["non_collaborator_organizations"] or 0),
        "contributor_organizations": int(row["contributor_organizations"] or 0),
        "non_contributor_organizations": int(row["non_contributor_organizations"] or 0)
    }


def fetch_organizations_by_type(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            o.org_type AS organization_type,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.org_type
        ORDER BY count DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "organization_type": row["organization_type"],
            "count": int(row["count"])
        }
        for row in rows
    ]


def fetch_organizations_by_size(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            o.org_size AS organization_size,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.org_size
        ORDER BY count DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "organization_size": row["organization_size"],
            "count": int(row["count"])
        }
        for row in rows
    ]


def fetch_collaborator_distribution(cursor, filters):
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

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "is_collaborator": row["is_collaborator"],
            "count": int(row["count"])
        }
        for row in rows
    ]


def fetch_contributor_distribution(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            o.is_contributor,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.is_contributor
        ORDER BY o.is_contributor DESC;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "is_contributor": row["is_contributor"],
            "count": int(row["count"])
        }
        for row in rows
    ]


def fetch_organizations_by_location(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            o.state_id,
            s.state_name,
            o.city_name,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s
            ON o.state_id = s.state_id
        {where_clause}
        GROUP BY
            o.state_id,
            s.state_name,
            o.city_name
        ORDER BY count DESC;
    """

    cursor.execute(query, params)
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


def fetch_organization_activity_trend(cursor, filters):
    group_by = filters.get("group_by", "daily")
    interval = GROUP_BY_MAP.get(group_by, "day")

    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            DATE_TRUNC('{interval}', o.created_at) AS period,
            COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY period
        ORDER BY period;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "period": row["period"],
            "count": int(row["count"])
        }
        for row in rows
    ]


# ----------------------------
# PERFORMANCE DASHBOARD
# ----------------------------

def fetch_performance_summary(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,

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

    cursor.execute(query, params)
    row = cursor.fetchone()

    return {
        "average_rating": (
            float(row["average_rating"])
            if row["average_rating"] is not None
            else 0
        ),
        "rated_organizations": int(row["rated_organizations"] or 0),
        "unrated_organizations": int(row["unrated_organizations"] or 0),
        "five_star_organizations": int(row["five_star_organizations"] or 0)
    }


def fetch_rating_distribution(cursor, filters):
    where_clause, params = build_filters(filters)

    rating_condition = "o.org_rating IS NOT NULL"

    if where_clause:
        where_clause += f" AND {rating_condition}"
    else:
        where_clause = f"WHERE {rating_condition}"

    query = f"""
        SELECT
            o.org_rating AS rating,
            COUNT(*) AS count
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
    where_clause, params = build_filters(filters)

    rating_condition = "o.org_rating IS NOT NULL"

    if where_clause:
        where_clause += f" AND {rating_condition}"
    else:
        where_clause = f"WHERE {rating_condition}"

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
        ORDER BY
            o.org_rating DESC,
            o.org_name
        LIMIT 10;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "org_type": row["org_type"],
            "org_size": row["org_size"],
            "org_rating": row["org_rating"],
            "city_name": row["city_name"],
            "state_id": row["state_id"]
        }
        for row in rows
    ]


def fetch_top_collaborator_organizations(cursor, filters):
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
            o.org_rating,
            o.org_type,
            o.org_size
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        ORDER BY
            o.org_rating DESC NULLS LAST,
            o.org_name
        LIMIT 10;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [dict(row) for row in rows]


def fetch_top_contributor_organizations(cursor, filters):
    where_clause, params = build_filters(filters)

    condition = "o.is_contributor = TRUE"

    if where_clause:
        where_clause += f" AND {condition}"
    else:
        where_clause = f"WHERE {condition}"

    query = f"""
        SELECT
            o.org_id,
            o.org_name,
            o.org_rating,
            o.org_type,
            o.org_size
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        ORDER BY
            o.org_rating DESC NULLS LAST,
            o.org_name
        LIMIT 10;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [dict(row) for row in rows]


def fetch_ratings_by_organization_type(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            o.org_type AS organization_type,
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(*) FILTER (
                WHERE o.org_rating IS NOT NULL
            ) AS rated_organizations
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.org_type
        ORDER BY average_rating DESC NULLS LAST;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "organization_type": row["organization_type"],
            "average_rating": (
                float(row["average_rating"])
                if row["average_rating"] is not None
                else 0
            ),
            "rated_organizations": int(row["rated_organizations"])
        }
        for row in rows
    ]


def fetch_ratings_by_organization_size(cursor, filters):
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            o.org_size AS organization_size,
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(*) FILTER (
                WHERE o.org_rating IS NOT NULL
            ) AS rated_organizations
        FROM {SCHEMA_NAME}.organizations o
        {where_clause}
        GROUP BY o.org_size
        ORDER BY average_rating DESC NULLS LAST;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [
        {
            "organization_size": row["organization_size"],
            "average_rating": (
                float(row["average_rating"])
                if row["average_rating"] is not None
                else 0
            ),
            "rated_organizations": int(row["rated_organizations"])
        }
        for row in rows
    ]


# ----------------------------
# DASHBOARD BUILDERS
# ----------------------------

def build_overview_dashboard(cursor, filters):
    return {
        "organization_overview": {
            "summary": fetch_overview_summary(cursor, filters),
            "organization_activity_trend": fetch_organization_activity_trend(
                cursor,
                filters
            ),
            "organizations_by_type": fetch_organizations_by_type(
                cursor,
                filters
            ),
            "organizations_by_size": fetch_organizations_by_size(
                cursor,
                filters
            ),
            "organizations_by_location": fetch_organizations_by_location(
                cursor,
                filters
            ),
            "collaborator_distribution": fetch_collaborator_distribution(
                cursor,
                filters
            ),
            "contributor_distribution": fetch_contributor_distribution(
                cursor,
                filters
            )
        }
    }


def build_performance_dashboard(cursor, filters):
    return {
        "organization_performance": {
            "summary": fetch_performance_summary(cursor, filters),
            "rating_distribution": fetch_rating_distribution(
                cursor,
                filters
            ),
            "top_rated_organizations": fetch_top_rated_organizations(
                cursor,
                filters
            ),
            "top_collaborator_organizations":
                fetch_top_collaborator_organizations(
                    cursor,
                    filters
                ),
            "top_contributor_organizations":
                fetch_top_contributor_organizations(
                    cursor,
                    filters
                ),
            "ratings_by_organization_type":
                fetch_ratings_by_organization_type(
                    cursor,
                    filters
                ),
            "ratings_by_organization_size":
                fetch_ratings_by_organization_size(
                    cursor,
                    filters
                )
        }
    }


def lambda_handler(event, context):
    conn = None
    cursor = None

    try:
        body = get_event_body(event)

        dashboard_type = body.get(
            "dashboard_type",
            "overview"
        )

        if dashboard_type not in {"overview", "performance"}:
            return build_response(
                400,
                {
                    "error": (
                        "dashboard_type must be "
                        "'overview' or 'performance'"
                    )
                }
            )

        conn = get_db_connection()
        cursor = conn.cursor(
            cursor_factory=RealDictCursor
        )

        if dashboard_type == "overview":
            response_body = build_overview_dashboard(
                cursor,
                body
            )
        else:
            response_body = build_performance_dashboard(
                cursor,
                body
            )

        return build_response(
            200,
            response_body
        )

    except Exception as error:
        print(
            f"Organization analytics API failed: {error}"
        )

        return build_response(
            500,
            {
                "error": "Internal Server Error"
            }
        )

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


if __name__ == "__main__":
    event = {
        "dashboard_type": "overview",
        "time_filter": "ALL",
        "state_id": "CA",
        "group_by": "monthly"
    }

    result = lambda_handler(event, None)

    print(json.dumps(json.loads(result["body"]), indent=2))