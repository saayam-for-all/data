"""Organization Analytics API for the Saayam Super Admin dashboard.

Single endpoint (``POST /analytics/organizations``) that populates all three
tabs of the Organization Dashboard:

    Tab 1  Growth & Location  -> growth_trend, organizations_by_location
    Tab 2  Size & Contribution-> organizations_by_size, collaborator_vs_contributor
    Tab 3  Ratings & Type     -> rating_distribution, organization_type_distribution

Plus the four common KPI cards under ``summary``.

Design decisions that are NOT derivable from the source documentation were
confirmed with the task owner; each is called out in a ``DECISION:`` comment so
the reasoning stays traceable during review.

Database credentials come from environment variables only. AWS Parameter Store
is deliberately not used here (explicit requirement of the task), unlike the
older analytics lambdas in this folder.
"""

import getpass
import json
import os
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor

# --------------------------------------------------------------------------- #
# Table constants
# --------------------------------------------------------------------------- #
# Naming follows volunteer_application_analytics.py.
REAL_TABLE_ORGANIZATIONS_VIRGINIA = "virginia_dev_saayam_rdbms.organizations"
REAL_TABLE_STATE_VIRGINIA = "virginia_dev_saayam_rdbms.state"

REAL_TABLE_ORGANIZATIONS_IRELAND = "ireland_dev_saayam_rdbms.organizations"
REAL_TABLE_STATE_IRELAND = "ireland_dev_saayam_rdbms.state"

# DECISION: query Virginia and Ireland and merge, mirroring
# volunteer_application_analytics.py. The task doc names only the Virginia
# tables, so Ireland is optional: it is queried only when IRELAND_PGHOST is set.
REGIONS = (
    {
        "name": "Virginia",
        "env_prefix": "",
        "organizations": REAL_TABLE_ORGANIZATIONS_VIRGINIA,
        "state": REAL_TABLE_STATE_VIRGINIA,
    },
    {
        "name": "Ireland",
        "env_prefix": "IRELAND_",
        "organizations": REAL_TABLE_ORGANIZATIONS_IRELAND,
        "state": REAL_TABLE_STATE_IRELAND,
    },
)

# --------------------------------------------------------------------------- #
# Filter vocabulary
# --------------------------------------------------------------------------- #
VALID_TIME_FILTERS = ("7D", "30D", "1Y", "ALL", "CUSTOM")

# group_by -> (date_trunc unit, to_char format). Whitelisted because both values
# are interpolated into SQL text; callers can never inject arbitrary strings.
GROUP_BY_MAP = {
    "daily": ("day", "YYYY-MM-DD"),
    "weekly": ("week", 'IYYY-"W"IW'),   # DECISION: ISO week label, e.g. 2026-W03
    "monthly": ("month", "YYYY-MM"),
    "yearly": ("year", "YYYY"),
}

VALID_ORG_TYPES = ("for_profit", "non_profit")
ORG_SIZES = ("small", "medium", "large")
RATING_BUCKETS = (1, 2, 3, 4, 5)

ALL_SENTINEL = "ALL"

# Normalisation expressions. The dev DB stores 'Non-Profit' / 'For-profit' and
# 'Small' / 'Medium' / 'Large'; the API contract uses non_profit / for_profit and
# lowercase sizes, so normalise in SQL rather than depending on stored casing.
SQL_ORG_TYPE = "REPLACE(LOWER(TRIM(o.org_type::text)), '-', '_')"
SQL_ORG_SIZE = "LOWER(TRIM(o.org_size::text))"
# ``::text`` keeps this working whether the column is a real boolean or the text
# 'TRUE'/'FALSE' produced by the local CSV loader.
SQL_IS_COLLABORATOR = "UPPER(o.is_collaborator::text) = 'TRUE'"
SQL_IS_CONTRIBUTOR = "UPPER(o.is_contributor::text) = 'TRUE'"
# NULLIF guards against empty strings when org_rating is loaded as text.
SQL_RATING = "NULLIF(TRIM(o.org_rating::text), '')::numeric"

DATE_INTERVALS = {
    "7D": "7 days",
    "30D": "30 days",
    "1Y": "1 year",
}


class FilterValidationError(ValueError):
    """Raised when the request payload contains an unusable filter."""


# --------------------------------------------------------------------------- #
# Request / response plumbing
# --------------------------------------------------------------------------- #
def parse_event_body(event):
    """Return the request payload whether it arrives via API Gateway or direct.

    Mirrors ``parse_event_body`` in volunteer_application_analytics.py. Analytics
    lambdas in this folder are deployed standalone, so shared helpers are copied
    per lambda rather than imported.
    """
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


def get_default_response():
    """Empty-but-valid response body, used for error paths."""
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
        "body": json.dumps(body),
    }


