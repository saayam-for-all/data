"""Organization Analytics API for the Saayam Organization Dashboard.

Endpoint: POST /analytics/organizations

Returns every dashboard section in one response:

- summary (KPI cards)
- growth_trend
- organizations_by_location
- organizations_by_size
- collaborator_vs_contributor
- rating_distribution
- organization_type_distribution

Database credentials come from local environment variables / DATABASE_URL.
AWS Parameter Store is not used.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from urllib.parse import unquote

import psycopg2
from psycopg2.extras import RealDictCursor

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ORGANIZATIONS_TABLE = f"{SCHEMA_NAME}.organizations"
# Sample data in this repo is state.csv / volunteer analytics use `.state`.
# The issue text says `states`; override with ORG_STATE_TABLE if needed.
STATE_TABLE = os.getenv("ORG_STATE_TABLE", f"{SCHEMA_NAME}.state")

VALID_TIME_FILTERS = ("7D", "30D", "1Y", "ALL", "CUSTOM")
GROUP_BY_MAP = {
    "daily": ("day", "YYYY-MM-DD"),
    "weekly": ("week", 'IYYY-"W"IW'),
    "monthly": ("month", "YYYY-MM"),
    "yearly": ("year", "YYYY"),
}
VALID_ORG_TYPES = ("for_profit", "non_profit")
ORG_SIZES = ("small", "medium", "large")
RATING_BUCKETS = (1, 2, 3, 4, 5)
ALL_SENTINEL = "ALL"
DATE_INTERVALS = {
    "7D": "7 days",
    "30D": "30 days",
    "1Y": "1 year",
}

# CSV / DB values are "Non-Profit", "For-profit", "Small"; API contract uses
# for_profit / non_profit and lowercase sizes.
SQL_ORG_TYPE = "REPLACE(LOWER(TRIM(o.org_type::text)), '-', '_')"
SQL_ORG_SIZE = "LOWER(TRIM(o.org_size::text))"
SQL_IS_COLLABORATOR = "UPPER(TRIM(o.is_collaborator::text)) IN ('TRUE', 'T', '1')"
SQL_IS_CONTRIBUTOR = "UPPER(TRIM(o.is_contributor::text)) IN ('TRUE', 'T', '1')"
SQL_RATING = "NULLIF(TRIM(o.org_rating::text), '')::numeric"


class FilterValidationError(ValueError):
    """Raised when the request payload contains an unusable filter."""


def parse_event_body(event):
    """Return the payload for both API Gateway and direct Lambda invocations."""
    if not event:
        return {}

    body = event.get("body") if isinstance(event, dict) else None
    if body is None:
        return event if isinstance(event, dict) else {}
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body, dict):
        return body
    return {}


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


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }


def get_db_connection():
    """Open a local PostgreSQL connection. Never reads AWS Parameter Store."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    kwargs = {
        "host": os.getenv("PGHOST", "localhost"),
        "port": os.getenv("PGPORT", "5432"),
        "dbname": os.getenv("PGDATABASE", os.getenv("POSTGRES_DB", "saayam")),
        "user": os.getenv("PGUSER", os.getenv("POSTGRES_USER", "postgres")),
        "password": os.getenv("PGPASSWORD", os.getenv("POSTGRES_PASSWORD", "")),
        "connect_timeout": int(os.getenv("PGCONNECT_TIMEOUT", "10")),
    }
    sslmode = os.getenv("PGSSLMODE")
    if sslmode:
        kwargs["sslmode"] = sslmode
    return psycopg2.connect(**kwargs)


def _parse_date(value, field):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise FilterValidationError(
            f"{field} must be a date in YYYY-MM-DD format."
        ) from exc


def parse_filters(body):
    """Validate common dashboard filters used by Request/Volunteer/KPI APIs."""
    body = body or {}

    time_filter = str(body.get("time_filter") or ALL_SENTINEL).strip().upper()
    if time_filter not in VALID_TIME_FILTERS:
        raise FilterValidationError(
            f"time_filter must be one of {', '.join(VALID_TIME_FILTERS)}."
        )

    group_by = str(body.get("group_by") or "monthly").strip().lower()
    if group_by not in GROUP_BY_MAP:
        raise FilterValidationError(
            f"group_by must be one of {', '.join(sorted(GROUP_BY_MAP))}."
        )

    start_date = body.get("start_date")
    end_date = body.get("end_date")
    if time_filter == "CUSTOM":
        if not start_date or not end_date:
            raise FilterValidationError(
                "start_date and end_date are both required when time_filter is CUSTOM."
            )
        start = _parse_date(start_date, "start_date")
        end = _parse_date(end_date, "end_date")
        if start > end:
            raise FilterValidationError("start_date must not be after end_date.")
        start_date, end_date = start.isoformat(), end.isoformat()
    else:
        start_date = end_date = None

    region = str(body.get("region") or ALL_SENTINEL).strip()
    if region.upper() == ALL_SENTINEL:
        region = ALL_SENTINEL
    else:
        region = unquote(region)

    organization_type = str(
        body.get("organization_type") or ALL_SENTINEL
    ).strip().lower()
    if organization_type == ALL_SENTINEL.lower():
        organization_type = ALL_SENTINEL
    elif organization_type not in VALID_ORG_TYPES:
        raise FilterValidationError(
            "organization_type must be ALL, for_profit, or non_profit."
        )

    return {
        "time_filter": time_filter,
        "group_by": group_by,
        "start_date": start_date,
        "end_date": end_date,
        "region": region,
        "organization_type": organization_type,
    }


