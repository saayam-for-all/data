"""
Organization Analytics API (Lambda handler)

Provides all three tabs of the Saayam "Organization Dashboard" in a single
response from one endpoint: `POST /analytics/organizations`.

Follows the finalized dashboard requirements captured on issue #228:
  - summary                          (4 KPI cards)
  - growth_trend                     (org + collaborator growth over time)
  - organizations_by_location        (state -> nested cities, with %)
  - organizations_by_size            (small / medium / large)
  - collaborator_vs_contributor      (counts + percentages)
  - rating_distribution              (1-5 stars)
  - organization_type_distribution   (for-profit vs non-profit over time)

Connection:
  Per the issue's explicit note, this module does NOT use AWS Systems
  Manager Parameter Store. Credentials are read from `DATABASE_URL`, or
  from the individual `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` /
  `DB_PASSWORD` environment variables (with PG* as a fallback).

State table naming:
  `ddl_organizations.sql` declares the FK against `states` (plural), but
  a locally-available copy of the schema may only have `state` (singular,
  per `ddl_state.sql`) -- see the known DDL mismatch flagged on this issue.
  The table name is configurable via `STATE_TABLE_NAME` (defaults to the
  ticket-correct `states`) so this module works against either schema
  without code changes.

is_contributor:
  Not guaranteed to exist yet. Rather than guessing, this module checks
  `information_schema.columns` once per request and only includes
  contributor counts in queries when the column is actually present.
  When it's missing, contributor-related figures come back as `0`
  (or `0.0%`) instead of failing the request or fabricating data.
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

DB_SCHEMA = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")
STATE_TABLE_NAME = os.environ.get("STATE_TABLE_NAME", "states")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", DB_SCHEMA):
    raise ValueError("DB_SCHEMA must be a valid PostgreSQL identifier")
if STATE_TABLE_NAME not in ("state", "states"):
    raise ValueError("STATE_TABLE_NAME must be 'state' or 'states'")

ORGANIZATIONS_TABLE = f"{DB_SCHEMA}.organizations"
STATE_TABLE = f"{DB_SCHEMA}.{STATE_TABLE_NAME}"

TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
ORG_TYPES = {"for_profit", "non_profit"}
ORG_SIZES = ["small", "medium", "large"]
RATINGS = [1, 2, 3, 4, 5]

GROUP_BY_UNITS = {
    "daily": ("day", "YYYY-MM-DD"),
    "weekly": ("week", 'IYYY-"W"IW'),
    "monthly": ("month", "YYYY-MM"),
    "yearly": ("year", "YYYY"),
}

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


class InvalidFilterError(ValueError):
    """Raised when the request payload fails filter validation."""


# ---------------------------------------------------------------------------
# Response / connection helpers
# ---------------------------------------------------------------------------

def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body, default=_json_default),
    }


def get_default_response():
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


def get_db_connection():
    """Local/runtime Postgres connection only -- no AWS Parameter Store."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    return psycopg2.connect(
        host=os.environ.get("DB_HOST", os.environ.get("PGHOST", "localhost")),
        dbname=os.environ.get("DB_NAME", os.environ.get("PGDATABASE", "saayam")),
        user=os.environ.get("DB_USER", os.environ.get("PGUSER", "postgres")),
        password=os.environ.get("DB_PASSWORD", os.environ.get("PGPASSWORD", "")),
        port=int(os.environ.get("DB_PORT", os.environ.get("PGPORT", "5432"))),
    )


def parse_event_body(event):
    if not event:
        return {}
    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise InvalidFilterError("Request body must contain valid JSON") from exc
        if isinstance(parsed, dict):
            return parsed
    raise InvalidFilterError("Request body must be a JSON object")


# ---------------------------------------------------------------------------
# Filter validation
# ---------------------------------------------------------------------------

def _parse_iso_date(value, field_name):
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise InvalidFilterError(f"{field_name} must use YYYY-MM-DD format") from exc


