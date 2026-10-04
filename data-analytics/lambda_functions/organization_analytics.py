"""Organization analytics API for the Saayam dashboard.

The Lambda exposes a single handler selected by ``dashboard_type`` and thin
wrappers for deployments that prefer separate overview/performance routes.
Database settings come from environment variables; no AWS Parameter Store path
is embedded in this module.
"""

import json
import logging
import os
from datetime import date
from decimal import Decimal


LOGGER = logging.getLogger(__name__)

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ORGANIZATIONS_TABLE = f"{SCHEMA_NAME}.organizations"
STATE_TABLE = f"{SCHEMA_NAME}.state"

VALID_DASHBOARDS = {"overview", "performance"}
VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
VALID_GROUP_BY = {
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
    "yearly": "year",
}
VALID_ORG_TYPES = {"non_profit", "for_profit"}
VALID_ORG_SIZES = {"small", "medium", "large"}
TOP_ORGANIZATION_LIMIT = 10

NORMALIZED_ORG_TYPE = (
    "REPLACE(REPLACE(LOWER(o.org_type::text), '-', '_'), ' ', '_')"
)
NORMALIZED_ORG_SIZE = (
    "REPLACE(REPLACE(LOWER(o.org_size::text), '-', '_'), ' ', '_')"
)


class RequestValidationError(ValueError):
    """Raised when an API request contains unsupported filter values."""


