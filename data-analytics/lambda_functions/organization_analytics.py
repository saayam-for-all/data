"""Organization analytics dashboards backed by PostgreSQL.

The Lambda accepts either a direct payload or an API Gateway event. Database
credentials are read from environment variables so the same code can run
against a local PostgreSQL instance or a configured Lambda environment.
"""

import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

DEFAULT_SCHEMA = "virginia_dev_saayam_rdbms"
TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
GROUPINGS = {
    "daily": ("day", "YYYY-MM-DD"),
    "weekly": ("week", "IYYY-IW"),
    "monthly": ("month", "YYYY-MM"),
    "yearly": ("year", "YYYY"),
}
CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


class RequestValidationError(ValueError):
    """Raised when an analytics request contains invalid filters."""


def get_schema_name():
    """Return a SQL-safe configured schema name."""
    schema = os.environ.get("DB_SCHEMA", DEFAULT_SCHEMA)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError("DB_SCHEMA must be a valid PostgreSQL identifier")
    return schema


def get_db_connection():
    """Create a PostgreSQL connection using local/environment configuration."""
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        dbname=os.environ.get("DB_NAME", "saayam_db"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", "postgres"),
        port=int(os.environ.get("DB_PORT", "5432")),
        connect_timeout=int(os.environ.get("DB_CONNECT_TIMEOUT", "10")),
    )


def parse_payload(event):
    """Parse direct invocation and API Gateway request formats."""
    if not isinstance(event, dict):
        raise RequestValidationError("Request must be a JSON object")

    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RequestValidationError("Request body must contain valid JSON") from exc
        if not isinstance(payload, dict):
            raise RequestValidationError("Request body must be a JSON object")
        return payload
    raise RequestValidationError("Request body must be a JSON object")


def _parse_date(value, field_name):
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise RequestValidationError(f"{field_name} must use YYYY-MM-DD format") from exc


def _parse_boolean(value, field_name):
    if value is None or isinstance(value, bool):
        return value
    raise RequestValidationError(f"{field_name} must be true, false, or null")


def validate_filters(payload):
    """Normalize and validate all common dashboard filters."""
    dashboard_type = str(payload.get("dashboard_type", "overview")).lower()
    if dashboard_type not in {"overview", "performance"}:
        raise RequestValidationError(
            "dashboard_type must be 'overview' or 'performance'"
        )

    time_filter = str(payload.get("time_filter", "30D")).upper()
    if time_filter not in TIME_FILTERS:
        raise RequestValidationError("time_filter must be 7D, 30D, 1Y, ALL, or CUSTOM")

    group_by = str(payload.get("group_by", "daily")).lower()
    if group_by not in GROUPINGS:
        raise RequestValidationError("group_by must be daily, weekly, monthly, or yearly")

    start_date = _parse_date(payload.get("start_date"), "start_date")
    end_date = _parse_date(payload.get("end_date"), "end_date")
    if time_filter == "CUSTOM" and (start_date is None or end_date is None):
        raise RequestValidationError("CUSTOM time_filter requires start_date and end_date")
    if start_date and end_date and start_date > end_date:
        raise RequestValidationError("start_date cannot be after end_date")

    org_rating = payload.get("org_rating")
    if org_rating is not None:
        if isinstance(org_rating, bool):
            raise RequestValidationError("org_rating must be a number from 1 to 5")
        try:
            org_rating = float(org_rating)
        except (TypeError, ValueError) as exc:
            raise RequestValidationError("org_rating must be a number from 1 to 5") from exc
        if not 1 <= org_rating <= 5:
            raise RequestValidationError("org_rating must be a number from 1 to 5")

    return {
        "dashboard_type": dashboard_type,
        "time_filter": time_filter,
        "start_date": start_date,
        "end_date": end_date,
        "org_type": payload.get("org_type"),
        "org_size": payload.get("org_size"),
        "state_id": payload.get("state_id"),
        "city_name": payload.get("city_name"),
        "org_rating": org_rating,
        "is_collaborator": _parse_boolean(payload.get("is_collaborator"), "is_collaborator"),
        "is_contributor": _parse_boolean(payload.get("is_contributor"), "is_contributor"),
        "group_by": group_by,
    }


def contributor_column_exists(cursor, schema):
    """Detect the in-progress is_contributor database migration."""
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
        (schema,),
    )
    row = cursor.fetchone()
    return bool(row and row["exists"])


