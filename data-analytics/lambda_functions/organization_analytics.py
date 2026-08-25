"""Organization-level analytics for the Saayam application dashboard.

The handler accepts either an API Gateway event or a direct dictionary payload.
Database credentials come only from local/runtime environment variables; this
module intentionally does not use AWS Systems Manager Parameter Store.
"""

import json
import logging
import os
import re
from datetime import date, timedelta
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

DEFAULT_SCHEMA = "virginia_dev_saayam_rdbms"
VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
GROUPINGS = {
    "daily": ("day", "YYYY-MM-DD"),
    "weekly": ("week", 'IYYY-"W"IW'),
    "monthly": ("month", "YYYY-MM"),
    "yearly": ("year", "YYYY"),
}
VALID_ORGANIZATION_TYPES = {"for_profit", "non_profit"}
VALID_STATE_TABLES = {"state", "states"}

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


class RequestValidationError(ValueError):
    """Raised when request filters do not satisfy the API contract."""


def build_response(status_code, body):
    """Build an API Gateway-compatible JSON response."""
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body, default=_json_default),
    }


def _json_default(value):
    """Serialize PostgreSQL numeric/date values returned by mocked or live cursors."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def get_default_response():
    """Return the stable response shape used for empty data and failures."""
    return {
        "summary": {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": 0.0,
        },
        "growth_trend": [],
        "organizations_by_location": [],
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
        "rating_distribution": [],
        "organization_type_distribution": [],
    }


def parse_event_body(event):
    """Normalize API Gateway and direct invocation events to a payload dictionary."""
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise RequestValidationError("Request must be a JSON object")

    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RequestValidationError(
                "Request body must contain valid JSON"
            ) from exc
        if isinstance(parsed, dict):
            return parsed
    raise RequestValidationError("Request body must be a JSON object")


def _parse_date(value, field_name):
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise RequestValidationError(
            f"{field_name} must use YYYY-MM-DD format"
        ) from exc


def _normalize_org_type(value):
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def validate_filters(payload):
    """Validate and normalize the dashboard's shared filters."""
    time_filter = str(payload.get("time_filter", "30D")).strip().upper()
    if time_filter not in VALID_TIME_FILTERS:
        raise RequestValidationError("time_filter must be 7D, 30D, 1Y, ALL, or CUSTOM")

    group_by = str(payload.get("group_by", "daily")).strip().lower()
    if group_by not in GROUPINGS:
        raise RequestValidationError(
            "group_by must be daily, weekly, monthly, or yearly"
        )

    start_date = _parse_date(payload.get("start_date"), "start_date")
    end_date = _parse_date(payload.get("end_date"), "end_date")
    if time_filter == "CUSTOM" and (start_date is None or end_date is None):
        raise RequestValidationError(
            "CUSTOM time_filter requires both start_date and end_date"
        )
    if start_date and end_date and start_date > end_date:
        raise RequestValidationError("start_date cannot be after end_date")

    raw_region = payload.get("region", "ALL")
    region = "ALL" if raw_region is None else str(raw_region).strip()
    if not region:
        raise RequestValidationError("region cannot be empty")

    raw_org_type = payload.get("organization_type", "ALL")
    organization_type = (
        "all" if raw_org_type is None else _normalize_org_type(raw_org_type)
    )
    if organization_type == "all":
        organization_type = "ALL"
    if organization_type != "ALL" and organization_type not in VALID_ORGANIZATION_TYPES:
        raise RequestValidationError(
            "organization_type must be ALL, for_profit, or non_profit"
        )

    return {
        "time_filter": time_filter,
        "start_date": start_date,
        "end_date": end_date,
        "group_by": group_by,
        "region": region,
        "organization_type": organization_type,
    }


def _validated_identifier(value, label):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"{label} must be a valid PostgreSQL identifier")
    return value