def normalize_label(value):
    """Normalize display labels such as ``Non-Profit`` to ``non_profit``."""
    if value is None:
        return None
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def parse_boolean(value, field_name):
    """Parse a JSON boolean or a common string representation."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise RequestValidationError(f"{field_name} must be true, false, or null.")


def parse_event_body(event):
    """Return a request dictionary for direct or API Gateway proxy invocation."""
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise RequestValidationError("The request payload must be a JSON object.")

    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as error:
            raise RequestValidationError("The request body is not valid JSON.") from error
        if not isinstance(parsed, dict):
            raise RequestValidationError("The request body must be a JSON object.")
        return parsed
    raise RequestValidationError("The request body must be a JSON object.")


def parse_filters(request_body):
    """Validate and normalize the filters shared by both dashboards."""
    time_filter = str(request_body.get("time_filter", "30D")).upper()
    if time_filter not in VALID_TIME_FILTERS:
        allowed = ", ".join(sorted(VALID_TIME_FILTERS))
        raise RequestValidationError(f"time_filter must be one of: {allowed}.")

    group_by = str(request_body.get("group_by", "daily")).lower()
    if group_by not in VALID_GROUP_BY:
        allowed = ", ".join(VALID_GROUP_BY)
        raise RequestValidationError(f"group_by must be one of: {allowed}.")

    start_date = request_body.get("start_date")
    end_date = request_body.get("end_date")
    if time_filter == "CUSTOM":
        if not start_date or not end_date:
            raise RequestValidationError(
                "CUSTOM time_filter requires start_date and end_date."
            )
        try:
            parsed_start = date.fromisoformat(str(start_date))
            parsed_end = date.fromisoformat(str(end_date))
        except ValueError as error:
            raise RequestValidationError(
                "start_date and end_date must use YYYY-MM-DD format."
            ) from error
        if parsed_start > parsed_end:
            raise RequestValidationError("start_date cannot be after end_date.")
        start_date = parsed_start.isoformat()
        end_date = parsed_end.isoformat()

    org_type = normalize_label(request_body.get("org_type"))
    if org_type is not None and org_type not in VALID_ORG_TYPES:
        raise RequestValidationError("org_type must be non_profit or for_profit.")

    org_size = normalize_label(request_body.get("org_size"))
    if org_size is not None and org_size not in VALID_ORG_SIZES:
        raise RequestValidationError("org_size must be small, medium, or large.")

    org_rating = request_body.get("org_rating")
    if org_rating is not None:
        try:
            org_rating = int(org_rating)
        except (TypeError, ValueError) as error:
            raise RequestValidationError("org_rating must be an integer from 1 to 5.") from error
        if org_rating < 1 or org_rating > 5:
            raise RequestValidationError("org_rating must be an integer from 1 to 5.")

    state_id = request_body.get("state_id")
    if state_id is not None:
        state_id = str(state_id).strip().upper()
    city_name = request_body.get("city_name")
    if city_name is not None:
        city_name = str(city_name).strip()

    return {
        "time_filter": time_filter,
        "start_date": start_date,
        "end_date": end_date,
        "org_type": org_type,
        "org_size": org_size,
        "state_id": state_id,
        "city_name": city_name,
        "org_rating": org_rating,
        "is_collaborator": parse_boolean(
            request_body.get("is_collaborator"), "is_collaborator"
        ),
        "is_contributor": parse_boolean(
            request_body.get("is_contributor"), "is_contributor"
        ),
        "group_by": group_by,
    }


def build_response(status_code, body):
    """Build an API Gateway proxy response with standard CORS headers."""
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


def get_db_connection():
    """Create a PostgreSQL connection using only environment configuration.

    ``DATABASE_URL`` takes precedence. Otherwise ``DB_HOST``, ``DB_PORT``,
    ``DB_NAME``, ``DB_USER``, ``DB_PASSWORD`` and optional ``DB_SSLMODE`` are
    used. Local-friendly defaults are supplied for host, port, database, and
    user; a password is not hard-coded.
    """
    try:
        import psycopg2
    except ImportError as error:
        raise RuntimeError(
            "psycopg2 is required. Install data-analytics/lambda_functions/"
            "requirements.txt before running the API."
        ) from error

    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        connection = psycopg2.connect(database_url)
    else:
        connection_options = {
            "host": os.environ.get("DB_HOST", "localhost"),
            "port": os.environ.get("DB_PORT", "5432"),
            "dbname": os.environ.get("DB_NAME", "saayam_local"),
            "user": os.environ.get("DB_USER", "postgres"),
        }
        password = os.environ.get("DB_PASSWORD")
        sslmode = os.environ.get("DB_SSLMODE")
        if password is not None:
            connection_options["password"] = password
        if sslmode:
            connection_options["sslmode"] = sslmode
        connection = psycopg2.connect(**connection_options)

    # Each dashboard metric is read-only and independent. Autocommit prevents a
    # single failed metric from aborting every subsequent query on the connection.
    connection.autocommit = True
    return connection


def get_default_overview_response():
    """Return the complete safe shape for the overview dashboard."""
    return {
        "organization_overview": {
            "summary": {
                "total_organizations": 0,
                "non_profit_organizations": 0,
                "for_profit_organizations": 0,
                "collaborator_organizations": 0,
                "non_collaborator_organizations": 0,
                "contributor_organizations": None,
                "non_contributor_organizations": None,
            },
            "organization_activity_trend": [],
            "organizations_by_type": [],
            "organizations_by_size": [],
            "organizations_by_location": {"by_state": [], "by_city": []},
            "collaborator_distribution": [],
            "contributor_distribution": [],
        }
    }


def get_default_performance_response():
    """Return the complete safe shape for the performance dashboard."""
    return {
        "organization_performance": {
            "summary": {
                "average_rating": 0.0,
                "rated_organizations": 0,
                "unrated_organizations": 0,
                "five_star_organizations": 0,
            },
            "rating_distribution": [],
            "top_rated_organizations": [],
            "top_collaborator_organizations": [],
            "top_contributor_organizations": [],
            "ratings_by_organization_type": [],
            "ratings_by_organization_size": [],
        }
    }


def has_contributor_column(cursor):
    """Return whether the not-yet-universal ``is_contributor`` column exists."""
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = 'organizations'
              AND column_name = 'is_contributor'
        ) AS available;
        """,
        (SCHEMA_NAME,),
    )
    row = cursor.fetchone()
    return bool(row and row["available"])


