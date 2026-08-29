import json
import os

import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = os.getenv(
    "DB_SCHEMA",
    "virginia_dev_saayam_rdbms"
)
ORGANIZATIONS_TABLE = f"{SCHEMA_NAME}.organizations"
STATE_TABLE = f"{SCHEMA_NAME}.state"


def parse_event_body(event):
    """Parse the Lambda event body into a dictionary."""
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


def get_db_connection():
    """Create and return a local PostgreSQL connection."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "saayam_local"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", "5432"),
    )


def build_response(status_code, body):
    """Build a standard Lambda HTTP response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def get_grouping(group_by):
    """Return PostgreSQL grouping and date formats."""
    if group_by == "daily":
        return "day", "YYYY-MM-DD"
    if group_by == "weekly":
        return "week", "YYYY-MM-DD"
    if group_by == "monthly":
        return "month", "YYYY-MM"
    if group_by == "yearly":
        return "year", "YYYY"

    raise ValueError("group_by must be daily, weekly, monthly, or yearly")


def build_filters(filters):
    """Build SQL WHERE clauses and parameters from dashboard filters."""
    clauses = []
    params = []

    time_filter = filters.get("time_filter", "30D")

    if time_filter == "7D":
        clauses.append("o.created_at >= CURRENT_DATE - INTERVAL '7 days'")
    elif time_filter == "30D":
        clauses.append("o.created_at >= CURRENT_DATE - INTERVAL '30 days'")
    elif time_filter == "1Y":
        clauses.append("o.created_at >= CURRENT_DATE - INTERVAL '1 year'")
    elif time_filter == "CUSTOM":
        start_date = filters.get("start_date")
        end_date = filters.get("end_date")

        if not start_date or not end_date:
            raise ValueError(
                "start_date and end_date are required for CUSTOM time_filter"
            )

        clauses.append("o.created_at >= %s")
        params.append(start_date)
        clauses.append("o.created_at < %s::date + INTERVAL '1 day'")
        params.append(end_date)
    elif time_filter == "ALL":
        pass
    else:
        raise ValueError("Invalid time_filter")

    optional_filters = [
        ("org_type", "o.org_type"),
        ("org_size", "o.org_size"),
        ("state_id", "o.state_id"),
        ("city_name", "o.city_name"),
        ("org_rating", "o.org_rating"),
        ("is_collaborator", "o.is_collaborator"),
        ("is_contributor", "o.is_contributor"),
    ]

    for key, column in optional_filters:
        value = filters.get(key)
        if value is not None:
            clauses.append(f"{column} = %s")
            params.append(value)

    where_clause = "WHERE " + " AND ".join(clauses) if clauses else ""

    return where_clause, params