def get_database_layout():
    """Return validated table identifiers used in query interpolation.

    The current ticket names ``states``. Older Saayam schemas use ``state``;
    local testing against those schemas can set ``SAAYAM_STATE_TABLE=state``.
    """
    schema = _validated_identifier(
        os.environ.get("DB_SCHEMA", DEFAULT_SCHEMA), "DB_SCHEMA"
    )
    state_table = os.environ.get("SAAYAM_STATE_TABLE", "states")
    if state_table not in VALID_STATE_TABLES:
        raise ValueError("SAAYAM_STATE_TABLE must be 'state' or 'states'")
    return schema, state_table


def get_db_connection():
    """Create a local/runtime PostgreSQL connection without AWS Parameter Store."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    return psycopg2.connect(
        host=os.environ.get("DB_HOST", os.environ.get("PGHOST", "localhost")),
        dbname=os.environ.get("DB_NAME", os.environ.get("PGDATABASE", "saayam")),
        user=os.environ.get("DB_USER", os.environ.get("PGUSER", "postgres")),
        password=os.environ.get("DB_PASSWORD", os.environ.get("PGPASSWORD", "")),
        port=int(os.environ.get("DB_PORT", os.environ.get("PGPORT", "5432"))),
        connect_timeout=int(os.environ.get("DB_CONNECT_TIMEOUT", "10")),
    )


def contributor_column_exists(cursor, schema):
    """Check whether the latest ``is_contributor`` migration is available."""
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


def _from_clause(schema, state_table):
    return (
        f"FROM {schema}.organizations o "
        f"LEFT JOIN {schema}.{state_table} s ON o.state_id = s.state_id"
    )


def _time_conditions(filters):
    """Return window condition, baseline condition, and named parameters."""
    time_filter = filters["time_filter"]
    if time_filter == "7D":
        boundary = "CURRENT_DATE - INTERVAL '7 days'"
        return f"o.created_at >= {boundary}", f"o.created_at < {boundary}", {}
    if time_filter == "30D":
        boundary = "CURRENT_DATE - INTERVAL '30 days'"
        return f"o.created_at >= {boundary}", f"o.created_at < {boundary}", {}
    if time_filter == "1Y":
        boundary = "CURRENT_DATE - INTERVAL '1 year'"
        return f"o.created_at >= {boundary}", f"o.created_at < {boundary}", {}
    if time_filter == "CUSTOM":
        return (
            "o.created_at >= %(start_date)s AND o.created_at < %(end_exclusive)s",
            "o.created_at < %(start_date)s",
            {
                "start_date": filters["start_date"],
                "end_exclusive": filters["end_date"] + timedelta(days=1),
            },
        )
    return "", "FALSE", {}


def _non_date_conditions(filters):
    conditions = []
    params = {}

    if filters["region"].upper() != "ALL":
        conditions.append(
            "(LOWER(COALESCE(s.state_name, '')) = LOWER(%(region)s) "
            "OR LOWER(COALESCE(s.state_id::text, '')) = LOWER(%(region)s))"
        )
        params["region"] = filters["region"]

    if filters["organization_type"] != "ALL":
        conditions.append(
            "LOWER(REGEXP_REPLACE(TRIM(o.org_type::text), '[- ]+', '_', 'g')) "
            "= %(organization_type)s"
        )
        params["organization_type"] = filters["organization_type"]

    return conditions, params


def build_where_clause(filters, include_time=True, extra_conditions=None):
    """Build the common parameterized SQL filter used by every metric."""
    conditions, params = _non_date_conditions(filters)
    if include_time:
        time_condition, _, time_params = _time_conditions(filters)
        if time_condition:
            conditions.insert(0, time_condition)
        params.update(time_params)
    if extra_conditions:
        conditions.extend(extra_conditions)
    return (f"WHERE {' AND '.join(conditions)}" if conditions else ""), params


def _where_from_conditions(conditions):
    return f"WHERE {' AND '.join(conditions)}" if conditions else ""


def get_summary(cursor, schema, state_table, filters, has_contributor):
    where_sql, params = build_where_clause(filters)
    contributor_sql = (
        "COUNT(*) FILTER (WHERE o.is_contributor IS TRUE)"
        if has_contributor
        else "0::bigint"
    )
    cursor.execute(
        f"""
        SELECT COUNT(*) AS total_organizations,
               COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS total_collaborators,
               {contributor_sql} AS total_contributors,
               ROUND(AVG(o.org_rating)::numeric, 2) AS average_org_rating
        {_from_clause(schema, state_table)}
        {where_sql}
        """,
        params,
    )
    row = cursor.fetchone() or {}
    rating = row.get("average_org_rating")
    return {
        "total_organizations": int(row.get("total_organizations") or 0),
        "total_collaborators": int(row.get("total_collaborators") or 0),
        "total_contributors": int(row.get("total_contributors") or 0),
        "average_org_rating": float(rating) if rating is not None else 0.0,
    }


def get_growth_trend(cursor, schema, state_table, filters):
    trunc_unit, date_format = GROUPINGS[filters["group_by"]]
    non_date_conditions, params = _non_date_conditions(filters)
    window_condition, baseline_condition, time_params = _time_conditions(filters)
    params.update(time_params)
    window_conditions = list(non_date_conditions)
    if window_condition:
        window_conditions.insert(0, window_condition)
    baseline_conditions = list(non_date_conditions) + [baseline_condition]

    cursor.execute(
        f"""
        WITH baseline AS (
            SELECT COUNT(*) AS organizations,
                   COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborators
            {_from_clause(schema, state_table)}
            {_where_from_conditions(baseline_conditions)}
        ), period_counts AS (
            SELECT DATE_TRUNC('{trunc_unit}', o.created_at) AS period_start,
                   TO_CHAR(DATE_TRUNC('{trunc_unit}', o.created_at), '{date_format}') AS period,
                   COUNT(*) AS organizations,
                   COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborators
            {_from_clause(schema, state_table)}
            {_where_from_conditions(window_conditions)}
            GROUP BY 1, 2
        )
        SELECT pc.period,
               b.organizations + SUM(pc.organizations) OVER (ORDER BY pc.period_start)
                   AS total_organizations,
               b.collaborators + SUM(pc.collaborators) OVER (ORDER BY pc.period_start)
                   AS total_collaborators
        FROM period_counts pc CROSS JOIN baseline b
        ORDER BY pc.period_start
        """,
        params,
    )
    return [
        {
            "period": row["period"],
            "total_organizations": int(row["total_organizations"]),
            "total_collaborators": int(row["total_collaborators"]),
        }
        for row in cursor.fetchall()
    ]


def get_organizations_by_location(cursor, schema, state_table, filters):
    where_sql, params = build_where_clause(filters)
    from_sql = _from_clause(schema, state_table)
    state_id_sql = "COALESCE(s.state_id::text, o.state_id::text, 'UNKNOWN')"

    cursor.execute(
        f"""
        SELECT {state_id_sql} AS state_id,
               COALESCE(s.state_name, 'Unknown') AS state_name,
               COUNT(*) AS organization_count,
               ROUND(
                   (100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0))::numeric,
                   1
               ) AS percentage
        {from_sql}
        {where_sql}
        GROUP BY 1, 2
        ORDER BY organization_count DESC, state_name
        """,
        params,
    )
    states = cursor.fetchall()

    cursor.execute(
        f"""
        SELECT {state_id_sql} AS state_id,
               COALESCE(NULLIF(TRIM(o.city_name), ''), 'Unknown') AS city_name,
               COUNT(*) AS organization_count
        {from_sql}
        {where_sql}
        GROUP BY 1, 2
        ORDER BY organization_count DESC, city_name
        """,
        params,
    )
    cities_by_state = {}
    for row in cursor.fetchall():
        cities_by_state.setdefault(row["state_id"], []).append(
            {
                "city_name": row["city_name"],
                "organization_count": int(row["organization_count"]),
            }
        )

    return [
        {
            "state_id": row["state_id"],
            "state_name": row["state_name"],
            "organization_count": int(row["organization_count"]),
            "percentage": float(row["percentage"] or 0),
            "cities": cities_by_state.get(row["state_id"], []),
        }
        for row in states
    ]


def get_organizations_by_size(cursor, schema, state_table, filters):
    where_sql, params = build_where_clause(filters)
    cursor.execute(
        f"""
        WITH filtered AS (
            SELECT LOWER(TRIM(o.org_size::text)) AS org_size
            {_from_clause(schema, state_table)}
            {where_sql}
        ), sizes(org_size, sort_order) AS (
            VALUES ('small', 1), ('medium', 2), ('large', 3)
        )
        SELECT sizes.org_size, COUNT(filtered.org_size) AS organization_count
        FROM sizes
        LEFT JOIN filtered ON filtered.org_size = sizes.org_size
        GROUP BY sizes.org_size, sizes.sort_order
        ORDER BY sizes.sort_order
        """,
        params,
    )
    return [
        {
            "org_size": row["org_size"],
            "organization_count": int(row["organization_count"]),
        }
        for row in cursor.fetchall()
    ]


def get_collaborator_vs_contributor(
    cursor, schema, state_table, filters, has_contributor
):
    where_sql, params = build_where_clause(filters)
    contributor_sql = (
        "COUNT(*) FILTER (WHERE o.is_contributor IS TRUE)"
        if has_contributor
        else "0::bigint"
    )
    cursor.execute(
        f"""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborators,
               {contributor_sql} AS contributors
        {_from_clause(schema, state_table)}
        {where_sql}
        """,
        params,
    )
    row = cursor.fetchone() or {}
    total = int(row.get("total") or 0)
    collaborators = int(row.get("collaborators") or 0)
    contributors = int(row.get("contributors") or 0)

    def percentage(count):
        return round(count * 100.0 / total, 1) if total else 0.0

    return [
        {
            "type": "collaborator",
            "organization_count": collaborators,
            "percentage": percentage(collaborators),
        },
        {
            "type": "contributor",
            "organization_count": contributors,
            "percentage": percentage(contributors),
        },
    ]


def get_rating_distribution(cursor, schema, state_table, filters):
    where_sql, params = build_where_clause(filters)
    cursor.execute(
        f"""
        WITH filtered AS (
            SELECT o.org_rating
            {_from_clause(schema, state_table)}
            {where_sql}
        ), ratings(rating) AS (
            VALUES (1), (2), (3), (4), (5)
        )
        SELECT ratings.rating, COUNT(filtered.org_rating) AS organization_count
        FROM ratings
        LEFT JOIN filtered ON filtered.org_rating = ratings.rating
        GROUP BY ratings.rating
        ORDER BY ratings.rating
        """,
        params,
    )
    return [
        {
            "rating": int(row["rating"]),
            "organization_count": int(row["organization_count"]),
        }
        for row in cursor.fetchall()
    ]


def get_organization_type_distribution(cursor, schema, state_table, filters):
    trunc_unit, date_format = GROUPINGS[filters["group_by"]]
    non_date_conditions, params = _non_date_conditions(filters)
    window_condition, baseline_condition, time_params = _time_conditions(filters)
    params.update(time_params)
    window_conditions = list(non_date_conditions)
    if window_condition:
        window_conditions.insert(0, window_condition)
    baseline_conditions = list(non_date_conditions) + [baseline_condition]
    normalized_type = "LOWER(REGEXP_REPLACE(TRIM(o.org_type::text), '[- ]+', '_', 'g'))"

    cursor.execute(
        f"""
        WITH baseline AS (
            SELECT COUNT(*) FILTER (WHERE {normalized_type} = 'for_profit') AS for_profit,
                   COUNT(*) FILTER (WHERE {normalized_type} = 'non_profit') AS non_profit
            {_from_clause(schema, state_table)}
            {_where_from_conditions(baseline_conditions)}
        ), period_counts AS (
            SELECT DATE_TRUNC('{trunc_unit}', o.created_at) AS period_start,
                   TO_CHAR(DATE_TRUNC('{trunc_unit}', o.created_at), '{date_format}') AS period,
                   COUNT(*) FILTER (WHERE {normalized_type} = 'for_profit') AS for_profit,
                   COUNT(*) FILTER (WHERE {normalized_type} = 'non_profit') AS non_profit
            {_from_clause(schema, state_table)}
            {_where_from_conditions(window_conditions)}
            GROUP BY 1, 2
        )
        SELECT pc.period,
               b.for_profit + SUM(pc.for_profit) OVER (ORDER BY pc.period_start) AS for_profit,
               b.non_profit + SUM(pc.non_profit) OVER (ORDER BY pc.period_start) AS non_profit,
               b.for_profit + b.non_profit
                   + SUM(pc.for_profit + pc.non_profit) OVER (ORDER BY pc.period_start) AS total
        FROM period_counts pc CROSS JOIN baseline b
        ORDER BY pc.period_start
        """,
        params,
    )
    return [
        {
            "period": row["period"],
            "for_profit": int(row["for_profit"]),
            "non_profit": int(row["non_profit"]),
            "total": int(row["total"]),
        }
        for row in cursor.fetchall()
    ]


def _run_metric(name, default, connection, function):
    """Run one metric and restore the transaction after a query failure."""
    try:
        return function()
    except Exception:
        LOGGER.exception("Organization analytics query failed: %s", name)
        try:
            connection.rollback()
        except Exception:
            LOGGER.exception("Database rollback failed after %s", name)
        return default


def lambda_handler(event, context):
    """Return all organization dashboard tabs from a single request."""
    del context
    response_body = get_default_response()

    try:
        payload = parse_event_body(event)
        filters = validate_filters(payload)
        schema, state_table = get_database_layout()
    except (RequestValidationError, ValueError) as exc:
        return build_response(400, {"error": str(exc), **response_body})

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=RealDictCursor)

        has_contributor = _run_metric(
            "contributor_column_check",
            False,
            connection,
            lambda: contributor_column_exists(cursor, schema),
        )

        response_body["summary"] = _run_metric(
            "summary",
            response_body["summary"],
            connection,
            lambda: get_summary(cursor, schema, state_table, filters, has_contributor),
        )
        response_body["growth_trend"] = _run_metric(
            "growth_trend",
            [],
            connection,
            lambda: get_growth_trend(cursor, schema, state_table, filters),
        )
        response_body["organizations_by_location"] = _run_metric(
            "organizations_by_location",
            [],
            connection,
            lambda: get_organizations_by_location(cursor, schema, state_table, filters),
        )
        response_body["organizations_by_size"] = _run_metric(
            "organizations_by_size",
            [],
            connection,
            lambda: get_organizations_by_size(cursor, schema, state_table, filters),
        )
        response_body["collaborator_vs_contributor"] = _run_metric(
            "collaborator_vs_contributor",
            [],
            connection,
            lambda: get_collaborator_vs_contributor(
                cursor, schema, state_table, filters, has_contributor
            ),
        )
        response_body["rating_distribution"] = _run_metric(
            "rating_distribution",
            [],
            connection,
            lambda: get_rating_distribution(cursor, schema, state_table, filters),
        )
        response_body["organization_type_distribution"] = _run_metric(
            "organization_type_distribution",
            [],
            connection,
            lambda: get_organization_type_distribution(
                cursor, schema, state_table, filters
            ),
        )

        return build_response(200, response_body)
    except Exception:
        LOGGER.exception("Organization analytics database connection failed")
        return build_response(500, response_body)
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                LOGGER.exception("Failed to close organization analytics cursor")
        if connection is not None:
            try:
                connection.close()
            except Exception:
                LOGGER.exception("Failed to close organization analytics connection")


if __name__ == "__main__":
    print(json.dumps(lambda_handler({}, None), indent=2))
