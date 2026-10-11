import json
import os
from datetime import date

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv()

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ORGANIZATIONS = f"{SCHEMA_NAME}.organizations"
STATE = f"{SCHEMA_NAME}.state"

VALID_DASHBOARD_TYPES = {"overview", "performance"}
VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
VALID_GROUP_BY = {"daily", "weekly", "monthly", "yearly"}
VALID_ORG_TYPES = {"non_profit", "for_profit"}
VALID_ORG_SIZES = {"small", "medium", "large"}


def build_response(status_code, body):
    """Build an API Gateway-compatible JSON response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }


def parse_event_body(event):
    """Return a request dictionary from an API Gateway event or direct input."""
    if not event:
        return {}

    body = event.get("body") if isinstance(event, dict) else None
    if body is None:
        return event if isinstance(event, dict) else {}

    if isinstance(body, dict):
        return body

    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as error:
            raise ValueError("Request body must contain valid JSON.") from error
        if not isinstance(parsed, dict):
            raise ValueError("Request body must be a JSON object.")
        return parsed

    raise ValueError("Request body must be a JSON object.")


def get_db_connection():
    """Connect to the locally configured PostgreSQL database."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "saayam_analytics"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def has_contributor_column(cursor):
    """Check whether organizations.is_contributor exists in the current database."""
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = 'organizations'
              AND column_name = 'is_contributor'
        ) AS exists
        """,
        (SCHEMA_NAME,),
    )
    return bool(cursor.fetchone()["exists"])


def validate_bool(value, field_name):
    """Validate optional boolean request values."""
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{field_name} must be true, false, or null.")


def validate_date(value, field_name):
    """Validate an optional ISO-8601 date value."""
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO date string (YYYY-MM-DD).")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            f"{field_name} must use YYYY-MM-DD format."
        ) from error


def validate_request(payload, contributor_available):
    """Validate dashboard options and return normalized request options."""
    dashboard_type = payload.get("dashboard_type", "overview")
    time_filter = payload.get("time_filter", "30D")
    group_by = payload.get("group_by", "daily")
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")

    if dashboard_type not in VALID_DASHBOARD_TYPES:
        raise ValueError("dashboard_type must be overview or performance.")
    if time_filter not in VALID_TIME_FILTERS:
        raise ValueError("time_filter must be one of 7D, 30D, 1Y, ALL, CUSTOM.")
    if group_by not in VALID_GROUP_BY:
        raise ValueError("group_by must be daily, weekly, monthly, or yearly.")

    validate_date(start_date, "start_date")
    validate_date(end_date, "end_date")

    if time_filter == "CUSTOM" and not (start_date or end_date):
        raise ValueError(
            "CUSTOM time_filter requires start_date, end_date, or both."
        )
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date cannot be after end_date.")

    org_type = payload.get("org_type")
    org_size = payload.get("org_size")
    org_rating = payload.get("org_rating")

    if org_type is not None and org_type not in VALID_ORG_TYPES:
        raise ValueError("org_type must be non_profit or for_profit.")
    if org_size is not None and org_size not in VALID_ORG_SIZES:
        raise ValueError("org_size must be small, medium, or large.")
    if org_rating is not None and (
        not isinstance(org_rating, int) or isinstance(org_rating, bool)
        or not 1 <= org_rating <= 5
    ):
        raise ValueError("org_rating must be an integer from 1 through 5.")

    validate_bool(payload.get("is_collaborator"), "is_collaborator")
    validate_bool(payload.get("is_contributor"), "is_contributor")

    if payload.get("is_contributor") is not None and not contributor_available:
        raise ValueError(
            "is_contributor filtering is unavailable because the database "
            "does not yet contain the is_contributor column."
        )

    return {
        "dashboard_type": dashboard_type,
        "time_filter": time_filter,
        "group_by": group_by,
        "start_date": start_date,
        "end_date": end_date,
        "org_type": org_type,
        "org_size": org_size,
        "state_id": payload.get("state_id"),
        "city_name": payload.get("city_name"),
        "org_rating": org_rating,
        "is_collaborator": payload.get("is_collaborator"),
        "is_contributor": payload.get("is_contributor"),
    }


def build_where_clause(options, contributor_available):
    """Build parameterized filters shared by all metric queries."""
    clauses = []
    params = []

    time_filter = options["time_filter"]
    if time_filter == "7D":
        clauses.append("o.created_at >= CURRENT_DATE - INTERVAL '7 days'")
    elif time_filter == "30D":
        clauses.append("o.created_at >= CURRENT_DATE - INTERVAL '30 days'")
    elif time_filter == "1Y":
        clauses.append("o.created_at >= CURRENT_DATE - INTERVAL '1 year'")
    elif time_filter == "CUSTOM":
        if options["start_date"]:
            clauses.append("o.created_at >= %s")
            params.append(options["start_date"])
        if options["end_date"]:
            clauses.append("o.created_at < (%s::date + INTERVAL '1 day')")
            params.append(options["end_date"])

    if options["org_type"] is not None:
        clauses.append("o.org_type = %s")
        params.append(options["org_type"])
    if options["org_size"] is not None:
        clauses.append("o.org_size = %s")
        params.append(options["org_size"])
    if options["state_id"] is not None:
        clauses.append("o.state_id = %s")
        params.append(options["state_id"])
    if options["city_name"] is not None:
        clauses.append("o.city_name ILIKE %s")
        params.append(options["city_name"])
    if options["org_rating"] is not None:
        clauses.append("o.org_rating = %s")
        params.append(options["org_rating"])
    if options["is_collaborator"] is not None:
        clauses.append("o.is_collaborator = %s")
        params.append(options["is_collaborator"])
    if contributor_available and options["is_contributor"] is not None:
        clauses.append("o.is_contributor = %s")
        params.append(options["is_contributor"])

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


def query_rows(cursor, query, params):
    """Execute a query and return JSON-serializable dictionary rows."""
    cursor.execute(query, params)
    return cursor.fetchall()


def get_overview(cursor, options, contributor_available):
    """Return metrics for the Organization Overview dashboard."""
    where_sql, params = build_where_clause(options, contributor_available)

    contributor_summary = """
        COUNT(*) FILTER (WHERE o.is_contributor IS TRUE) AS contributor_organizations,
        COUNT(*) FILTER (
            WHERE o.is_contributor IS NOT TRUE
        ) AS non_contributor_organizations
    """ if contributor_available else """
        NULL::integer AS contributor_organizations,
        NULL::integer AS non_contributor_organizations
    """

    cursor.execute(
        f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (
                WHERE o.org_type = 'non_profit'
            ) AS non_profit_organizations,
            COUNT(*) FILTER (
                WHERE o.org_type = 'for_profit'
            ) AS for_profit_organizations,
            COUNT(*) FILTER (
                WHERE o.is_collaborator IS TRUE
            ) AS collaborator_organizations,
            COUNT(*) FILTER (
                WHERE o.is_collaborator IS NOT TRUE
            ) AS non_collaborator_organizations,
            {contributor_summary}
        FROM {ORGANIZATIONS} o
        {where_sql}
        """,
        params,
    )
    summary = dict(cursor.fetchone())
    for key, value in summary.items():
        if value is not None:
            summary[key] = int(value)

    period, date_format = {
        "daily": ("day", "YYYY-MM-DD"),
        "weekly": ("week", 'IYYY-"W"IW'),
        "monthly": ("month", "YYYY-MM"),
        "yearly": ("year", "YYYY"),
    }[options["group_by"]]

    activity_rows = query_rows(
        cursor,
        f"""
        SELECT
            TO_CHAR(
                DATE_TRUNC('{period}', o.created_at),
                '{date_format}'
            ) AS period,
            COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY 1
        ORDER BY 1
        """,
        params,
    )

    type_rows = query_rows(
        cursor,
        f"""
        SELECT o.org_type AS type, COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY o.org_type
        ORDER BY o.org_type
        """,
        params,
    )

    size_rows = query_rows(
        cursor,
        f"""
        SELECT o.org_size AS size, COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY o.org_size
        ORDER BY o.org_size
        """,
        params,
    )

    location_rows = query_rows(
        cursor,
        f"""
        SELECT
            s.state_name AS state,
            s.state_code AS state_code,
            o.city_name AS city,
            COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        LEFT JOIN {STATE} s ON s.state_id = o.state_id
        {where_sql}
        GROUP BY s.state_name, s.state_code, o.city_name
        ORDER BY count DESC, state, city
        """,
        params,
    )

    collaborator_rows = query_rows(
        cursor,
        f"""
        SELECT
            COALESCE(o.is_collaborator, FALSE) AS is_collaborator,
            COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY COALESCE(o.is_collaborator, FALSE)
        ORDER BY is_collaborator DESC
        """,
        params,
    )

    contributor_rows = []
    if contributor_available:
        contributor_rows = query_rows(
            cursor,
            f"""
            SELECT
                COALESCE(o.is_contributor, FALSE) AS is_contributor,
                COUNT(*) AS count
            FROM {ORGANIZATIONS} o
            {where_sql}
            GROUP BY COALESCE(o.is_contributor, FALSE)
            ORDER BY is_contributor DESC
            """,
            params,
        )

    return {
        "organization_overview": {
            "summary": summary,
            "organization_activity_trend": [
                {"period": row["period"], "count": int(row["count"])}
                for row in activity_rows
            ],
            "organizations_by_type": [
                {"type": row["type"], "count": int(row["count"])}
                for row in type_rows
            ],
            "organizations_by_size": [
                {"size": row["size"], "count": int(row["count"])}
                for row in size_rows
            ],
            "organizations_by_location": [
                {
                    "state": row["state"],
                    "state_code": row["state_code"],
                    "city": row["city"],
                    "count": int(row["count"]),
                }
                for row in location_rows
            ],
            "collaborator_distribution": [
                {
                    "is_collaborator": bool(row["is_collaborator"]),
                    "count": int(row["count"]),
                }
                for row in collaborator_rows
            ],
            "contributor_distribution": [
                {
                    "is_contributor": bool(row["is_contributor"]),
                    "count": int(row["count"]),
                }
                for row in contributor_rows
            ],
        }
    }