def get_grouping(group_by):
    try:
        return GROUP_BY_MAP[group_by]
    except KeyError as exc:
        raise FilterValidationError(
            f"group_by must be one of {', '.join(sorted(GROUP_BY_MAP))}."
        ) from exc


def build_filter_clause(filters, state_table=STATE_TABLE):
    """Shared WHERE fragment for every dashboard query.

    Returns (sql starting with AND or empty, params). Date range, region, and
    organization_type apply to KPI cards and all charts.
    """
    clauses = []
    params = []

    time_filter = filters["time_filter"]
    if time_filter in DATE_INTERVALS:
        clauses.append(
            f"o.created_at >= CURRENT_DATE - INTERVAL '{DATE_INTERVALS[time_filter]}'"
        )
    elif time_filter == "CUSTOM":
        clauses.append("o.created_at >= %s::date")
        clauses.append("o.created_at < (%s::date + INTERVAL '1 day')")
        params.extend([filters["start_date"], filters["end_date"]])

    if filters["region"] != ALL_SENTINEL:
        clauses.append(
            f"""(
                UPPER(TRIM(o.state_id::text)) = UPPER(%s)
                OR EXISTS (
                    SELECT 1
                    FROM {state_table} s_filter
                    WHERE TRIM(o.state_id::text) = TRIM(s_filter.state_id::text)
                      AND UPPER(TRIM(s_filter.state_name::text)) = UPPER(%s)
                )
            )"""
        )
        params.extend([filters["region"], filters["region"]])

    if filters["organization_type"] != ALL_SENTINEL:
        clauses.append(f"{SQL_ORG_TYPE} = %s")
        params.append(filters["organization_type"])

    if not clauses:
        return "", []
    return "AND " + " AND ".join(clauses), params


def has_column(cursor, qualified_table, column):
    """True when column exists. is_contributor may be missing in dev."""
    schema, _, table = qualified_table.partition(".")
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = %s
        """,
        (schema, table, column),
    )
    return cursor.fetchone() is not None


def _value(row, key, index):
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


def _percentage(count, total):
    if not total:
        return 0.0
    return round(count * 100.0 / total, 1)


def fetch_summary_counts(cursor, filters, contributor_supported=True):
    filter_sql, params = build_filter_clause(filters)
    contributor_expr = (
        f"COUNT(*) FILTER (WHERE {SQL_IS_CONTRIBUTOR})"
        if contributor_supported
        else "0"
    )
    query = f"""
        SELECT
            COUNT(*) AS total_organizations,
            COUNT(*) FILTER (WHERE {SQL_IS_COLLABORATOR}) AS total_collaborators,
            {contributor_expr} AS total_contributors,
            COALESCE(SUM({SQL_RATING}), 0) AS rating_sum,
            COUNT({SQL_RATING}) AS rating_count
        FROM {ORGANIZATIONS_TABLE} o
        WHERE 1=1
        {filter_sql};
    """
    cursor.execute(query, params)
    row = cursor.fetchone()
    if row is None:
        return {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "rating_sum": 0.0,
            "rating_count": 0,
        }
    return {
        "total_organizations": int(_value(row, "total_organizations", 0) or 0),
        "total_collaborators": int(_value(row, "total_collaborators", 1) or 0),
        "total_contributors": int(_value(row, "total_contributors", 2) or 0),
        "rating_sum": float(_value(row, "rating_sum", 3) or 0),
        "rating_count": int(_value(row, "rating_count", 4) or 0),
    }


def fetch_growth_buckets(cursor, filters):
    period, date_format = get_grouping(filters["group_by"])
    filter_sql, params = build_filter_clause(filters)
    query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
            COUNT(*) AS new_organizations,
            COUNT(*) FILTER (WHERE {SQL_IS_COLLABORATOR}) AS new_collaborators
        FROM {ORGANIZATIONS_TABLE} o
        WHERE o.created_at IS NOT NULL
        {filter_sql}
        GROUP BY 1
        ORDER BY 1;
    """
    cursor.execute(query, params)
    return [
        {
            "period": _value(row, "period", 0),
            "new_organizations": int(_value(row, "new_organizations", 1) or 0),
            "new_collaborators": int(_value(row, "new_collaborators", 2) or 0),
        }
        for row in cursor.fetchall()
    ]