def build_conditions(filters, contributor_available):
    """Build parameterized SQL conditions referencing organization alias ``o``."""
    conditions = []
    params = []
    time_filter = filters["time_filter"]

    if time_filter == "7D":
        conditions.append("o.created_at >= CURRENT_DATE - INTERVAL '7 days'")
    elif time_filter == "30D":
        conditions.append("o.created_at >= CURRENT_DATE - INTERVAL '30 days'")
    elif time_filter == "1Y":
        conditions.append("o.created_at >= CURRENT_DATE - INTERVAL '1 year'")
    elif time_filter == "CUSTOM":
        conditions.append("o.created_at >= %s::date")
        conditions.append("o.created_at < %s::date + INTERVAL '1 day'")
        params.extend([filters["start_date"], filters["end_date"]])

    if filters["org_type"] is not None:
        conditions.append(f"{NORMALIZED_ORG_TYPE} = %s")
        params.append(filters["org_type"])
    if filters["org_size"] is not None:
        conditions.append(f"{NORMALIZED_ORG_SIZE} = %s")
        params.append(filters["org_size"])
    if filters["state_id"]:
        conditions.append("UPPER(o.state_id::text) = %s")
        params.append(filters["state_id"])
    if filters["city_name"]:
        conditions.append("LOWER(o.city_name) = LOWER(%s)")
        params.append(filters["city_name"])
    if filters["org_rating"] is not None:
        conditions.append("o.org_rating = %s")
        params.append(filters["org_rating"])
    if filters["is_collaborator"] is not None:
        conditions.append("o.is_collaborator IS NOT DISTINCT FROM %s")
        params.append(filters["is_collaborator"])
    if filters["is_contributor"] is not None:
        if not contributor_available:
            raise RequestValidationError(
                "is_contributor cannot be filtered because the column is not "
                "available in the current database schema."
            )
        conditions.append("o.is_contributor IS NOT DISTINCT FROM %s")
        params.append(filters["is_contributor"])

    return conditions, params


def where_clause(conditions):
    """Render a WHERE clause from trusted, internally generated conditions."""
    return f"WHERE {' AND '.join(conditions)}" if conditions else ""


def where_with_extra(conditions, extra_condition):
    """Render a WHERE clause plus one trusted metric-specific condition."""
    all_conditions = [*conditions, extra_condition]
    return where_clause(all_conditions)


def to_number(value):
    """Convert PostgreSQL numeric values to JSON-friendly int/float values."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def fetch_overview_summary(cursor, conditions, params, contributor_available):
    """Fetch all overview summary cards in one aggregate query."""
    if contributor_available:
        contributor_columns = """
            COUNT(*) FILTER (WHERE o.is_contributor IS TRUE)
                AS contributor_organizations,
            COUNT(*) FILTER (WHERE o.is_contributor IS NOT TRUE)
                AS non_contributor_organizations
        """
    else:
        contributor_columns = """
            NULL::bigint AS contributor_organizations,
            NULL::bigint AS non_contributor_organizations
        """

    cursor.execute(
        f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE {NORMALIZED_ORG_TYPE} = 'non_profit')
                AS non_profit_organizations,
            COUNT(*) FILTER (WHERE {NORMALIZED_ORG_TYPE} = 'for_profit')
                AS for_profit_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE)
                AS collaborator_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS NOT TRUE)
                AS non_collaborator_organizations,
            {contributor_columns}
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)};
        """,
        params,
    )
    row = cursor.fetchone()
    return {
        "total_organizations": int(row["total_organizations"] or 0),
        "non_profit_organizations": int(row["non_profit_organizations"] or 0),
        "for_profit_organizations": int(row["for_profit_organizations"] or 0),
        "collaborator_organizations": int(row["collaborator_organizations"] or 0),
        "non_collaborator_organizations": int(
            row["non_collaborator_organizations"] or 0
        ),
        "contributor_organizations": (
            int(row["contributor_organizations"] or 0)
            if contributor_available
            else None
        ),
        "non_contributor_organizations": (
            int(row["non_contributor_organizations"] or 0)
            if contributor_available
            else None
        ),
    }


def fetch_registration_trend(cursor, conditions, params, group_by):
    """Fetch new organization registrations grouped by the requested period."""
    period = VALID_GROUP_BY[group_by]
    cursor.execute(
        f"""
        SELECT DATE_TRUNC('{period}', o.created_at)::date AS period,
               COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_with_extra(conditions, 'o.created_at IS NOT NULL')}
        GROUP BY 1
        ORDER BY 1;
        """,
        params,
    )
    return [
        {"period": row["period"].isoformat(), "count": int(row["count"])}
        for row in cursor.fetchall()
    ]