def default_db_user():
    """libpq defaults the DB user to the OS username; mirror that."""
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - no passwd entry available
        return "postgres"


def get_db_connection(env_prefix=""):
    """Open a PostgreSQL connection from environment variables.

    Recognised variables (Virginia uses no prefix, Ireland uses ``IRELAND_``):
    PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD, PGSSLMODE.

    PGUSER defaults to the OS username, matching libpq's own default. Homebrew
    and Postgres.app create a superuser named after the OS account rather than
    "postgres", so this is the default that works locally without configuration.
    """

    def env(name, default=None):
        return os.getenv(f"{env_prefix}{name}", default)

    kwargs = {
        "host": env("PGHOST", "localhost"),
        "port": env("PGPORT", "5432"),
        "dbname": env("PGDATABASE", "saayam_local"),
        "user": env("PGUSER") or default_db_user(),
        "password": env("PGPASSWORD", ""),
        "connect_timeout": int(env("PGCONNECT_TIMEOUT", "10")),
    }
    sslmode = env("PGSSLMODE")
    if sslmode:
        kwargs["sslmode"] = sslmode
    return psycopg2.connect(**kwargs)


def active_regions():
    """Regions to query. Ireland is included only when its host is configured."""
    regions = [REGIONS[0]]
    if os.getenv("IRELAND_PGHOST"):
        regions.append(REGIONS[1])
    return regions


# --------------------------------------------------------------------------- #
# Filter parsing
# --------------------------------------------------------------------------- #
def _parse_date(value, field):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise FilterValidationError(f"{field} must be a date in YYYY-MM-DD format.")