def fetch_location_buckets(cursor, filters):
    filter_sql, params = build_filter_clause(filters)
    query = f"""
        SELECT
            COALESCE(NULLIF(TRIM(o.state_id::text), ''), 'Unknown') AS state_id,
            COALESCE(NULLIF(TRIM(s.state_name::text), ''), 'Unknown') AS state_name,
            COALESCE(NULLIF(TRIM(o.city_name::text), ''), 'Unknown') AS city_name,
            COUNT(*) AS organization_count
        FROM {ORGANIZATIONS_TABLE} o
        LEFT JOIN {STATE_TABLE} s
            ON TRIM(o.state_id::text) = TRIM(s.state_id::text)
        WHERE 1=1
        {filter_sql}
        GROUP BY 1, 2, 3
        ORDER BY 4 DESC, 1 ASC, 3 ASC;
    """
    cursor.execute(query, params)
    return [
        {
            "state_id": _value(row, "state_id", 0),
            "state_name": _value(row, "state_name", 1),
            "city_name": _value(row, "city_name", 2),
            "organization_count": int(_value(row, "organization_count", 3) or 0),
        }
        for row in cursor.fetchall()
    ]


def fetch_size_buckets(cursor, filters):
    filter_sql, params = build_filter_clause(filters)
    query = f"""
        SELECT
            COALESCE(NULLIF({SQL_ORG_SIZE}, ''), 'unknown') AS org_size,
            COUNT(*) AS organization_count
        FROM {ORGANIZATIONS_TABLE} o
        WHERE 1=1
        {filter_sql}
        GROUP BY 1
        ORDER BY 1;
    """
    cursor.execute(query, params)
    return {
        _value(row, "org_size", 0): int(_value(row, "organization_count", 1) or 0)
        for row in cursor.fetchall()
    }


def fetch_rating_buckets(cursor, filters):
    filter_sql, params = build_filter_clause(filters)
    query = f"""
        SELECT
            ROUND({SQL_RATING})::int AS rating,
            COUNT(*) AS organization_count
        FROM {ORGANIZATIONS_TABLE} o
        WHERE {SQL_RATING} IS NOT NULL
          AND ROUND({SQL_RATING})::int BETWEEN 1 AND 5
        {filter_sql}
        GROUP BY 1
        ORDER BY 1;
    """
    cursor.execute(query, params)
    return {
        int(_value(row, "rating", 0)): int(_value(row, "organization_count", 1) or 0)
        for row in cursor.fetchall()
    }