def fetch_group_distribution(cursor, conditions, params, dimension):
    """Fetch normalized counts for organization type or size."""
    if dimension == "org_type":
        expression = NORMALIZED_ORG_TYPE
    elif dimension == "org_size":
        expression = NORMALIZED_ORG_SIZE
    else:
        raise ValueError("Unsupported organization dimension.")

    cursor.execute(
        f"""
        SELECT {expression} AS label, COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)}
        GROUP BY 1
        ORDER BY count DESC, label;
        """,
        params,
    )
    return [
        {dimension: row["label"], "count": int(row["count"])}
        for row in cursor.fetchall()
    ]


def fetch_organizations_by_location(cursor, conditions, params):
    """Fetch state and city distributions for the same filtered population."""
    cursor.execute(
        f"""
        SELECT o.state_id, COALESCE(s.state_name, o.state_id::text) AS state_name,
               COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        LEFT JOIN {STATE_TABLE} s ON s.state_id = o.state_id
        {where_clause(conditions)}
        GROUP BY o.state_id, s.state_name
        ORDER BY count DESC, state_name;
        """,
        params,
    )
    by_state = [
        {
            "state_id": row["state_id"],
            "state_name": row["state_name"],
            "count": int(row["count"]),
        }
        for row in cursor.fetchall()
    ]

    cursor.execute(
        f"""
        SELECT o.city_name, COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)}
        GROUP BY o.city_name
        ORDER BY count DESC, o.city_name;
        """,
        params,
    )
    by_city = [
        {"city_name": row["city_name"], "count": int(row["count"])}
        for row in cursor.fetchall()
    ]
    return {"by_state": by_state, "by_city": by_city}