def parse_filters(body):
    """Validate the common dashboard filters and return a normalised dict.

    Raises FilterValidationError on anything unusable so the handler can answer
    400 rather than silently returning wrong numbers.
    """
    body = body or {}

    # DECISION: default to ALL (no date restriction) when time_filter is absent;
    # the doc does not specify a default.
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

    organization_type = str(
        body.get("organization_type") or ALL_SENTINEL
    ).strip().lower()
    if organization_type == ALL_SENTINEL.lower():
        organization_type = ALL_SENTINEL
    elif organization_type not in VALID_ORG_TYPES:
        raise FilterValidationError(
            f"organization_type must be ALL or one of {', '.join(VALID_ORG_TYPES)}."
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
    """Map a validated group_by value to (date_trunc unit, to_char format)."""
    try:
        return GROUP_BY_MAP[group_by]
    except KeyError:
        raise FilterValidationError(
            f"group_by must be one of {', '.join(sorted(GROUP_BY_MAP))}."
        )


def build_filter_clause(filters):
    """Build the shared WHERE fragment applied to every section.

    DECISION: date range, region and organization_type apply to all sections
    (KPI cards included), so every number on the dashboard reflects the active
    filter. Returns (sql_fragment, params) where sql_fragment always starts with
    ``AND`` or is empty.
    """
    clauses = []
    params = []

    time_filter = filters["time_filter"]
    if time_filter in DATE_INTERVALS:
        clauses.append(
            f"o.created_at >= CURRENT_DATE - INTERVAL '{DATE_INTERVALS[time_filter]}'"
        )
    elif time_filter == "CUSTOM":
        # End date is inclusive of the whole day.
        clauses.append("o.created_at >= %s::date")
        clauses.append("o.created_at < (%s::date + INTERVAL '1 day')")
        params.extend([filters["start_date"], filters["end_date"]])

    # DECISION: region matches organizations.state_id (the two-letter code),
    # case-insensitively.
    if filters["region"] != ALL_SENTINEL:
        clauses.append("UPPER(TRIM(o.state_id::text)) = UPPER(%s)")
        params.append(filters["region"])

    if filters["organization_type"] != ALL_SENTINEL:
        clauses.append(f"{SQL_ORG_TYPE} = %s")
        params.append(filters["organization_type"])

    if not clauses:
        return "", []
    return "AND " + " AND ".join(clauses), params


def has_column(cursor, qualified_table, column):
    """True when ``column`` exists on ``schema.table``.

    Used for is_contributor, which the task doc warns may not exist yet in the
    development database.
    """
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


# --------------------------------------------------------------------------- #
# Row helpers
# --------------------------------------------------------------------------- #
def _value(row, key, index):
    """Read a column from either a RealDictCursor row or a plain tuple."""
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


def _percentage(count, total):
    if not total:
        return 0.0
    return round(count * 100.0 / total, 1)


# --------------------------------------------------------------------------- #
# Per-region fetches (raw, unmerged)
# --------------------------------------------------------------------------- #
def fetch_summary_counts(cursor, organizations, filters, contributor_supported=True):
    """Filtered totals plus the rating sum/count needed to merge averages."""
    filter_sql, params = build_filter_clause(filters)
    contributor_expr = (
        f"COUNT(*) FILTER (WHERE {SQL_IS_CONTRIBUTOR})"
        if contributor_supported
        else "0"
    )
    query = f"""
        SELECT COUNT(*) AS total_organizations,
               COUNT(*) FILTER (WHERE {SQL_IS_COLLABORATOR}) AS total_collaborators,
               {contributor_expr} AS total_contributors,
               COALESCE(SUM({SQL_RATING}), 0) AS rating_sum,
               COUNT({SQL_RATING}) AS rating_count
        FROM {organizations} o
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


def fetch_growth_buckets(cursor, organizations, filters):
    """Per-period new organizations / new collaborators.

    Cumulative totals are computed after regions are merged, so that periods
    present in one region but not the other cannot distort the running total.
    """
    period, date_format = get_grouping(filters["group_by"])
    filter_sql, params = build_filter_clause(filters)
    query = f"""
        SELECT TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
               COUNT(*) AS new_organizations,
               COUNT(*) FILTER (WHERE {SQL_IS_COLLABORATOR}) AS new_collaborators
        FROM {organizations} o
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


def fetch_location_buckets(cursor, organizations, state_table, filters):
    """Organization counts grouped by state and city."""
    filter_sql, params = build_filter_clause(filters)
    query = f"""
        SELECT COALESCE(NULLIF(TRIM(o.state_id::text), ''), 'Unknown') AS state_id,
               COALESCE(NULLIF(TRIM(s.state_name::text), ''), 'Unknown') AS state_name,
               COALESCE(NULLIF(TRIM(o.city_name::text), ''), 'Unknown') AS city_name,
               COUNT(*) AS organization_count
        FROM {organizations} o
        LEFT JOIN {state_table} s
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


def fetch_size_buckets(cursor, organizations, filters):
    filter_sql, params = build_filter_clause(filters)
    query = f"""
        SELECT COALESCE(NULLIF({SQL_ORG_SIZE}, ''), 'unknown') AS org_size,
               COUNT(*) AS organization_count
        FROM {organizations} o
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


def fetch_rating_buckets(cursor, organizations, filters):
    """Counts per whole-star rating. NULL / out-of-range ratings are excluded."""
    filter_sql, params = build_filter_clause(filters)
    query = f"""
        SELECT ROUND({SQL_RATING})::int AS rating,
               COUNT(*) AS organization_count
        FROM {organizations} o
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


def fetch_org_type_buckets(cursor, organizations, filters):
    """Per-period new for-profit / non-profit counts (cumulated after merge)."""
    period, date_format = get_grouping(filters["group_by"])
    filter_sql, params = build_filter_clause(filters)
    query = f"""
        SELECT TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
               COUNT(*) FILTER (WHERE {SQL_ORG_TYPE} = 'for_profit') AS for_profit,
               COUNT(*) FILTER (WHERE {SQL_ORG_TYPE} = 'non_profit') AS non_profit
        FROM {organizations} o
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


# --------------------------------------------------------------------------- #
# Merge + shape
# --------------------------------------------------------------------------- #
def merge_period_buckets(bucket_lists, count_keys):
    """Sum per-period counts across regions, returning periods in sorted order."""
    merged = {}
    for buckets in bucket_lists:
        for row in buckets:
            period = row["period"]
            target = merged.setdefault(period, {key: 0 for key in count_keys})
            for key in count_keys:
                target[key] += int(row.get(key) or 0)
    return [
        dict(period=period, **merged[period]) for period in sorted(merged)
    ]


def build_summary(region_counts):
    total_organizations = sum(c["total_organizations"] for c in region_counts)
    total_collaborators = sum(c["total_collaborators"] for c in region_counts)
    total_contributors = sum(c["total_contributors"] for c in region_counts)
    rating_sum = sum(c["rating_sum"] for c in region_counts)
    rating_count = sum(c["rating_count"] for c in region_counts)
    return {
        "total_organizations": total_organizations,
        "total_collaborators": total_collaborators,
        "total_contributors": total_contributors,
        # Organizations with a NULL rating are excluded from the average rather
        # than counted as zero; 0.0 is returned only when nothing is rated.
        "average_org_rating": round(rating_sum / rating_count, 1) if rating_count else 0.0,
    }


def build_growth_trend(bucket_lists):
    """Cumulative organizations / collaborators within the filtered window."""
    merged = merge_period_buckets(
        bucket_lists, ("new_organizations", "new_collaborators")
    )
    running_orgs = 0
    running_collaborators = 0
    trend = []
    for row in merged:
        running_orgs += row["new_organizations"]
        running_collaborators += row["new_collaborators"]
        trend.append(
            {
                "period": row["period"],
                "total_organizations": running_orgs,
                "total_collaborators": running_collaborators,
            }
        )
    return trend


def build_organizations_by_location(bucket_lists, total_organizations):
    states = {}
    for buckets in bucket_lists:
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
                state["cities"].items(), key=lambda kv: (-kv[1], kv[0])
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
    result.sort(key=lambda r: (-r["organization_count"], r["state_id"]))
    return result


def build_organizations_by_size(bucket_dicts):
    merged = {}
    for buckets in bucket_dicts:
        for size, count in buckets.items():
            merged[size] = merged.get(size, 0) + count
    # Always emit small/medium/large so the chart keeps a stable set of bars.
    rows = [
        {"org_size": size, "organization_count": merged.get(size, 0)}
        for size in ORG_SIZES
    ]
    extras = sorted(set(merged) - set(ORG_SIZES))
    rows.extend(
        {"org_size": size, "organization_count": merged[size]} for size in extras
    )
    return rows


def build_collaborator_vs_contributor(summary, total_organizations, contributor_supported):
    rows = [
        {
            "type": "collaborator",
            "organization_count": summary["total_collaborators"],
            "percentage": _percentage(
                summary["total_collaborators"], total_organizations
            ),
        }
    ]
    # When is_contributor is missing from the database the row is omitted rather
    # than reported as a real zero.
    if contributor_supported:
        rows.append(
            {
                "type": "contributor",
                "organization_count": summary["total_contributors"],
                "percentage": _percentage(
                    summary["total_contributors"], total_organizations
                ),
            }
        )
    return rows


def build_rating_distribution(bucket_dicts):
    merged = {}
    for buckets in bucket_dicts:
        for rating, count in buckets.items():
            merged[rating] = merged.get(rating, 0) + count
    return [
        {"rating": rating, "organization_count": merged.get(rating, 0)}
        for rating in RATING_BUCKETS
    ]


def build_organization_type_distribution(bucket_lists):
    merged = merge_period_buckets(bucket_lists, ("for_profit", "non_profit"))
    running_for_profit = 0
    running_non_profit = 0
    distribution = []
    for row in merged:
        running_for_profit += row["for_profit"]
        running_non_profit += row["non_profit"]
        distribution.append(
            {
                "period": row["period"],
                "for_profit": running_for_profit,
                "non_profit": running_non_profit,
                "total": running_for_profit + running_non_profit,
            }
        )
    return distribution


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def collect_region_data(cursor, region, filters):
    """Run every section query for one region and return the raw buckets."""
    organizations = region["organizations"]
    contributor_supported = has_column(cursor, organizations, "is_contributor")
    return {
        "contributor_supported": contributor_supported,
        "summary": fetch_summary_counts(
            cursor, organizations, filters, contributor_supported
        ),
        "growth": fetch_growth_buckets(cursor, organizations, filters),
        "location": fetch_location_buckets(
            cursor, organizations, region["state"], filters
        ),
        "size": fetch_size_buckets(cursor, organizations, filters),
        "rating": fetch_rating_buckets(cursor, organizations, filters),
        "org_type": fetch_org_type_buckets(cursor, organizations, filters),
    }


def build_dashboard(region_data):
    """Assemble the documented response body from per-region raw buckets."""
    summary = build_summary([d["summary"] for d in region_data])
    total_organizations = summary["total_organizations"]
    contributor_supported = any(d["contributor_supported"] for d in region_data)

    return {
        "summary": summary,
        "growth_trend": build_growth_trend([d["growth"] for d in region_data]),
        "organizations_by_location": build_organizations_by_location(
            [d["location"] for d in region_data], total_organizations
        ),
        "organizations_by_size": build_organizations_by_size(
            [d["size"] for d in region_data]
        ),
        "collaborator_vs_contributor": build_collaborator_vs_contributor(
            summary, total_organizations, contributor_supported
        ),
        "rating_distribution": build_rating_distribution(
            [d["rating"] for d in region_data]
        ),
        "organization_type_distribution": build_organization_type_distribution(
            [d["org_type"] for d in region_data]
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

    connections = []
    region_data = []
    try:
        for region in active_regions():
            conn = get_db_connection(region["env_prefix"])
            connections.append(conn)
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                region_data.append(collect_region_data(cursor, region, filters))
            print(f"{region['name']} organization analytics collected.")

        return build_response(200, build_dashboard(region_data))

    except Exception as exc:  # noqa: BLE001 - never fail the dashboard open
        print(f"Organization analytics failed: {exc}")
        return build_response(500, get_default_response())

    finally:
        for conn in connections:
            try:
                conn.close()
            except Exception as exc:  # noqa: BLE001
                print(f"Error closing connection: {exc}")


if __name__ == "__main__":
    sample_event = {
        "time_filter": "1Y",
        "start_date": None,
        "end_date": None,
        "group_by": "monthly",
        "region": "ALL",
        "organization_type": "ALL",
    }
    print(json.dumps(json.loads(lambda_handler(sample_event, None)["body"]), indent=2))