def _normalize_org_type(value):
    return re.sub(r"[\s-]+", "_", str(value).strip().lower())


def validate_filters(payload):
    time_filter = str(payload.get("time_filter", "30D") or "30D").strip().upper()
    if time_filter not in TIME_FILTERS:
        raise InvalidFilterError("time_filter must be one of 7D, 30D, 1Y, ALL, CUSTOM")

    group_by = str(payload.get("group_by", "daily") or "daily").strip().lower()
    if group_by not in GROUP_BY_UNITS:
        raise InvalidFilterError("group_by must be one of daily, weekly, monthly, yearly")

    start_date = _parse_iso_date(payload.get("start_date"), "start_date")
    end_date = _parse_iso_date(payload.get("end_date"), "end_date")
    if time_filter == "CUSTOM":
        if start_date is None or end_date is None:
            raise InvalidFilterError("CUSTOM time_filter requires start_date and end_date")
        if start_date > end_date:
            raise InvalidFilterError("start_date cannot be after end_date")

    region = payload.get("region") or "ALL"
    region = str(region).strip() or "ALL"

    raw_org_type = payload.get("organization_type") or "ALL"
    organization_type = str(raw_org_type).strip()
    organization_type = (
        "ALL" if organization_type.upper() == "ALL" else _normalize_org_type(organization_type)
    )
    if organization_type != "ALL" and organization_type not in ORG_TYPES:
        raise InvalidFilterError("organization_type must be ALL, for_profit, or non_profit")

    return {
        "time_filter": time_filter,
        "start_date": start_date,
        "end_date": end_date,
        "group_by": group_by,
        "region": region,
        "organization_type": organization_type,
    }


# ---------------------------------------------------------------------------
# SQL condition builders
# ---------------------------------------------------------------------------

def _window_condition(filters):
    """SQL condition + params restricting rows to the selected time window."""
    time_filter = filters["time_filter"]
    if time_filter == "7D":
        return "o.created_at >= CURRENT_DATE - INTERVAL '7 days'", {}
    if time_filter == "30D":
        return "o.created_at >= CURRENT_DATE - INTERVAL '30 days'", {}
    if time_filter == "1Y":
        return "o.created_at >= CURRENT_DATE - INTERVAL '1 year'", {}
    if time_filter == "CUSTOM":
        return (
            "o.created_at >= %(start_date)s AND o.created_at < %(end_exclusive)s",
            {
                "start_date": filters["start_date"],
                "end_exclusive": filters["end_date"] + timedelta(days=1),
            },
        )
    return "", {}  # ALL


def _window_start_bound(filters):
    """The lower-bound expression/params used to compute a "before window" baseline."""
    time_filter = filters["time_filter"]
    if time_filter == "7D":
        return "CURRENT_DATE - INTERVAL '7 days'", {}
    if time_filter == "30D":
        return "CURRENT_DATE - INTERVAL '30 days'", {}
    if time_filter == "1Y":
        return "CURRENT_DATE - INTERVAL '1 year'", {}
    if time_filter == "CUSTOM":
        return "%(start_date)s", {"start_date": filters["start_date"]}
    return None, {}  # ALL has no baseline period


def _shared_conditions(filters):
    """Region / organization_type conditions applied to every query."""
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
            "LOWER(REGEXP_REPLACE(TRIM(o.org_type::text), '[\\s-]+', '_', 'g')) = %(org_type)s"
        )
        params["org_type"] = filters["organization_type"]

    return conditions, params


def _where(conditions):
    return f"WHERE {' AND '.join(conditions)}" if conditions else ""


def _base_from():
    return (
        f"FROM {ORGANIZATIONS_TABLE} o "
        f"LEFT JOIN {STATE_TABLE} s ON o.state_id = s.state_id"
    )


