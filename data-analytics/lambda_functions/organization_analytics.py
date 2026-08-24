import json
import logging
import os

import psycopg2
from psycopg2.extras import RealDictCursor

# Setup Logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_db_connection():
    """Establish local PostgreSQL database connection with environment fallbacks."""
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            database=os.environ.get("DB_NAME", "saayam_db"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", "postgres"),
            port=os.environ.get("DB_PORT", "5432"),
        )
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        raise e


def build_where_clause(filters):
    """Build dynamic WHERE clause and parameters based on updated common filter payload."""
    conditions = []
    params = {}

    # 1. Time Filter Handling
    time_filter = filters.get("time_filter", "30D")
    start_date = filters.get("start_date")
    end_date = filters.get("end_date")

    if time_filter == "7D":
        conditions.append("o.created_at >= CURRENT_DATE - INTERVAL '7 days'")
    elif time_filter == "30D":
        conditions.append("o.created_at >= CURRENT_DATE - INTERVAL '30 days'")
    elif time_filter == "1Y":
        conditions.append("o.created_at >= CURRENT_DATE - INTERVAL '1 year'")
    elif time_filter == "CUSTOM" and start_date and end_date:
        conditions.append(
            "o.created_at BETWEEN %(start_date)s::timestamp AND %(end_date)s::timestamp"
        )
        params["start_date"] = start_date
        params["end_date"] = end_date

    # 2. Region / State Filter
    region = filters.get("region")
    if region and region.upper() != "ALL":
        conditions.append("(s.state_name = %(region)s OR s.id = %(region)s)")
        params["region"] = region

    # 3. Organization Type Filter
    org_type = filters.get("organization_type")
    if org_type and org_type.upper() != "ALL":
        conditions.append("LOWER(o.org_type) = LOWER(%(org_type)s)")
        params["org_type"] = org_type

    where_sql = " WHERE " + " AND ".join(conditions) if conditions else ""
    return where_sql, params


def get_trunc_unit(group_by):
    """Map group_by string to PostgreSQL DATE_TRUNC unit and format."""
    group_by = (group_by or "daily").lower()
    if group_by == "weekly":
        return "week", "YYYY-IW"
    elif group_by == "monthly":
        return "month", "YYYY-MM"
    elif group_by == "yearly":
        return "year", "YYYY"
    else:
        return "day", "YYYY-MM-DD"