def fetch_org_type_buckets(cursor, filters):
    period, date_format = get_grouping(filters["group_by"])
    filter_sql, params = build_filter_clause(filters)
    query = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
            COUNT(*) FILTER (WHERE {SQL_ORG_TYPE} = 'for_profit') AS for_profit,
            COUNT(*) FILTER (WHERE {SQL_ORG_TYPE} = 'non_profit') AS non_profit
        FROM {ORGANIZATIONS_TABLE} o
        WHERE o.created_at IS NOT NULL
        {filter_sql}
        GROUP BY 1
        ORDER BY 1;
    """
    cursor.execute(query, params)
    return [
        {
            "period": _value(row, "period", 0),
            "for_profit": int(_value(row, "for_profit", 1) or 0),
            "non_profit": int(_value(row, "non_profit", 2) or 0),
        }
        for row in cursor.fetchall()
    ]


def build_summary(counts):
    rating_count = counts["rating_count"]
    return {
        "total_organizations": counts["total_organizations"],
        "total_collaborators": counts["total_collaborators"],
        "total_contributors": counts["total_contributors"],
        "average_org_rating": (
            round(counts["rating_sum"] / rating_count, 1) if rating_count else 0.0
        ),
    }


def build_growth_trend(buckets):
    """Cumulative organizations / collaborators within the filtered window."""
    running_orgs = 0
    running_collaborators = 0
    trend = []
    for row in buckets:
        running_orgs += int(row.get("new_organizations") or 0)
        running_collaborators += int(row.get("new_collaborators") or 0)
        trend.append(
            {
                "period": row["period"],
                "total_organizations": running_orgs,
                "total_collaborators": running_collaborators,
            }
        )
    return trend


def build_organizations_by_location(buckets, total_organizations):
    states = {}
    for row in buckets:
        state = states.setdefault(
            row["state_id"],
            {
                "state_id": row["state_id"],
                "state_name": row["state_name"],
                "organization_count": 0,
                "cities": {},
            },
        )
        state["organization_count"] += row["organization_count"]
        state["cities"][row["city_name"]] = (
            state["cities"].get(row["city_name"], 0) + row["organization_count"]
        )

    result = []
    for state in states.values():
        cities = [
            {"city_name": city, "organization_count": count}
            for city, count in sorted(
                state["cities"].items(), key=lambda item: (-item[1], item[0])
            )
        ]
        result.append(
            {
                "state_id": state["state_id"],
                "state_name": state["state_name"],
                "organization_count": state["organization_count"],
                "percentage": _percentage(
                    state["organization_count"], total_organizations
                ),
                "cities": cities,
            }
        )
    result.sort(key=lambda row: (-row["organization_count"], row["state_id"]))
    return result


def build_organizations_by_size(size_counts):
    rows = [
        {"org_size": size, "organization_count": int(size_counts.get(size, 0))}
        for size in ORG_SIZES
    ]
    extras = sorted(set(size_counts) - set(ORG_SIZES))
    rows.extend(
        {"org_size": size, "organization_count": int(size_counts[size])}
        for size in extras
    )
    return rows


def build_collaborator_vs_contributor(summary, contributor_supported=True):
    """Always return both types so the dashboard chart has a stable shape.

    If ``is_contributor`` is missing from the database, contributor count is 0.
    """
    total = summary["total_organizations"]
    contributor_count = (
        summary["total_contributors"] if contributor_supported else 0
    )
    return [
        {
            "type": "collaborator",
            "organization_count": summary["total_collaborators"],
            "percentage": _percentage(summary["total_collaborators"], total),
        },
        {
            "type": "contributor",
            "organization_count": contributor_count,
            "percentage": _percentage(contributor_count, total),
        },
    ]


def build_rating_distribution(rating_counts):
    return [
        {"rating": rating, "organization_count": int(rating_counts.get(rating, 0))}
        for rating in RATING_BUCKETS
    ]


def build_organization_type_distribution(buckets):
    running_for_profit = 0
    running_non_profit = 0
    distribution = []
    for row in buckets:
        running_for_profit += int(row.get("for_profit") or 0)
        running_non_profit += int(row.get("non_profit") or 0)
        distribution.append(
            {
                "period": row["period"],
                "for_profit": running_for_profit,
                "non_profit": running_non_profit,
                "total": running_for_profit + running_non_profit,
            }
        )
    return distribution


def collect_dashboard(cursor, filters):
    contributor_supported = has_column(cursor, ORGANIZATIONS_TABLE, "is_contributor")
    summary_counts = fetch_summary_counts(cursor, filters, contributor_supported)
    summary = build_summary(summary_counts)
    return {
        "summary": summary,
        "growth_trend": build_growth_trend(fetch_growth_buckets(cursor, filters)),
        "organizations_by_location": build_organizations_by_location(
            fetch_location_buckets(cursor, filters),
            summary["total_organizations"],
        ),
        "organizations_by_size": build_organizations_by_size(
            fetch_size_buckets(cursor, filters)
        ),
        "collaborator_vs_contributor": build_collaborator_vs_contributor(
            summary, contributor_supported
        ),
        "rating_distribution": build_rating_distribution(
            fetch_rating_buckets(cursor, filters)
        ),
        "organization_type_distribution": build_organization_type_distribution(
            fetch_org_type_buckets(cursor, filters)
        ),
    }


def lambda_handler(event, context):
    """Entry point for POST /analytics/organizations."""
    try:
        filters = parse_filters(parse_event_body(event))
    except FilterValidationError as exc:
        body = get_default_response()
        body["error"] = str(exc)
        return build_response(400, body)

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        return build_response(200, collect_dashboard(cursor, filters))
    except Exception as exc:  # noqa: BLE001 - dashboard must not crash
        print(f"Organization analytics failed: {exc}")
        return build_response(500, get_default_response())
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    sample_event = {
        "time_filter": "30D",
        "start_date": None,
        "end_date": None,
        "group_by": "daily",
        "region": "ALL",
        "organization_type": "ALL",
    }
    result = lambda_handler(sample_event, None)
    print(json.dumps(json.loads(result["body"]), indent=2))