def _filtered_where(filters, include_window=True):
    conditions, params = _shared_conditions(filters)
    if include_window:
        window_sql, window_params = _window_condition(filters)
        if window_sql:
            conditions.insert(0, window_sql)
        params.update(window_params)
    return _where(conditions), params


# ---------------------------------------------------------------------------
# Contributor-column detection
# ---------------------------------------------------------------------------

def has_contributor_column(cursor):
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = 'organizations'
          AND column_name = 'is_contributor'
        LIMIT 1
        """,
        (DB_SCHEMA,),
    )
    return cursor.fetchone() is not None


# ---------------------------------------------------------------------------
# Metric fetchers
# ---------------------------------------------------------------------------

def fetch_summary(cursor, filters, contributor_available):
    where_sql, params = _filtered_where(filters)
    contributor_expr = (
        "COUNT(*) FILTER (WHERE o.is_contributor IS TRUE)" if contributor_available else "0"
    )
    cursor.execute(
        f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS total_collaborators,
            {contributor_expr} AS total_contributors,
            ROUND(AVG(o.org_rating)::numeric, 2) AS average_org_rating
        {_base_from()}
        {where_sql}
        """,
        params,
    )
    row = cursor.fetchone()
    rating = row["average_org_rating"]
    return {
        "total_organizations": int(row["total_organizations"] or 0),
        "total_collaborators": int(row["total_collaborators"] or 0),
        "total_contributors": int(row["total_contributors"] or 0),
        "average_org_rating": float(rating) if rating is not None else 0.0,
    }