def fetch_overview_summary(cursor, filters):
    """Fetch summary metrics for the organization overview dashboard."""
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE org_type = 'Non-Profit') AS non_profit_organizations,
            COUNT(*) FILTER (WHERE org_type = 'For-profit') AS for_profit_organizations,
            COUNT(*) FILTER (WHERE is_collaborator = TRUE) AS collaborator_organizations,
            COUNT(*) FILTER (WHERE is_collaborator = FALSE) AS non_collaborator_organizations,
            COUNT(*) FILTER (WHERE is_contributor = TRUE) AS contributor_organizations,
            COUNT(*) FILTER (WHERE is_contributor = FALSE) AS non_contributor_organizations
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause};
    """

    cursor.execute(query, params)
    row = cursor.fetchone()

    return dict(row)


def fetch_organizations_by_type(cursor, filters):
    """Fetch organization counts grouped by organization type."""
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            org_type,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause}
        GROUP BY org_type
        ORDER BY count DESC;
    """

    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def fetch_organizations_by_size(cursor, filters):
    """Fetch organization counts grouped by organization size."""
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            org_size,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause}
        GROUP BY org_size
        ORDER BY count DESC;
    """

    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def fetch_collaborator_distribution(cursor, filters):
    """Fetch collaborator and non-collaborator organization counts."""
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            is_collaborator,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause}
        GROUP BY is_collaborator
        ORDER BY is_collaborator DESC;
    """

    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def fetch_contributor_distribution(cursor, filters):
    """Fetch contributor and non-contributor organization counts."""
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            is_contributor,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause}
        GROUP BY is_contributor
        ORDER BY is_contributor DESC;
    """

    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def fetch_organizations_by_location(cursor, filters):
    """Fetch organization counts grouped by state and city."""
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            o.state_id,
            s.state_name,
            o.city_name,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        LEFT JOIN {STATE_TABLE} s
            ON o.state_id = s.state_id
        {where_clause}
        GROUP BY o.state_id, s.state_name, o.city_name
        ORDER BY count DESC;
    """

    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def fetch_organization_activity_trend(cursor, filters):
    """Fetch organization registration trends for the selected grouping."""
    period, date_format = get_grouping(filters.get("group_by", "daily"))
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause}
        GROUP BY 1
        ORDER BY 1;
    """

    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def get_organization_overview(cursor, filters):
    """Build the complete organization overview response."""
    return {
        "organization_overview": {
            "summary": fetch_overview_summary(cursor, filters),
            "organization_activity_trend": fetch_organization_activity_trend(
                cursor, filters
            ),
            "organizations_by_type": fetch_organizations_by_type(cursor, filters),
            "organizations_by_size": fetch_organizations_by_size(cursor, filters),
            "organizations_by_location": fetch_organizations_by_location(
                cursor, filters
            ),
            "collaborator_distribution": fetch_collaborator_distribution(
                cursor, filters
            ),
            "contributor_distribution": fetch_contributor_distribution(
                cursor, filters
            ),
        }
    }


def fetch_performance_summary(cursor, filters):
    """Fetch summary metrics for the organization performance dashboard."""
    where_clause, params = build_filters(filters)

    query = f"""
        SELECT
            ROUND(AVG(org_rating)::numeric, 2) AS average_rating,
            COUNT(*) FILTER (WHERE org_rating IS NOT NULL) AS rated_organizations,
            COUNT(*) FILTER (WHERE org_rating IS NULL) AS unrated_organizations,
            COUNT(*) FILTER (WHERE org_rating = 5) AS five_star_organizations
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause};
    """

    cursor.execute(query, params)
    return dict(cursor.fetchone())


def fetch_rating_distribution(cursor, filters):
    """Fetch organization counts grouped by rating."""
    where_clause, params = build_filters(filters)

    condition = (
        f"{where_clause} AND org_rating IS NOT NULL"
        if where_clause
        else "WHERE org_rating IS NOT NULL"
    )

    query = f"""
        SELECT
            org_rating,
            COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {condition}
        GROUP BY org_rating
        ORDER BY org_rating;
    """

    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def fetch_top_rated_organizations(cursor, filters):
    """Fetch the top-rated organizations."""
    where_clause, params = build_filters(filters)

    condition = (
        f"{where_clause} AND org_rating IS NOT NULL"
        if where_clause
        else "WHERE org_rating IS NOT NULL"
    )

    query = f"""
        SELECT
            org_id,
            org_name,
            org_type,
            org_size,
            org_rating
        FROM {ORGANIZATIONS_TABLE} o
        {condition}
        ORDER BY org_rating DESC, org_name
        LIMIT 10;
    """

    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def fetch_top_collaborator_organizations(cursor, filters):
    """Fetch the highest-rated collaborator organizations."""
    where_clause, params = build_filters(filters)

    condition = (
        f"{where_clause} AND is_collaborator = TRUE"
        if where_clause
        else "WHERE is_collaborator = TRUE"
    )

    query = f"""
        SELECT
            org_id,
            org_name,
            org_type,
            org_size,
            org_rating
        FROM {ORGANIZATIONS_TABLE} o
        {condition}
        ORDER BY org_rating DESC NULLS LAST, org_name
        LIMIT 10;
    """

    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def fetch_top_contributor_organizations(cursor, filters):
    """Fetch the highest-rated contributor organizations."""
    where_clause, params = build_filters(filters)

    condition = (
        f"{where_clause} AND is_contributor = TRUE"
        if where_clause
        else "WHERE is_contributor = TRUE"
    )

    query = f"""
        SELECT
            org_id,
            org_name,
            org_type,
            org_size,
            org_rating
        FROM {ORGANIZATIONS_TABLE} o
        {condition}
        ORDER BY org_rating DESC NULLS LAST, org_name
        LIMIT 10;
    """

    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def fetch_ratings_by_organization_type(cursor, filters):
    """Fetch average ratings grouped by organization type."""
    where_clause, params = build_filters(filters)

    condition = (
        f"{where_clause} AND org_rating IS NOT NULL"
        if where_clause
        else "WHERE org_rating IS NOT NULL"
    )

    query = f"""
        SELECT
            org_type,
            ROUND(AVG(org_rating)::numeric, 2) AS average_rating,
            COUNT(*) AS rated_organizations
        FROM {ORGANIZATIONS_TABLE} o
        {condition}
        GROUP BY org_type
        ORDER BY org_type;
    """

    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def fetch_ratings_by_organization_size(cursor, filters):
    """Fetch average ratings grouped by organization size."""
    where_clause, params = build_filters(filters)

    condition = (
        f"{where_clause} AND org_rating IS NOT NULL"
        if where_clause
        else "WHERE org_rating IS NOT NULL"
    )

    query = f"""
        SELECT
            org_size,
            ROUND(AVG(org_rating)::numeric, 2) AS average_rating,
            COUNT(*) AS rated_organizations
        FROM {ORGANIZATIONS_TABLE} o
        {condition}
        GROUP BY org_size
        ORDER BY org_size;
    """

    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def get_organization_performance(cursor, filters):
    """Build the complete organization performance response."""
    return {
        "organization_performance": {
            "summary": fetch_performance_summary(cursor, filters),
            "rating_distribution": fetch_rating_distribution(cursor, filters),
            "top_rated_organizations": fetch_top_rated_organizations(
                cursor, filters
            ),
            "top_collaborator_organizations": fetch_top_collaborator_organizations(
                cursor, filters
            ),
            "top_contributor_organizations": fetch_top_contributor_organizations(
                cursor, filters
            ),
            "ratings_by_organization_type": fetch_ratings_by_organization_type(
                cursor, filters
            ),
            "ratings_by_organization_size": fetch_ratings_by_organization_size(
                cursor, filters
            ),
        }
    }


def lambda_handler(event, context):
    """Handle organization analytics dashboard requests."""
    conn = None
    cursor = None

    try:
        request_body = parse_event_body(event)
        dashboard_type = request_body.get("dashboard_type", "overview")

        filters = {
            "time_filter": request_body.get("time_filter", "30D"),
            "start_date": request_body.get("start_date"),
            "end_date": request_body.get("end_date"),
            "org_type": request_body.get("org_type"),
            "org_size": request_body.get("org_size"),
            "state_id": request_body.get("state_id"),
            "city_name": request_body.get("city_name"),
            "org_rating": request_body.get("org_rating"),
            "is_collaborator": request_body.get("is_collaborator"),
            "is_contributor": request_body.get("is_contributor"),
            "group_by": request_body.get("group_by", "daily"),
        }

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if dashboard_type == "overview":
            response_body = get_organization_overview(cursor, filters)
        elif dashboard_type == "performance":
            response_body = get_organization_performance(cursor, filters)
        else:
            return build_response(
                400,
                {"error": "dashboard_type must be 'overview' or 'performance'"},
            )

        return build_response(200, response_body)

    except ValueError as exc:
        return build_response(400, {"error": str(exc)})

    except Exception as exc:
        print("ERROR:", str(exc))
        return build_response(500, {"error": "Internal server error"})

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    test_event = {
    "body": json.dumps({
        "dashboard_type": "performance",
        "time_filter": "ALL"
    })
}

    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))
