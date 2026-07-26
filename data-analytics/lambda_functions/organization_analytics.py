import json
import logging
import os
import re

import psycopg2
from psycopg2.extras import RealDictCursor

# Setup Logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_db_connection():
    """Establish PostgreSQL database connection with environment fallbacks."""
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
    """Build dynamic WHERE clause and parameters based on filters payload."""
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
        conditions.append("o.created_at BETWEEN %(start_date)s AND %(end_date)s")
        params["start_date"] = start_date
        params["end_date"] = end_date

    # 2. Dynamic Attribute Filters
    if filters.get("org_type"):
        conditions.append("o.org_type = %(org_type)s")
        params["org_type"] = filters["org_type"]

    if filters.get("org_size"):
        conditions.append("o.org_size = %(org_size)s")
        params["org_size"] = filters["org_size"]

    if filters.get("state_id"):
        conditions.append("o.state_id = %(state_id)s")
        params["state_id"] = filters["state_id"]

    if filters.get("city_name"):
        conditions.append("o.city_name = %(city_name)s")
        params["city_name"] = filters["city_name"]

    if filters.get("org_rating") is not None:
        conditions.append("o.rating = %(org_rating)s")
        params["org_rating"] = filters["org_rating"]

    if filters.get("is_collaborator") is not None:
        conditions.append("o.is_collaborator = %(is_collaborator)s")
        params["is_collaborator"] = filters["is_collaborator"]

    if filters.get("is_contributor") is not None:
        conditions.append("o.is_contributor = %(is_contributor)s")
        params["is_contributor"] = filters["is_contributor"]

    where_sql = " WHERE " + " AND ".join(conditions) if conditions else ""
    return where_sql, params


def fetch_overview_dashboard(cursor, where_sql, params, group_by):
    """Generate Overview Dashboard Metrics."""
    # Summary Query
    summary_query = f"""
        SELECT 
            COUNT(o.id) AS total_organizations,
            COUNT(CASE WHEN LOWER(o.org_type) = 'non-profit' THEN 1 END) AS non_profit_organizations,
            COUNT(CASE WHEN LOWER(o.org_type) = 'for-profit' THEN 1 END) AS for_profit_organizations,
            COUNT(CASE WHEN o.is_collaborator = TRUE THEN 1 END) AS collaborator_organizations,
            COUNT(CASE WHEN o.is_collaborator = FALSE OR o.is_collaborator IS NULL THEN 1 END) AS non_collaborator_organizations,
            COUNT(CASE WHEN o.is_contributor = TRUE THEN 1 END) AS contributor_organizations,
            COUNT(CASE WHEN o.is_contributor = FALSE OR o.is_contributor IS NULL THEN 1 END) AS non_contributor_organizations
        FROM organizations o
        {where_sql};
    """
    cursor.execute(summary_query, params)
    summary = cursor.fetchone() or {}

    # Registration Trend Query
    trunc_unit = (
        "day"
        if group_by == "daily"
        else (
            "week"
            if group_by == "weekly"
            else "year" if group_by == "yearly" else "month"
        )
    )

    trend_query = f"""
        SELECT 
            TO_CHAR(DATE_TRUNC('{trunc_unit}', o.created_at), 'YYYY-MM-DD') AS period,
            COUNT(o.id) AS count
        FROM organizations o
        {where_sql}
        GROUP BY 1
        ORDER BY 1 ASC;
    """
    cursor.execute(trend_query, params)
    activity_trend = cursor.fetchall()

    # Organizations by Type
    type_query = f"""
        SELECT o.org_type AS type, COUNT(o.id) AS count
        FROM organizations o
        {where_sql}
        GROUP BY o.org_type;
    """
    cursor.execute(type_query, params)
    by_type = cursor.fetchall()

    # Organizations by Size
    size_query = f"""
        SELECT o.org_size AS size, COUNT(o.id) AS count
        FROM organizations o
        {where_sql}
        GROUP BY o.org_size;
    """
    cursor.execute(size_query, params)
    by_size = cursor.fetchall()

    # Organizations by Location
    location_query = f"""
        SELECT 
            s.state_name AS state,
            o.city_name AS city,
            COUNT(o.id) AS count
        FROM organizations o
        LEFT JOIN state s ON o.state_id = s.id
        {where_sql}
        GROUP BY s.state_name, o.city_name;
    """
    cursor.execute(location_query, params)
    by_location = cursor.fetchall()

    # Collaborator Distribution
    collab_query = f"""
        SELECT 
            CASE WHEN o.is_collaborator = TRUE THEN 'collaborator' ELSE 'non_collaborator' END AS status,
            COUNT(o.id) AS count
        FROM organizations o
        {where_sql}
        GROUP BY 1;
    """
    cursor.execute(collab_query, params)
    collab_dist = cursor.fetchall()

    # Contributor Distribution
    contrib_query = f"""
        SELECT 
            CASE WHEN o.is_contributor = TRUE THEN 'contributor' ELSE 'non_contributor' END AS status,
            COUNT(o.id) AS count
        FROM organizations o
        {where_sql}
        GROUP BY 1;
    """
    cursor.execute(contrib_query, params)
    contrib_dist = cursor.fetchall()

    return {
        "organization_overview": {
            "summary": summary,
            "organization_activity_trend": activity_trend,
            "organizations_by_type": by_type,
            "organizations_by_size": by_size,
            "organizations_by_location": by_location,
            "collaborator_distribution": collab_dist,
            "contributor_distribution": contrib_dist,
        }
    }