def build_where_clause(filters, has_contributor):
    """Build a parameterized WHERE clause shared by all dashboard queries."""
    conditions = []
    params = {}
    time_filter = filters["time_filter"]

    if time_filter == "7D":
        conditions.append("o.created_at >= CURRENT_DATE - INTERVAL '7 days'")
    elif time_filter == "30D":
        conditions.append("o.created_at >= CURRENT_DATE - INTERVAL '30 days'")
    elif time_filter == "1Y":
        conditions.append("o.created_at >= CURRENT_DATE - INTERVAL '1 year'")
    elif time_filter == "CUSTOM":
        conditions.append(
            "o.created_at >= %(start_date)s AND o.created_at < %(end_exclusive)s"
        )
        params.update(
            start_date=filters["start_date"],
            end_exclusive=filters["end_date"] + timedelta(days=1),
        )

    column_filters = {
        "org_type": "o.org_type",
        "org_size": "o.org_size",
        "state_id": "o.state_id",
        "city_name": "o.city_name",
        "org_rating": "o.org_rating",
        "is_collaborator": "o.is_collaborator",
    }
    for name, column in column_filters.items():
        if filters[name] is not None:
            conditions.append(f"{column} = %({name})s")
            params[name] = filters[name]

    contributor_filter = filters["is_contributor"]
    if contributor_filter is not None:
        if has_contributor:
            conditions.append("o.is_contributor = %(is_contributor)s")
            params["is_contributor"] = contributor_filter
        elif contributor_filter:
            conditions.append("FALSE")

    return ("WHERE " + " AND ".join(conditions)) if conditions else "", params


def _with_condition(where_sql, condition):
    if where_sql:
        return f"{where_sql} AND {condition}"
    return f"WHERE {condition}"


def _fetch_all(cursor, query, params):
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def fetch_overview_dashboard(cursor, schema, where_sql, params, group_by, has_contributor):
    contributor_true = "o.is_contributor IS TRUE" if has_contributor else "FALSE"
    contributor_false = "o.is_contributor IS NOT TRUE" if has_contributor else "TRUE"
    cursor.execute(
        f"""
        SELECT COUNT(*) AS total_organizations,
               COUNT(*) FILTER (WHERE LOWER(o.org_type) IN ('non-profit', 'nonprofit')) AS non_profit_organizations,
               COUNT(*) FILTER (WHERE LOWER(o.org_type) IN ('for-profit', 'for profit')) AS for_profit_organizations,
               COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_organizations,
               COUNT(*) FILTER (WHERE o.is_collaborator IS NOT TRUE) AS non_collaborator_organizations,
               COUNT(*) FILTER (WHERE {contributor_true}) AS contributor_organizations,
               COUNT(*) FILTER (WHERE {contributor_false}) AS non_contributor_organizations
        FROM {schema}.organizations o
        {where_sql}
        """,
        params,
    )
    summary = dict(cursor.fetchone())
    trunc_unit, output_format = GROUPINGS[group_by]

    trend = _fetch_all(
        cursor,
        f"""
        SELECT TO_CHAR(DATE_TRUNC('{trunc_unit}', o.created_at), '{output_format}') AS period,
               COUNT(*) AS count
        FROM {schema}.organizations o
        {where_sql}
        GROUP BY DATE_TRUNC('{trunc_unit}', o.created_at)
        ORDER BY DATE_TRUNC('{trunc_unit}', o.created_at)
        """,
        params,
    )
    by_type = _fetch_all(
        cursor,
        f"""
        SELECT COALESCE(o.org_type, 'Unknown') AS type, COUNT(*) AS count
        FROM {schema}.organizations o
        {where_sql}
        GROUP BY o.org_type
        ORDER BY count DESC, type
        """,
        params,
    )
    by_size = _fetch_all(
        cursor,
        f"""
        SELECT COALESCE(o.org_size, 'Unknown') AS size, COUNT(*) AS count
        FROM {schema}.organizations o
        {where_sql}
        GROUP BY o.org_size
        ORDER BY count DESC, size
        """,
        params,
    )
    by_location = _fetch_all(
        cursor,
        f"""
        SELECT o.state_id, COALESCE(s.state_name, 'Unknown') AS state,
               COALESCE(o.city_name, 'Unknown') AS city, COUNT(*) AS count
        FROM {schema}.organizations o
        LEFT JOIN {schema}.state s ON o.state_id = s.state_id
        {where_sql}
        GROUP BY o.state_id, s.state_name, o.city_name
        ORDER BY count DESC, state, city
        """,
        params,
    )
    collaborators = [
        {"status": "collaborator", "count": summary["collaborator_organizations"]},
        {
            "status": "non_collaborator",
            "count": summary["non_collaborator_organizations"],
        },
    ]
    contributors = [
        {"status": "contributor", "count": summary["contributor_organizations"]},
        {
            "status": "non_contributor",
            "count": summary["non_contributor_organizations"],
        },
    ]

    return {"organization_overview": {
        "summary": summary,
        "organization_activity_trend": trend,
        "organizations_by_type": by_type,
        "organizations_by_size": by_size,
        "organizations_by_location": by_location,
        "collaborator_distribution": collaborators,
        "contributor_distribution": contributors,
    }}