def fetch_organization_analytics(cursor, where_sql, params, group_by):
    """Fetch all metrics across tabs in a single structured JSON response."""
    trunc_unit, date_format = get_trunc_unit(group_by)

    # 1. KPI Summary Cards
    summary_query = f"""
        SELECT 
            COUNT(o.id) AS total_organizations,
            COUNT(CASE WHEN o.is_collaborator = TRUE THEN 1 END) AS total_collaborators,
            COUNT(CASE WHEN o.is_contributor = TRUE THEN 1 END) AS total_contributors,
            ROUND(COALESCE(AVG(o.rating), 0)::numeric, 1) AS average_org_rating
        FROM organizations o
        LEFT JOIN states s ON o.state_id = s.id
        {where_sql};
    """
    cursor.execute(summary_query, params)
    summary = cursor.fetchone() or {
        "total_organizations": 0,
        "total_collaborators": 0,
        "total_contributors": 0,
        "average_org_rating": 0.0,
    }

    # Cast numeric average rating safely
    if summary.get("average_org_rating") is not None:
        summary["average_org_rating"] = float(summary["average_org_rating"])

    # 2. Growth Trend (Line Chart: Total Organizations vs Total Collaborators)
    growth_query = f"""
        SELECT 
            TO_CHAR(DATE_TRUNC('{trunc_unit}', o.created_at), '{date_format}') AS period,
            COUNT(o.id) AS total_organizations,
            COUNT(CASE WHEN o.is_collaborator = TRUE THEN 1 END) AS total_collaborators
        FROM organizations o
        LEFT JOIN states s ON o.state_id = s.id
        {where_sql}
        GROUP BY 1
        ORDER BY 1 ASC;
    """
    cursor.execute(growth_query, params)
    growth_trend = cursor.fetchall() or []

    # 3. Organizations by Location (with percentage calculation)
    location_query = f"""
        WITH total_count AS (
            SELECT COUNT(o.id) AS grand_total 
            FROM organizations o 
            LEFT JOIN states s ON o.state_id = s.id 
            {where_sql}
        )
        SELECT 
            COALESCE(s.id, 'UNKNOWN') AS state_id,
            COALESCE(s.state_name, 'Unknown') AS state_name,
            COUNT(o.id) AS organization_count,
            ROUND(
                (COUNT(o.id)::numeric / NULLIF((SELECT grand_total FROM total_count), 0)) * 100, 1
            ) AS percentage
        FROM organizations o
        LEFT JOIN states s ON o.state_id = s.id
        {where_sql}
        GROUP BY s.id, s.state_name
        ORDER BY organization_count DESC;
    """
    cursor.execute(location_query, params)
    locations = cursor.fetchall() or []
    for loc in locations:
        if loc.get("percentage") is not None:
            loc["percentage"] = float(loc["percentage"])

    # 4. Organizations by Size
    size_query = f"""
        SELECT 
            LOWER(COALESCE(o.org_size, 'unknown')) AS org_size,
            COUNT(o.id) AS organization_count
        FROM organizations o
        LEFT JOIN states s ON o.state_id = s.id
        {where_sql}
        GROUP BY 1
        ORDER BY organization_count DESC;
    """
    cursor.execute(size_query, params)
    by_size = cursor.fetchall() or []

    # 5. Collaborator vs Contributor
    collab_contrib_query = f"""
        WITH total_count AS (
            SELECT COUNT(o.id) AS grand_total 
            FROM organizations o 
            LEFT JOIN states s ON o.state_id = s.id 
            {where_sql}
        )
        SELECT 
            'collaborator' AS type,
            COUNT(CASE WHEN o.is_collaborator = TRUE THEN 1 END) AS organization_count,
            ROUND(
                (COUNT(CASE WHEN o.is_collaborator = TRUE THEN 1 END)::numeric / NULLIF((SELECT grand_total FROM total_count), 0)) * 100, 1
            ) AS percentage
        FROM organizations o
        LEFT JOIN states s ON o.state_id = s.id
        {where_sql}
        UNION ALL
        SELECT 
            'contributor' AS type,
            COUNT(CASE WHEN o.is_contributor = TRUE THEN 1 END) AS organization_count,
            ROUND(
                (COUNT(CASE WHEN o.is_contributor = TRUE THEN 1 END)::numeric / NULLIF((SELECT grand_total FROM total_count), 0)) * 100, 1
            ) AS percentage
        FROM organizations o
        LEFT JOIN states s ON o.state_id = s.id
        {where_sql};
    """
    cursor.execute(collab_contrib_query, params)
    collab_vs_contrib = cursor.fetchall() or []
    for item in collab_vs_contrib:
        if item.get("percentage") is not None:
            item["percentage"] = float(item["percentage"])

    # 6. Rating Distribution (1 to 5 Stars, ignoring NULLs)
    rating_query = f"""
        SELECT 
            o.rating,
            COUNT(o.id) AS organization_count
        FROM organizations o
        LEFT JOIN states s ON o.state_id = s.id
        {where_sql} AND o.rating IS NOT NULL
        GROUP BY o.rating
        ORDER BY o.rating ASC;
    """
    cursor.execute(rating_query, params)
    rating_dist = cursor.fetchall() or []

    # 7. For-Profit vs Non-Profit Distribution (Stacked Bar Chart over time)
    type_dist_query = f"""
        SELECT 
            TO_CHAR(DATE_TRUNC('{trunc_unit}', o.created_at), '{date_format}') AS period,
            COUNT(CASE WHEN LOWER(o.org_type) IN ('for_profit', 'for-profit') THEN 1 END) AS for_profit,
            COUNT(CASE WHEN LOWER(o.org_type) IN ('non_profit', 'non-profit') THEN 1 END) AS non_profit,
            COUNT(o.id) AS total
        FROM organizations o
        LEFT JOIN states s ON o.state_id = s.id
        {where_sql}
        GROUP BY 1
        ORDER BY 1 ASC;
    """
    cursor.execute(type_dist_query, params)
    type_distribution = cursor.fetchall() or []

    return {
        "summary": summary,
        "growth_trend": growth_trend,
        "organizations_by_location": locations,
        "organizations_by_size": by_size,
        "collaborator_vs_contributor": collab_vs_contrib,
        "rating_distribution": rating_dist,
        "organization_type_distribution": type_distribution,
    }


def lambda_handler(event, context):
    """Main Lambda Handler for Organization Analytics API."""
    try:
        payload = {}
        if event.get("body"):
            payload = (
                json.loads(event["body"])
                if isinstance(event["body"], str)
                else event["body"]
            )
        else:
            payload = event

        group_by = payload.get("group_by", "daily")

        where_sql, params = build_where_clause(payload)

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        response_data = fetch_organization_analytics(
            cursor, where_sql, params, group_by
        )

        cursor.close()
        conn.close()

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(response_data, default=str),
        }

    except psycopg2.Error as db_err:
        logger.error(f"Database Query Error: {str(db_err)}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {"error_code": "DE 1001", "message": "Database query failed."}
            ),
        }
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "error_code": "DE 1000",
                    "message": "Internal server execution error.",
                }
            ),
        }