def _period_counts(cursor, filters, select_exprs):
    """
    Shared helper: returns (baseline_row, [period_rows]) where baseline_row
    is the pre-window totals (for cumulative "growth" math) and period_rows
    are the new-in-period counts, ordered chronologically.
    `select_exprs` is a dict of {output_name: SQL aggregate expression}.
    """
    trunc_unit, date_format = GROUP_BY_UNITS[filters["group_by"]]
    select_list = ",\n            ".join(f"{expr} AS {name}" for name, expr in select_exprs.items())

    baseline_row = {name: 0 for name in select_exprs}
    lower_bound_sql, lower_bound_params = _window_start_bound(filters)
    if lower_bound_sql is not None:
        shared_conditions, shared_params = _shared_conditions(filters)
        baseline_conditions = shared_conditions + [f"o.created_at < {lower_bound_sql}"]
        baseline_params = {**shared_params, **lower_bound_params}
        cursor.execute(
            f"""
            SELECT {select_list}
            {_base_from()}
            {_where(baseline_conditions)}
            """,
            baseline_params,
        )
        fetched = cursor.fetchone()
        if fetched:
            baseline_row = {name: int(fetched[name] or 0) for name in select_exprs}

    where_sql, params = _filtered_where(filters)
    cursor.execute(
        f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{trunc_unit}', o.created_at), '{date_format}') AS period,
            DATE_TRUNC('{trunc_unit}', o.created_at) AS period_start,
            {select_list}
        {_base_from()}
        {where_sql}
        GROUP BY 1, 2
        ORDER BY 2
        """,
        params,
    )
    period_rows = cursor.fetchall()
    return baseline_row, period_rows


def fetch_growth_trend(cursor, filters):
    baseline, period_rows = _period_counts(
        cursor,
        filters,
        {
            "total_organizations": "COUNT(*)",
            "total_collaborators": "COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE)",
        },
    )
    running_orgs = baseline["total_organizations"]
    running_collaborators = baseline["total_collaborators"]
    trend = []
    for row in period_rows:
        running_orgs += int(row["total_organizations"] or 0)
        running_collaborators += int(row["total_collaborators"] or 0)
        trend.append(
            {
                "period": row["period"],
                "total_organizations": running_orgs,
                "total_collaborators": running_collaborators,
            }
        )
    return trend


def fetch_organization_type_distribution(cursor, filters):
    normalized_type = "LOWER(REGEXP_REPLACE(TRIM(o.org_type::text), '[\\s-]+', '_', 'g'))"
    baseline, period_rows = _period_counts(
        cursor,
        filters,
        {
            "for_profit": f"COUNT(*) FILTER (WHERE {normalized_type} = 'for_profit')",
            "non_profit": f"COUNT(*) FILTER (WHERE {normalized_type} = 'non_profit')",
        },
    )
    running_for_profit = baseline["for_profit"]
    running_non_profit = baseline["non_profit"]
    trend = []
    for row in period_rows:
        running_for_profit += int(row["for_profit"] or 0)
        running_non_profit += int(row["non_profit"] or 0)
        trend.append(
            {
                "period": row["period"],
                "for_profit": running_for_profit,
                "non_profit": running_non_profit,
                "total": running_for_profit + running_non_profit,
            }
        )
    return trend


def fetch_organizations_by_location(cursor, filters):
    where_sql, params = _filtered_where(filters)
    cursor.execute(
        f"""
        SELECT
            COALESCE(s.state_id::text, o.state_id::text, 'UNKNOWN') AS state_id,
            COALESCE(s.state_name, 'Unknown') AS state_name,
            COALESCE(NULLIF(TRIM(o.city_name), ''), 'Unknown') AS city_name,
            COUNT(*) AS organization_count
        {_base_from()}
        {where_sql}
        GROUP BY 1, 2, 3
        """,
        params,
    )
    rows = cursor.fetchall()

    states = {}
    grand_total = 0
    for row in rows:
        count = int(row["organization_count"] or 0)
        grand_total += count
        state_id = row["state_id"]
        state = states.setdefault(
            state_id,
            {"state_id": state_id, "state_name": row["state_name"], "count": 0, "cities": []},
        )
        state["count"] += count
        state["cities"].append({"city_name": row["city_name"], "organization_count": count})

    result = []
    for state in states.values():
        state["cities"].sort(key=lambda c: c["organization_count"], reverse=True)
        percentage = round(state["count"] * 100.0 / grand_total, 1) if grand_total else 0.0
        result.append(
            {
                "state_id": state["state_id"],
                "state_name": state["state_name"],
                "organization_count": state["count"],
                "percentage": percentage,
                "cities": state["cities"],
            }
        )
    result.sort(key=lambda s: s["organization_count"], reverse=True)
    return result


def fetch_organizations_by_size(cursor, filters):
    where_sql, params = _filtered_where(filters)
    cursor.execute(
        f"""
        SELECT LOWER(TRIM(o.org_size::text)) AS org_size, COUNT(*) AS organization_count
        {_base_from()}
        {where_sql}
        GROUP BY 1
        """,
        params,
    )
    counts = {row["org_size"]: int(row["organization_count"] or 0) for row in cursor.fetchall()}
    return [{"org_size": size, "organization_count": counts.get(size, 0)} for size in ORG_SIZES]


def fetch_collaborator_vs_contributor(cursor, filters, contributor_available):
    where_sql, params = _filtered_where(filters)
    contributor_expr = (
        "COUNT(*) FILTER (WHERE o.is_contributor IS TRUE)" if contributor_available else "0"
    )
    cursor.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborators,
            {contributor_expr} AS contributors
        {_base_from()}
        {where_sql}
        """,
        params,
    )
    row = cursor.fetchone()
    total = int(row["total"] or 0)
    collaborators = int(row["collaborators"] or 0)
    contributors = int(row["contributors"] or 0)

    def pct(count):
        return round(count * 100.0 / total, 1) if total else 0.0

    return [
        {"type": "collaborator", "organization_count": collaborators, "percentage": pct(collaborators)},
        {"type": "contributor", "organization_count": contributors, "percentage": pct(contributors)},
    ]