def fetch_boolean_distribution(cursor, conditions, params, column_name):
    """Fetch true/false counts for an allow-listed organization flag."""
    if column_name not in {"is_collaborator", "is_contributor"}:
        raise ValueError("Unsupported boolean distribution.")
    cursor.execute(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE o.{column_name} IS TRUE) AS true_count,
            COUNT(*) FILTER (WHERE o.{column_name} IS NOT TRUE) AS false_count
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)};
        """,
        params,
    )
    row = cursor.fetchone()
    return [
        {column_name: True, "count": int(row["true_count"] or 0)},
        {column_name: False, "count": int(row["false_count"] or 0)},
    ]


def fetch_performance_summary(cursor, conditions, params):
    """Fetch the performance summary cards."""
    cursor.execute(
        f"""
        SELECT
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
            COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL)
                AS rated_organizations,
            COUNT(*) FILTER (WHERE o.org_rating IS NULL)
                AS unrated_organizations,
            COUNT(*) FILTER (WHERE o.org_rating = 5)
                AS five_star_organizations
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)};
        """,
        params,
    )
    row = cursor.fetchone()
    return {
        "average_rating": float(row["average_rating"] or 0),
        "rated_organizations": int(row["rated_organizations"] or 0),
        "unrated_organizations": int(row["unrated_organizations"] or 0),
        "five_star_organizations": int(row["five_star_organizations"] or 0),
    }


def fetch_rating_distribution(cursor, conditions, params):
    """Return all rating buckets from one to five, including zero-count buckets."""
    cursor.execute(
        f"""
        SELECT ratings.rating, COUNT(filtered.org_rating) AS count
        FROM GENERATE_SERIES(1, 5) AS ratings(rating)
        LEFT JOIN (
            SELECT o.org_rating
            FROM {ORGANIZATIONS_TABLE} o
            {where_with_extra(conditions, 'o.org_rating IS NOT NULL')}
        ) AS filtered ON filtered.org_rating::int = ratings.rating
        GROUP BY ratings.rating
        ORDER BY ratings.rating;
        """,
        params,
    )
    return [
        {"rating": int(row["rating"]), "count": int(row["count"])}
        for row in cursor.fetchall()
    ]


def fetch_top_organizations(cursor, conditions, params, flag_column=None):
    """Fetch the ten highest-rated organizations, optionally restricted by flag."""
    extra_conditions = ["o.org_rating IS NOT NULL"]
    if flag_column is not None:
        if flag_column not in {"is_collaborator", "is_contributor"}:
            raise ValueError("Unsupported top-organization flag.")
        extra_conditions.append(f"o.{flag_column} IS TRUE")

    cursor.execute(
        f"""
        SELECT o.org_id, o.org_name, o.org_rating,
               {NORMALIZED_ORG_TYPE} AS org_type,
               {NORMALIZED_ORG_SIZE} AS org_size,
               o.state_id, o.city_name
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause([*conditions, *extra_conditions])}
        ORDER BY o.org_rating DESC, o.org_name
        LIMIT %s;
        """,
        [*params, TOP_ORGANIZATION_LIMIT],
    )
    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "org_rating": to_number(row["org_rating"]),
            "org_type": row["org_type"],
            "org_size": row["org_size"],
            "state_id": row["state_id"],
            "city_name": row["city_name"],
        }
        for row in cursor.fetchall()
    ]


def fetch_ratings_by_dimension(cursor, conditions, params, dimension):
    """Fetch average ratings by normalized organization type or size."""
    if dimension == "org_type":
        expression = NORMALIZED_ORG_TYPE
    elif dimension == "org_size":
        expression = NORMALIZED_ORG_SIZE
    else:
        raise ValueError("Unsupported rating dimension.")

    cursor.execute(
        f"""
        SELECT {expression} AS label,
               ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
               COUNT(*) AS total_organizations,
               COUNT(o.org_rating) AS rated_organizations
        FROM {ORGANIZATIONS_TABLE} o
        {where_clause(conditions)}
        GROUP BY 1
        ORDER BY average_rating DESC NULLS LAST, label;
        """,
        params,
    )
    return [
        {
            dimension: row["label"],
            "average_rating": float(row["average_rating"] or 0),
            "total_organizations": int(row["total_organizations"]),
            "rated_organizations": int(row["rated_organizations"]),
        }
        for row in cursor.fetchall()
    ]


def run_metric(connection, label, default, callback):
    """Run one metric without allowing its failure to blank the dashboard."""
    try:
        return callback()
    except Exception:
        LOGGER.exception("Organization analytics metric failed: %s", label)
        try:
            connection.rollback()
        except Exception:
            LOGGER.exception("Database rollback failed after metric: %s", label)
        return default


def build_overview(connection, cursor, filters, contributor_available):
    """Build the Organization Overview dashboard response."""
    response = get_default_overview_response()
    dashboard = response["organization_overview"]
    conditions, params = build_conditions(filters, contributor_available)

    dashboard["summary"] = run_metric(
        connection,
        "overview.summary",
        dashboard["summary"],
        lambda: fetch_overview_summary(
            cursor, conditions, params, contributor_available
        ),
    )
    dashboard["organization_activity_trend"] = run_metric(
        connection,
        "overview.organization_activity_trend",
        [],
        lambda: fetch_registration_trend(
            cursor, conditions, params, filters["group_by"]
        ),
    )
    dashboard["organizations_by_type"] = run_metric(
        connection,
        "overview.organizations_by_type",
        [],
        lambda: fetch_group_distribution(
            cursor, conditions, params, "org_type"
        ),
    )
    dashboard["organizations_by_size"] = run_metric(
        connection,
        "overview.organizations_by_size",
        [],
        lambda: fetch_group_distribution(
            cursor, conditions, params, "org_size"
        ),
    )
    dashboard["organizations_by_location"] = run_metric(
        connection,
        "overview.organizations_by_location",
        {"by_state": [], "by_city": []},
        lambda: fetch_organizations_by_location(cursor, conditions, params),
    )
    dashboard["collaborator_distribution"] = run_metric(
        connection,
        "overview.collaborator_distribution",
        [],
        lambda: fetch_boolean_distribution(
            cursor, conditions, params, "is_collaborator"
        ),
    )
    if contributor_available:
        dashboard["contributor_distribution"] = run_metric(
            connection,
            "overview.contributor_distribution",
            [],
            lambda: fetch_boolean_distribution(
                cursor, conditions, params, "is_contributor"
            ),
        )
    else:
        dashboard["schema_notes"] = {
            "is_contributor": (
                "Contributor metrics are unavailable until is_contributor is "
                "added to the organizations table."
            )
        }
    return response


def build_performance(connection, cursor, filters, contributor_available):
    """Build the Organization Performance dashboard response."""
    response = get_default_performance_response()
    dashboard = response["organization_performance"]
    conditions, params = build_conditions(filters, contributor_available)

    dashboard["summary"] = run_metric(
        connection,
        "performance.summary",
        dashboard["summary"],
        lambda: fetch_performance_summary(cursor, conditions, params),
    )
    dashboard["rating_distribution"] = run_metric(
        connection,
        "performance.rating_distribution",
        [],
        lambda: fetch_rating_distribution(cursor, conditions, params),
    )
    dashboard["top_rated_organizations"] = run_metric(
        connection,
        "performance.top_rated_organizations",
        [],
        lambda: fetch_top_organizations(cursor, conditions, params),
    )
    dashboard["top_collaborator_organizations"] = run_metric(
        connection,
        "performance.top_collaborator_organizations",
        [],
        lambda: fetch_top_organizations(
            cursor, conditions, params, "is_collaborator"
        ),
    )
    if contributor_available:
        dashboard["top_contributor_organizations"] = run_metric(
            connection,
            "performance.top_contributor_organizations",
            [],
            lambda: fetch_top_organizations(
                cursor, conditions, params, "is_contributor"
            ),
        )
    else:
        dashboard["schema_notes"] = {
            "is_contributor": (
                "Top contributor organizations are unavailable until "
                "is_contributor is added to the organizations table."
            )
        }
    dashboard["ratings_by_organization_type"] = run_metric(
        connection,
        "performance.ratings_by_organization_type",
        [],
        lambda: fetch_ratings_by_dimension(
            cursor, conditions, params, "org_type"
        ),
    )
    dashboard["ratings_by_organization_size"] = run_metric(
        connection,
        "performance.ratings_by_organization_size",
        [],
        lambda: fetch_ratings_by_dimension(
            cursor, conditions, params, "org_size"
        ),
    )
    return response


def handle_dashboard(dashboard_type, request_body):
    """Validate, connect, and execute one dashboard request."""
    connection = None
    cursor = None
    fallback = (
        get_default_overview_response()
        if dashboard_type == "overview"
        else get_default_performance_response()
    )

    try:
        filters = parse_filters(request_body)
        connection = get_db_connection()
        from psycopg2.extras import RealDictCursor

        cursor = connection.cursor(cursor_factory=RealDictCursor)
        contributor_available = has_contributor_column(cursor)
        if dashboard_type == "overview":
            body = build_overview(
                connection, cursor, filters, contributor_available
            )
        else:
            body = build_performance(
                connection, cursor, filters, contributor_available
            )
        return build_response(200, body)
    except RequestValidationError as error:
        return build_response(400, {"error": str(error)})
    except Exception:
        LOGGER.exception("Organization analytics request failed")
        fallback["error"] = "Unable to query organization analytics."
        return build_response(500, fallback)
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def lambda_handler(event, context):
    """Serve ``POST /analytics/organizations`` using ``dashboard_type``."""
    try:
        request_body = parse_event_body(event)
        dashboard_type = str(
            request_body.get("dashboard_type", "overview")
        ).lower()
        if dashboard_type not in VALID_DASHBOARDS:
            raise RequestValidationError(
                "dashboard_type must be overview or performance."
            )
        return handle_dashboard(dashboard_type, request_body)
    except RequestValidationError as error:
        return build_response(400, {"error": str(error)})


def overview_handler(event, context):
    """Serve ``POST /analytics/organizations/overview``."""
    try:
        return handle_dashboard("overview", parse_event_body(event))
    except RequestValidationError as error:
        return build_response(400, {"error": str(error)})


def performance_handler(event, context):
    """Serve ``POST /analytics/organizations/performance``."""
    try:
        return handle_dashboard("performance", parse_event_body(event))
    except RequestValidationError as error:
        return build_response(400, {"error": str(error)})


if __name__ == "__main__":
    for selected_dashboard in ("overview", "performance"):
        result = lambda_handler(
            {
                "dashboard_type": selected_dashboard,
                "time_filter": "ALL",
                "group_by": "monthly",
            },
            None,
        )
        print(json.dumps(result, indent=2))