def fetch_performance_dashboard(cursor, schema, where_sql, params, has_contributor):
    contributor_true = "o.is_contributor IS TRUE" if has_contributor else "FALSE"
    cursor.execute(
        f"""
        SELECT COALESCE(ROUND(AVG(o.org_rating)::numeric, 2), 0) AS average_rating,
               COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_organizations,
               COUNT(*) FILTER (WHERE o.org_rating IS NULL) AS unrated_organizations,
               COUNT(*) FILTER (WHERE o.org_rating = 5) AS five_star_organizations
        FROM {schema}.organizations o
        {where_sql}
        """,
        params,
    )
    summary = dict(cursor.fetchone())
    rated_where = _with_condition(where_sql, "o.org_rating IS NOT NULL")

    rating_rows = _fetch_all(
        cursor,
        f"""
        SELECT o.org_rating AS rating, COUNT(*) AS count
        FROM {schema}.organizations o
        {rated_where}
        GROUP BY o.org_rating
        ORDER BY o.org_rating
        """,
        params,
    )
    counts = {int(row["rating"]): int(row["count"]) for row in rating_rows}
    rating_distribution = [
        {"rating": rating, "count": counts.get(rating, 0)}
        for rating in range(1, 6)
    ]
    organization_fields = """
        o.org_id, o.org_name, o.org_rating, o.org_type, o.org_size,
        o.state_id, o.city_name
    """
    top_rated = _fetch_all(
        cursor,
        f"""
        SELECT {organization_fields}
        FROM {schema}.organizations o
        {rated_where}
        ORDER BY o.org_rating DESC, o.org_name
        LIMIT 10
        """,
        params,
    )
    top_collaborators = _fetch_all(
        cursor,
        f"""
        SELECT {organization_fields}
        FROM {schema}.organizations o
        {_with_condition(where_sql, 'o.is_collaborator IS TRUE')}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name
        LIMIT 10
        """,
        params,
    )
    top_contributors = _fetch_all(
        cursor,
        f"""
        SELECT {organization_fields}
        FROM {schema}.organizations o
        {_with_condition(where_sql, contributor_true)}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name
        LIMIT 10
        """,
        params,
    )
    by_type = _fetch_all(
        cursor,
        f"""
        SELECT COALESCE(o.org_type, 'Unknown') AS type,
               ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
               COUNT(*) AS rated_organizations
        FROM {schema}.organizations o
        {rated_where}
        GROUP BY o.org_type
        ORDER BY average_rating DESC, type
        """,
        params,
    )
    by_size = _fetch_all(
        cursor,
        f"""
        SELECT COALESCE(o.org_size, 'Unknown') AS size,
               ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
               COUNT(*) AS rated_organizations
        FROM {schema}.organizations o
        {rated_where}
        GROUP BY o.org_size
        ORDER BY average_rating DESC, size
        """,
        params,
    )

    return {"organization_performance": {
        "summary": summary,
        "rating_distribution": rating_distribution,
        "top_rated_organizations": top_rated,
        "top_collaborator_organizations": top_collaborators,
        "top_contributor_organizations": top_contributors,
        "ratings_by_organization_type": by_type,
        "ratings_by_organization_size": by_size,
    }}


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body, default=_json_default),
    }


def lambda_handler(event, context):
    """Serve overview or performance organization analytics."""
    conn = None
    cursor = None
    try:
        if isinstance(event, dict) and event.get("httpMethod") == "OPTIONS":
            return build_response(200, {})
        filters = validate_filters(parse_payload(event))
        schema = get_schema_name()
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        has_contributor = contributor_column_exists(cursor, schema)
        where_sql, params = build_where_clause(filters, has_contributor)

        if filters["dashboard_type"] == "overview":
            result = fetch_overview_dashboard(cursor, schema, where_sql, params, filters["group_by"], has_contributor)
        else:
            result = fetch_performance_dashboard(cursor, schema, where_sql, params, has_contributor)
        return build_response(200, result)
    except RequestValidationError as exc:
        return build_response(400, {"error_code": "DE 1002", "message": str(exc)})
    except psycopg2.Error:
        LOGGER.exception("Organization analytics database query failed")
        return build_response(500, {"error_code": "DE 1001", "message": "Database query failed."})
    except Exception:
        LOGGER.exception("Organization analytics request failed")
        return build_response(500, {"error_code": "DE 1000", "message": "Internal server execution error."})
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    print(json.dumps(lambda_handler({"dashboard_type": "overview"}, None), indent=2))