def fetch_performance_dashboard(cursor, where_sql, params):
    """Generate Performance Dashboard Metrics."""
    # Summary Query
    summary_query = f"""
        SELECT 
            ROUND(AVG(o.rating)::numeric, 2) AS average_rating,
            COUNT(CASE WHEN o.rating IS NOT NULL THEN 1 END) AS rated_organizations,
            COUNT(CASE WHEN o.rating IS NULL THEN 1 END) AS unrated_organizations,
            COUNT(CASE WHEN o.rating = 5 THEN 1 END) AS five_star_organizations
        FROM organizations o
        {where_sql};
    """
    cursor.execute(summary_query, params)
    summary = cursor.fetchone() or {}

    # Rating Distribution (1 to 5)
    rating_query = f"""
        SELECT o.rating, COUNT(o.id) AS count
        FROM organizations o
        {where_sql} AND o.rating IS NOT NULL
        GROUP BY o.rating
        ORDER BY o.rating DESC;
    """
    cursor.execute(rating_query, params)
    rating_dist = cursor.fetchall()

    # Top-Rated Organizations
    top_rated_query = f"""
        SELECT o.id, o.name, o.rating, o.org_type, o.org_size
        FROM organizations o
        {where_sql} AND o.rating IS NOT NULL
        ORDER BY o.rating DESC
        LIMIT 10;
    """
    cursor.execute(top_rated_query, params)
    top_rated = cursor.fetchall()

    # Top Collaborators
    top_collab_query = f"""
        SELECT o.id, o.name, o.rating, o.org_type
        FROM organizations o
        {where_sql} AND o.is_collaborator = TRUE
        ORDER BY o.rating DESC NULLS LAST
        LIMIT 10;
    """
    cursor.execute(top_collab_query, params)
    top_collab = cursor.fetchall()

    # Top Contributors
    top_contrib_query = f"""
        SELECT o.id, o.name, o.rating, o.org_type
        FROM organizations o
        {where_sql} AND o.is_contributor = TRUE
        ORDER BY o.rating DESC NULLS LAST
        LIMIT 10;
    """
    cursor.execute(top_contrib_query, params)
    top_contrib = cursor.fetchall()

    # Ratings by Organization Type
    type_rating_query = f"""
        SELECT o.org_type AS type, ROUND(AVG(o.rating)::numeric, 2) AS average_rating, COUNT(o.id) AS count
        FROM organizations o
        {where_sql} AND o.rating IS NOT NULL
        GROUP BY o.org_type;
    """
    cursor.execute(type_rating_query, params)
    type_ratings = cursor.fetchall()

    # Ratings by Organization Size
    size_rating_query = f"""
        SELECT o.org_size AS size, ROUND(AVG(o.rating)::numeric, 2) AS average_rating, COUNT(o.id) AS count
        FROM organizations o
        {where_sql} AND o.rating IS NOT NULL
        GROUP BY o.org_size;
    """
    cursor.execute(size_rating_query, params)
    size_ratings = cursor.fetchall()

    return {
        "organization_performance": {
            "summary": summary,
            "rating_distribution": rating_dist,
            "top_rated_organizations": top_rated,
            "top_collaborator_organizations": top_collab,
            "top_contributor_organizations": top_contrib,
            "ratings_by_organization_type": type_ratings,
            "ratings_by_organization_size": size_ratings,
        }
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

        dashboard_type = payload.get("dashboard_type", "overview").lower()
        group_by = payload.get("group_by", "daily").lower()

        where_sql, params = build_where_clause(payload)

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if dashboard_type == "overview":
            response_data = fetch_overview_dashboard(
                cursor, where_sql, params, group_by
            )
        elif dashboard_type == "performance":
            response_data = fetch_performance_dashboard(
                cursor, where_sql, params
            )
        else:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "error_code": "DE 1002",
                        "message": "Invalid dashboard_type provided. Must be 'overview' or 'performance'.",
                    }
                ),
            }

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