def get_performance(cursor, options, contributor_available):
    """Return metrics for the Organization Performance dashboard."""
    where_sql, params = build_where_clause(options, contributor_available)

    cursor.execute(
        f"""
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
        FROM {ORGANIZATIONS} o
        {where_sql}
        """,
        params,
    )
    summary = dict(cursor.fetchone())
    summary["average_rating"] = (
        float(summary["average_rating"])
        if summary["average_rating"] is not None
        else None
    )
    for key in (
        "rated_organizations",
        "unrated_organizations",
        "five_star_organizations",
    ):
        summary[key] = int(summary[key])

    rating_rows = query_rows(
        cursor,
        f"""
        SELECT o.org_rating AS rating, COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY o.org_rating
        ORDER BY o.org_rating NULLS LAST
        """,
        params,
    )

    def top_organizations(extra_clause):
        combined_where = (
            f"{where_sql} AND {extra_clause}"
            if where_sql
            else f"WHERE {extra_clause}"
        )
        rows = query_rows(
            cursor,
            f"""
            SELECT
                o.org_id,
                o.org_name,
                o.org_rating AS rating,
                o.org_type AS type,
                o.org_size AS size
            FROM {ORGANIZATIONS} o
            {combined_where}
            ORDER BY o.org_rating DESC NULLS LAST, o.org_name
            LIMIT 10
            """,
            params,
        )
        return [
            {
                "org_id": row["org_id"],
                "org_name": row["org_name"],
                "rating": row["rating"],
                "type": row["type"],
                "size": row["size"],
            }
            for row in rows
        ]

    type_rating_rows = query_rows(
        cursor,
        f"""
        SELECT
            o.org_type AS type,
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY o.org_type
        ORDER BY o.org_type
        """,
        params,
    )

    size_rating_rows = query_rows(
        cursor,
        f"""
        SELECT
            o.org_size AS size,
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(*) AS count
        FROM {ORGANIZATIONS} o
        {where_sql}
        GROUP BY o.org_size
        ORDER BY o.org_size
        """,
        params,
    )

    return {
        "organization_performance": {
            "summary": summary,
            "rating_distribution": [
                {"rating": row["rating"], "count": int(row["count"])}
                for row in rating_rows
            ],
            "top_rated_organizations": top_organizations(
                "o.org_rating IS NOT NULL"
            ),
            "top_collaborator_organizations": top_organizations(
                "o.is_collaborator IS TRUE"
            ),
            "top_contributor_organizations": (
                top_organizations("o.is_contributor IS TRUE")
                if contributor_available
                else []
            ),
            "ratings_by_organization_type": [
                {
                    "type": row["type"],
                    "average_rating": (
                        float(row["average_rating"])
                        if row["average_rating"] is not None
                        else None
                    ),
                    "count": int(row["count"]),
                }
                for row in type_rating_rows
            ],
            "ratings_by_organization_size": [
                {
                    "size": row["size"],
                    "average_rating": (
                        float(row["average_rating"])
                        if row["average_rating"] is not None
                        else None
                    ),
                    "count": int(row["count"]),
                }
                for row in size_rating_rows
            ],
        }
    }


def lambda_handler(event, context):
    """Handle Organization Overview and Performance analytics requests."""
    connection = None
    cursor = None

    try:
        request = parse_event_body(event)
        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=RealDictCursor)

        contributor_available = has_contributor_column(cursor)
        options = validate_request(request, contributor_available)

        if options["dashboard_type"] == "performance":
            response_body = get_performance(
                cursor,
                options,
                contributor_available,
            )
        else:
            response_body = get_overview(
                cursor,
                options,
                contributor_available,
            )

        return build_response(200, response_body)

    except ValueError as error:
        return build_response(400, {"error": str(error)})
    except psycopg2.Error as error:
        return build_response(
            500,
            {"error": "Database query failed.", "details": str(error)},
        )
    except Exception as error:
        return build_response(
            500,
            {"error": "Unexpected server error.", "details": str(error)},
        )
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