def fetch_rating_distribution(cursor, filters):
    # Built explicitly (rather than via _filtered_where) so the
    # rating-not-null condition combines correctly whether or not other
    # filters are already present.
    conditions, params = _shared_conditions(filters)
    window_sql, window_params = _window_condition(filters)
    if window_sql:
        conditions.insert(0, window_sql)
    params.update(window_params)
    conditions.append("o.org_rating IS NOT NULL")

    cursor.execute(
        f"""
        SELECT o.org_rating AS rating, COUNT(*) AS organization_count
        {_base_from()}
        {_where(conditions)}
        GROUP BY 1
        """,
        params,
    )
    counts = {int(row["rating"]): int(row["organization_count"] or 0) for row in cursor.fetchall()}
    return [{"rating": rating, "organization_count": counts.get(rating, 0)} for rating in RATINGS]


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def _run_metric(label, default, connection, fn):
    try:
        return fn()
    except Exception as error:
        LOGGER.warning("organization_analytics: %s failed: %s", label, error)
        try:
            connection.rollback()
        except Exception as rollback_error:
            LOGGER.warning("organization_analytics: rollback after %s failed: %s", label, rollback_error)
        return default


def lambda_handler(event, context):
    response_body = get_default_response()

    try:
        payload = parse_event_body(event)
        filters = validate_filters(payload)
    except InvalidFilterError as error:
        return build_response(400, {"error": str(error), **response_body})

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=RealDictCursor)

        contributor_available = _run_metric(
            "contributor_column_check", False, connection, lambda: has_contributor_column(cursor)
        )

        response_body["summary"] = _run_metric(
            "summary", response_body["summary"], connection,
            lambda: fetch_summary(cursor, filters, contributor_available),
        )
        response_body["growth_trend"] = _run_metric(
            "growth_trend", [], connection, lambda: fetch_growth_trend(cursor, filters)
        )
        response_body["organizations_by_location"] = _run_metric(
            "organizations_by_location", [], connection,
            lambda: fetch_organizations_by_location(cursor, filters),
        )
        response_body["organizations_by_size"] = _run_metric(
            "organizations_by_size", [], connection, lambda: fetch_organizations_by_size(cursor, filters)
        )
        response_body["collaborator_vs_contributor"] = _run_metric(
            "collaborator_vs_contributor", [], connection,
            lambda: fetch_collaborator_vs_contributor(cursor, filters, contributor_available),
        )
        response_body["rating_distribution"] = _run_metric(
            "rating_distribution", [], connection, lambda: fetch_rating_distribution(cursor, filters)
        )
        response_body["organization_type_distribution"] = _run_metric(
            "organization_type_distribution", [], connection,
            lambda: fetch_organization_type_distribution(cursor, filters),
        )

        return build_response(200, response_body)

    except Exception as error:
        LOGGER.error("organization_analytics: database connection failed: %s", error)
        return build_response(500, response_body)

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# ---------------------------------------------------------------------------
# Local testing
#
#   export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/saayam
#   # or export DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD
#   # export STATE_TABLE_NAME=state   (only if your local schema is singular)
#   python organization_analytics.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_scenarios = [
        ("Default (30D, daily)", {}),
        ("ALL time, monthly", {"time_filter": "ALL", "group_by": "monthly"}),
        ("Region + org type filter", {"time_filter": "1Y", "group_by": "monthly", "region": "Virginia", "organization_type": "non_profit"}),
        ("CUSTOM range", {"time_filter": "CUSTOM", "start_date": "2025-01-01", "end_date": "2026-08-25", "group_by": "yearly"}),
        ("Invalid time_filter", {"time_filter": "5Y"}),
    ]

    print("=" * 70)
    print("LOCAL TESTING - organization_analytics.py")
    print("=" * 70)

    for label, payload in test_scenarios:
        print(f"\n--- Scenario: {label} ---")
        result = lambda_handler({"body": json.dumps(payload)}, None)
        print(f"statusCode: {result['statusCode']}")
        print(json.dumps(json.loads(result["body"]), indent=2))

    print("\n" + "=" * 70)
    print("LOCAL TESTING COMPLETE")
    print("=" * 70)
