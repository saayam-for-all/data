"""Organization Analytics API (Issue #228).

A single AWS Lambda entry point behind ``POST /analytics/organizations`` that
returns everything the three Organization Dashboard tabs need in one response,
over ``virginia_dev_saayam_rdbms.organizations`` and
``virginia_dev_saayam_rdbms.state``:

* KPI cards      - totals and average rating.
* Tab 1          - ``growth_trend``, ``organizations_by_location``
                   (plus ``organizations_by_city``).
* Tab 2          - ``organizations_by_size``, ``collaborator_vs_contributor``.
* Tab 3          - ``rating_distribution``, ``organization_type_distribution``.

No shared-database credentials
------------------------------
This Lambda deliberately has **no** AWS Parameter Store / SSM credential
lookup. The connection is built solely from explicit ``DB_*`` environment
variables, and ``get_db_connection`` raises when they are absent rather than
falling back to anything. There is therefore no code path from this module to
the shared production database.

Development and testing run entirely against the mock CSV fixtures in
``data-analytics/sql`` (``organizations.csv`` and ``state.csv``); see
``data-analytics/tests/`` for the harness that loads them and the recorded
results.

Guarded contributor support
---------------------------
``is_contributor`` may not exist yet in the development database. Every
contributor code path is gated behind ``ORG_IS_CONTRIBUTOR``. With the guard
off, contributor figures report ``0`` *without ever referencing the column*,
and no response key is added or dropped.

Safety
------
All user-supplied filter values are passed as parameterized ``%s`` values;
only trusted, whitelisted identifiers (schema name, ``date_trunc`` unit,
normalization expressions) are ever formatted into SQL text. Every query is
wrapped so that one failure degrades to a safe empty default rather than
failing the whole request, and NULL ratings are handled without error.
"""

import json
import os
import re
from typing import Any, Optional

import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"

# ``is_contributor`` may be missing from the development database. Set
# ORG_IS_CONTRIBUTOR=false there; contributor figures then report 0 without
# the column ever appearing in a statement.
DEFAULT_IS_CONTRIBUTOR_AVAILABLE = "true"

# The sentinel the dashboard sends instead of null to mean "no filter".
ALL_SENTINEL = "ALL"

# Whitelist mapping the public ``group_by`` values to a (date_trunc unit,
# TO_CHAR format) pair. Guards against SQL injection via the trend grouping.
GROUP_BY_MAP: dict[str, tuple[str, str]] = {
    "daily": ("day", "YYYY-MM-DD"),
    "weekly": ("week", "YYYY-MM-DD"),
    "monthly": ("month", "YYYY-MM"),
    "yearly": ("year", "YYYY"),
}
DEFAULT_GROUP_BY = "daily"

SUPPORTED_TIME_FILTERS = ("7D", "30D", "1Y", "ALL", "CUSTOM")

# Canonical org_size buckets, always present in the response so the UI can
# render a stable set of bars even when a filter empties one.
CANONICAL_ORG_SIZES = ("small", "medium", "large")

# Ratings are always reported as a full 1-5 scale, zero-filled where needed.
RATING_SCALE = (1, 2, 3, 4, 5)

# The fixtures store display labels ("Non-Profit", "For-profit") while the API
# speaks snake_case ("non_profit", "for_profit"). Both sides are reduced to a
# punctuation-free lowercase key before being compared.
ORG_TYPE_KEYS: dict[str, str] = {
    "nonprofit": "non_profit",
    "forprofit": "for_profit",
}

# Portable SQL that reduces org_type to the same key ``_normalize_key`` builds.
# Uses only LOWER/REPLACE so it behaves identically across engines.
_ORG_TYPE_KEY_SQL = (
    "LOWER(REPLACE(REPLACE(REPLACE(o.org_type, '-', ''), '_', ''), ' ', ''))"
)


# --------------------------------------------------------------------------- #
# Response envelope + DB connection
# --------------------------------------------------------------------------- #
def build_response(status_code: int, body: Any) -> dict[str, Any]:
    """Wrap a body in the standard API Gateway proxy response envelope.

    Args:
        status_code: HTTP status code to return.
        body: JSON-serializable response payload.

    Returns:
        A dict with ``statusCode``, CORS ``headers`` and a JSON ``body``.
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def get_db_connection() -> "psycopg2.extensions.connection":
    """Open a Postgres connection described entirely by environment variables.

    The connection is built from ``DB_HOST``/``DB_NAME``/``DB_USER``/
    ``DB_PASSWORD``/``DB_PORT``. There is intentionally **no** AWS Parameter
    Store fallback: this module must not be able to reach the shared
    production database, so an unconfigured environment is an error rather
    than an implicit escalation to real credentials.

    Returns:
        An open ``psycopg2`` connection.

    Raises:
        RuntimeError: If ``DB_HOST`` is not set.
    """
    db_host = os.environ.get("DB_HOST")
    if not db_host:
        raise RuntimeError(
            "DB_HOST is not set. organization_analytics has no AWS Parameter "
            "Store fallback by design - set the DB_* environment variables to "
            "point at your own database, or run the mock-backed test suite in "
            "data-analytics/tests/."
        )

    return psycopg2.connect(
        host=db_host,
        database=os.environ.get("DB_NAME", "saayam_local"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
        port=os.environ.get("DB_PORT", "5432"),
    )


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _contributor_available() -> bool:
    """Report whether ``is_contributor`` may be referenced in SQL.

    Read from the environment on every call (rather than captured at import)
    so the flag can be toggled per-request in tests and per-stage in
    deployment without reloading the module.

    Returns:
        ``True`` unless ``ORG_IS_CONTRIBUTOR`` is set to a falsy value.
    """
    raw = os.environ.get("ORG_IS_CONTRIBUTOR", DEFAULT_IS_CONTRIBUTOR_AVAILABLE)
    return str(raw).strip().lower() in ("true", "t", "1", "yes", "y")


def _normalize_key(value: Any) -> str:
    """Reduce a label to a lowercase letters-only comparison key.

    Maps ``"Non-Profit"``, ``"non_profit"`` and ``"Non Profit"`` onto the
    single key ``"nonprofit"``.

    Args:
        value: Any label from the database or the request.

    Returns:
        A lowercase letters-only key (``""`` for ``None``).
    """
    return re.sub(r"[^a-z]", "", str(value or "").lower())


def _percentage(count: int, total: int) -> float:
    """Return ``count`` as a percentage of ``total``, rounded to one decimal.

    Args:
        count: Numerator.
        total: Denominator; ``0`` yields ``0.0`` rather than raising.

    Returns:
        The percentage, or ``0.0`` when ``total`` is zero.
    """
    if not total:
        return 0.0
    return round(count * 100.0 / total, 1)


def _is_unset(value: Any) -> bool:
    """Report whether a filter value means "no filter".

    Treats ``None``, an empty/whitespace string and the ``"ALL"`` sentinel the
    dashboard sends as equivalent.
    """
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.upper() == ALL_SENTINEL


def parse_event_body(event: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Return the request payload from a Lambda event.

    Mirrors ``volunteer_application_analytics.parse_event_body`` so this API
    accepts the same shapes as the other analytics endpoints: an API Gateway
    proxy event carrying a JSON string ``body``, a dict ``body``, or a plain
    invocation event with the filters at the top level.

    Args:
        event: The raw Lambda event.

    Returns:
        The decoded payload, or ``{}`` when it cannot be read.
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


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
def resolve_group_by(group_by: Optional[str]) -> tuple[str, str]:
    """Validate ``group_by`` against the whitelist and return SQL parts.

    Args:
        group_by: ``daily``/``weekly``/``monthly``/``yearly``
            (case-insensitive); ``None`` selects the default.

    Returns:
        A ``(date_trunc_unit, to_char_format)`` tuple.

    Raises:
        ValueError: If ``group_by`` is not a supported value.
    """
    key = (group_by or DEFAULT_GROUP_BY).strip().lower()
    if key not in GROUP_BY_MAP:
        raise ValueError(
            f"group_by must be one of {', '.join(GROUP_BY_MAP)}; got {group_by!r}"
        )
    return GROUP_BY_MAP[key]


def build_date_filter(
    time_filter: Optional[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[str, list[Any]]:
    """Build a ``created_at`` date predicate and its bind params.

    Args:
        time_filter: ``7D``/``30D``/``1Y``/``ALL``/``CUSTOM``
            (case-insensitive; defaults to ``ALL``).
        start_date: Inclusive lower bound, required for ``CUSTOM``.
        end_date: Inclusive upper bound, required for ``CUSTOM``.

    Returns:
        A ``(predicate, params)`` tuple. ``predicate`` is ``""`` (with an
        empty param list) for ``ALL``.

    Raises:
        ValueError: If ``time_filter`` is unsupported, or ``CUSTOM`` is
            requested without both dates.
    """
    tf = (time_filter or "ALL").strip().upper()
    if tf not in SUPPORTED_TIME_FILTERS:
        raise ValueError(
            f"time_filter must be one of {', '.join(SUPPORTED_TIME_FILTERS)}; "
            f"got {time_filter!r}"
        )
    if tf == "7D":
        return "o.created_at >= CURRENT_DATE - INTERVAL '7 days'", []
    if tf == "30D":
        return "o.created_at >= CURRENT_DATE - INTERVAL '30 days'", []
    if tf == "1Y":
        return "o.created_at >= CURRENT_DATE - INTERVAL '1 year'", []
    if tf == "CUSTOM":
        if not start_date or not end_date:
            raise ValueError(
                "start_date and end_date are required when time_filter is CUSTOM"
            )
        return "o.created_at BETWEEN %s AND %s", [start_date, end_date]
    return "", []


def build_filters(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """Compose the ``WHERE`` clause shared by every query.

    Combines the ``created_at`` window with the dashboard's ``region`` and
    ``organization_type`` filters. ``region`` accepts either a readable state
    name ("California") or a state code ("CA") and is resolved through the
    ``state`` lookup table, so no caller needs to know state ids.

    The base table must be aliased ``o``.

    Args:
        filters: The parsed filter dict from :func:`_extract_filters`.

    Returns:
        A ``(where_clause, params)`` tuple; ``where_clause`` is ``""`` when
        nothing applies, otherwise a ready-to-use ``"WHERE ..."`` string.
    """
    predicates: list[str] = []
    params: list[Any] = []

    date_pred, date_params = build_date_filter(
        filters.get("time_filter"),
        filters.get("start_date"),
        filters.get("end_date"),
    )
    if date_pred:
        predicates.append(date_pred)
        params.extend(date_params)

    region = filters.get("region")
    if region is not None:
        predicates.append(
            f"o.state_id IN ("
            f"SELECT s_r.state_id FROM {SCHEMA_NAME}.state s_r "
            f"WHERE LOWER(s_r.state_name) = LOWER(%s) "
            f"OR LOWER(s_r.state_id) = LOWER(%s))"
        )
        params.extend([region, region])

    organization_type = filters.get("organization_type")
    if organization_type is not None:
        predicates.append(f"{_ORG_TYPE_KEY_SQL} = %s")
        params.append(organization_type)

    where_clause = f"WHERE {' AND '.join(predicates)}" if predicates else ""
    return where_clause, params


def _extract_filters(event: dict[str, Any]) -> dict[str, Any]:
    """Pull and validate the common dashboard filters from the payload.

    Recognizes the shared filter structure used by the other analytics
    dashboards: ``time_filter``, ``start_date``, ``end_date``, ``group_by``,
    ``region`` and ``organization_type``. ``"ALL"``, ``null`` and ``""`` all
    mean "no filter".

    Args:
        event: The decoded request payload.

    Returns:
        A dict holding only the filters that actually apply. Applied filters
        are normalized: ``organization_type`` becomes a comparison key.

    Raises:
        ValueError: If a supplied filter value is not supported.
    """
    filters: dict[str, Any] = {}

    time_filter = event.get("time_filter")
    if not _is_unset(time_filter):
        filters["time_filter"] = str(time_filter).strip().upper()
    for key in ("start_date", "end_date"):
        value = event.get(key)
        if value is not None and str(value).strip() != "":
            filters[key] = str(value).strip()

    group_by = event.get("group_by")
    if group_by is not None and str(group_by).strip() != "":
        filters["group_by"] = str(group_by).strip().lower()

    region = event.get("region")
    if not _is_unset(region):
        filters["region"] = str(region).strip()

    organization_type = event.get("organization_type")
    if not _is_unset(organization_type):
        key = _normalize_key(organization_type)
        if key not in ORG_TYPE_KEYS:
            raise ValueError(
                "organization_type must be one of "
                f"{', '.join(sorted(ORG_TYPE_KEYS.values()))} or ALL; "
                f"got {organization_type!r}"
            )
        filters["organization_type"] = key

    # Surface unsupported time_filter / group_by values as validation errors
    # rather than silently returning data for a different window.
    build_date_filter(
        filters.get("time_filter"), filters.get("start_date"), filters.get("end_date")
    )
    resolve_group_by(filters.get("group_by"))

    return filters


# --------------------------------------------------------------------------- #
# KPI cards
# --------------------------------------------------------------------------- #
def fetch_summary(cursor: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """Return the four KPI cards for the current filters.

    ``total_contributors`` reports ``0`` without referencing the column when
    the contributor guard is off. ``average_org_rating`` ignores NULL ratings
    and reports ``0.0`` when nothing is rated.

    Returns:
        ``{"total_organizations", "total_collaborators", "total_contributors",
        "average_org_rating"}``.
    """
    where, params = build_filters(filters)
    contributor_select = (
        "COUNT(*) FILTER (WHERE o.is_contributor IS TRUE)"
        if _contributor_available()
        else "0"
    )
    cursor.execute(
        f"""
        SELECT
            COUNT(*)                                            AS total_organizations,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE)   AS total_collaborators,
            {contributor_select}                                AS total_contributors,
            ROUND(AVG(o.org_rating)::numeric, 2)                AS average_org_rating
        FROM {SCHEMA_NAME}.organizations o
        {where}
        """,
        params,
    )
    row = cursor.fetchone()
    if not row:
        return {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": 0.0,
        }
    average = row["average_org_rating"]
    return {
        "total_organizations": int(row["total_organizations"] or 0),
        "total_collaborators": int(row["total_collaborators"] or 0),
        "total_contributors": int(row["total_contributors"] or 0),
        "average_org_rating": float(average) if average is not None else 0.0,
    }


# --------------------------------------------------------------------------- #
# Tab 1 - Growth & Location
# --------------------------------------------------------------------------- #
def fetch_growth_trend(cursor: Any, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the cumulative organization and collaborator counts per period.

    Both series are running totals across the filtered window, matching the
    growth-chart figures in the issue (each period reports the total reached
    by the end of that period, not the number added during it).

    Returns:
        ``[{"period", "total_organizations", "total_collaborators"}, ...]``
        ordered oldest first.
    """
    unit, fmt = resolve_group_by(filters.get("group_by"))
    where, params = build_filters(filters)
    cursor.execute(
        f"""
        SELECT TO_CHAR(DATE_TRUNC(%s, o.created_at), %s)        AS period,
               COUNT(*)                                         AS new_organizations,
               COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS new_collaborators
        FROM {SCHEMA_NAME}.organizations o
        {where}
        GROUP BY DATE_TRUNC(%s, o.created_at)
        ORDER BY DATE_TRUNC(%s, o.created_at) ASC
        """,
        [unit, fmt] + params + [unit, unit],
    )

    trend: list[dict[str, Any]] = []
    running_organizations = 0
    running_collaborators = 0
    for row in cursor.fetchall():
        running_organizations += int(row["new_organizations"] or 0)
        running_collaborators += int(row["new_collaborators"] or 0)
        trend.append(
            {
                "period": row["period"],
                "total_organizations": running_organizations,
                "total_collaborators": running_collaborators,
            }
        )
    return trend


def fetch_organizations_by_location(
    cursor: Any, filters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return the organization count and share per state.

    ``state_name`` is resolved through the ``state`` lookup table so the UI
    gets readable labels; it is ``None`` for any state id the lookup does not
    cover.

    Returns:
        ``[{"state_id", "state_name", "organization_count", "percentage"}, ...]``
        ordered by count descending.
    """
    where, params = build_filters(filters)
    cursor.execute(
        f"""
        SELECT o.state_id                AS state_id,
               s.state_name              AS state_name,
               COUNT(*)                  AS organization_count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        {where}
        GROUP BY o.state_id, s.state_name
        ORDER BY organization_count DESC, o.state_id ASC
        """,
        params,
    )
    rows = cursor.fetchall()
    total = sum(int(row["organization_count"]) for row in rows)
    return [
        {
            "state_id": row["state_id"],
            "state_name": row["state_name"],
            "organization_count": int(row["organization_count"]),
            "percentage": _percentage(int(row["organization_count"]), total),
        }
        for row in rows
    ]


def fetch_organizations_by_city(
    cursor: Any, filters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return the organization count and share per city.

    Carries the owning state alongside each city so the UI can disambiguate
    identically named cities in different states.

    Returns:
        ``[{"city_name", "state_id", "state_name", "organization_count",
        "percentage"}, ...]`` ordered by count descending.
    """
    where, params = build_filters(filters)
    cursor.execute(
        f"""
        SELECT o.city_name               AS city_name,
               o.state_id                AS state_id,
               s.state_name              AS state_name,
               COUNT(*)                  AS organization_count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        {where}
        GROUP BY o.city_name, o.state_id, s.state_name
        ORDER BY organization_count DESC, o.city_name ASC
        """,
        params,
    )
    rows = cursor.fetchall()
    total = sum(int(row["organization_count"]) for row in rows)
    return [
        {
            "city_name": row["city_name"],
            "state_id": row["state_id"],
            "state_name": row["state_name"],
            "organization_count": int(row["organization_count"]),
            "percentage": _percentage(int(row["organization_count"]), total),
        }
        for row in rows
    ]


# --------------------------------------------------------------------------- #
# Tab 2 - Size & Contribution
# --------------------------------------------------------------------------- #
def fetch_organizations_by_size(
    cursor: Any, filters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return organization counts for the small/medium/large buckets.

    All three canonical buckets are always present (zero-filled) and reported
    in that order, so the chart keeps a stable set of bars under any filter.
    Any non-canonical size found in the data is appended afterwards.

    Returns:
        ``[{"org_size", "organization_count"}, ...]``.
    """
    where, params = build_filters(filters)
    cursor.execute(
        f"""
        SELECT LOWER(o.org_size) AS org_size, COUNT(*) AS organization_count
        FROM {SCHEMA_NAME}.organizations o
        {where}
        GROUP BY LOWER(o.org_size)
        """,
        params,
    )
    counts = {
        row["org_size"]: int(row["organization_count"]) for row in cursor.fetchall()
    }

    result = [
        {"org_size": size, "organization_count": counts.pop(size, 0)}
        for size in CANONICAL_ORG_SIZES
    ]
    # Preserve anything unexpected rather than silently dropping rows.
    result.extend(
        {"org_size": size, "organization_count": count}
        for size, count in sorted(counts.items(), key=lambda item: -item[1])
    )
    return result


def fetch_collaborator_vs_contributor(
    cursor: Any, filters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return collaborator and contributor counts with their shares.

    Both flags are independent, so percentages are each organization's share
    of the filtered population rather than of one another.

    GUARDED: the contributor row reports ``0`` without referencing the column
    when ``ORG_IS_CONTRIBUTOR`` is disabled; the row itself is always present.

    Returns:
        ``[{"type", "organization_count", "percentage"}, ...]`` for
        ``collaborator`` then ``contributor``.
    """
    where, params = build_filters(filters)
    contributor_select = (
        "COUNT(*) FILTER (WHERE o.is_contributor IS TRUE)"
        if _contributor_available()
        else "0"
    )
    cursor.execute(
        f"""
        SELECT
            COUNT(*)                                          AS total,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborators,
            {contributor_select}                              AS contributors
        FROM {SCHEMA_NAME}.organizations o
        {where}
        """,
        params,
    )
    row = cursor.fetchone()
    if not row:
        return [
            {"type": "collaborator", "organization_count": 0, "percentage": 0.0},
            {"type": "contributor", "organization_count": 0, "percentage": 0.0},
        ]

    total = int(row["total"] or 0)
    collaborators = int(row["collaborators"] or 0)
    contributors = int(row["contributors"] or 0)
    return [
        {
            "type": "collaborator",
            "organization_count": collaborators,
            "percentage": _percentage(collaborators, total),
        },
        {
            "type": "contributor",
            "organization_count": contributors,
            "percentage": _percentage(contributors, total),
        },
    ]


# --------------------------------------------------------------------------- #
# Tab 3 - Ratings & Type
# --------------------------------------------------------------------------- #
def fetch_rating_distribution(
    cursor: Any, filters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return the organization count for each star rating.

    The full 1-5 scale is always returned, zero-filled where a rating is
    unused. Organizations with a NULL rating are simply excluded from every
    bucket rather than causing an error.

    Returns:
        ``[{"rating", "organization_count"}, ...]`` ascending by rating.
    """
    where, params = build_filters(filters)
    cursor.execute(
        f"""
        SELECT o.org_rating AS rating, COUNT(*) AS organization_count
        FROM {SCHEMA_NAME}.organizations o
        {where}
        GROUP BY o.org_rating
        """,
        params,
    )
    counts: dict[int, int] = {}
    for row in cursor.fetchall():
        if row["rating"] is None:
            continue
        counts[int(row["rating"])] = int(row["organization_count"])
    return [
        {"rating": rating, "organization_count": counts.get(rating, 0)}
        for rating in RATING_SCALE
    ]


def fetch_organization_type_distribution(
    cursor: Any, filters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return the cumulative for-profit / non-profit split per period.

    Like the growth trend, each period reports the totals reached by the end
    of that period, which is what the stacked-bar figures in the issue show.

    Returns:
        ``[{"period", "for_profit", "non_profit", "total"}, ...]`` ordered
        oldest first.
    """
    unit, fmt = resolve_group_by(filters.get("group_by"))
    where, params = build_filters(filters)
    cursor.execute(
        f"""
        SELECT TO_CHAR(DATE_TRUNC(%s, o.created_at), %s) AS period,
               COUNT(*) FILTER (WHERE {_ORG_TYPE_KEY_SQL} = 'forprofit') AS for_profit,
               COUNT(*) FILTER (WHERE {_ORG_TYPE_KEY_SQL} = 'nonprofit') AS non_profit
        FROM {SCHEMA_NAME}.organizations o
        {where}
        GROUP BY DATE_TRUNC(%s, o.created_at)
        ORDER BY DATE_TRUNC(%s, o.created_at) ASC
        """,
        [unit, fmt] + params + [unit, unit],
    )

    distribution: list[dict[str, Any]] = []
    running_for_profit = 0
    running_non_profit = 0
    for row in cursor.fetchall():
        running_for_profit += int(row["for_profit"] or 0)
        running_non_profit += int(row["non_profit"] or 0)
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
# Dashboard assembly (per-query try/except, safe defaults)
# --------------------------------------------------------------------------- #
def _safe(fetch, default: Any, label: str) -> Any:
    """Run a fetcher, returning ``default`` (and logging) on any error.

    Args:
        fetch: Zero-arg callable performing the query.
        default: Value to return if the query raises.
        label: Human-readable name used in the log line.

    Returns:
        The fetcher's result, or ``default`` on failure.
    """
    try:
        return fetch()
    except Exception as exc:  # noqa: BLE001 - degrade gracefully per query
        print(f"[organization_analytics] query '{label}' failed: {exc}")
        return default


def empty_dashboard() -> dict[str, Any]:
    """Return the full response shape with every metric at its zero value."""
    return {
        "summary": {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": 0.0,
        },
        "growth_trend": [],
        "organizations_by_location": [],
        "organizations_by_city": [],
        "organizations_by_size": [
            {"org_size": size, "organization_count": 0}
            for size in CANONICAL_ORG_SIZES
        ],
        "collaborator_vs_contributor": [
            {"type": "collaborator", "organization_count": 0, "percentage": 0.0},
            {"type": "contributor", "organization_count": 0, "percentage": 0.0},
        ],
        "rating_distribution": [
            {"rating": rating, "organization_count": 0} for rating in RATING_SCALE
        ],
        "organization_type_distribution": [],
    }


def build_dashboard_response(cursor: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """Assemble the whole Organization Dashboard payload.

    Every section is fetched independently so one failing query degrades to
    its zero value while the rest of the dashboard still renders.

    Args:
        cursor: An open dict-returning cursor.
        filters: The validated filter dict.

    Returns:
        The full response body.
    """
    defaults = empty_dashboard()
    return {
        "summary": _safe(
            lambda: fetch_summary(cursor, filters), defaults["summary"], "summary"
        ),
        "growth_trend": _safe(
            lambda: fetch_growth_trend(cursor, filters), [], "growth_trend"
        ),
        "organizations_by_location": _safe(
            lambda: fetch_organizations_by_location(cursor, filters),
            [],
            "organizations_by_location",
        ),
        "organizations_by_city": _safe(
            lambda: fetch_organizations_by_city(cursor, filters),
            [],
            "organizations_by_city",
        ),
        "organizations_by_size": _safe(
            lambda: fetch_organizations_by_size(cursor, filters),
            defaults["organizations_by_size"],
            "organizations_by_size",
        ),
        "collaborator_vs_contributor": _safe(
            lambda: fetch_collaborator_vs_contributor(cursor, filters),
            defaults["collaborator_vs_contributor"],
            "collaborator_vs_contributor",
        ),
        "rating_distribution": _safe(
            lambda: fetch_rating_distribution(cursor, filters),
            defaults["rating_distribution"],
            "rating_distribution",
        ),
        "organization_type_distribution": _safe(
            lambda: fetch_organization_type_distribution(cursor, filters),
            [],
            "organization_type_distribution",
        ),
    }


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #
def lambda_handler(event: Optional[dict[str, Any]], context: Any = None) -> dict[str, Any]:
    """Serve ``POST /analytics/organizations``.

    One request returns every metric for all three dashboard tabs. Invalid
    filter values are rejected with ``400`` before any query runs; a database
    failure returns ``500`` without leaking connection details; and a single
    failing query degrades to that metric's zero value while the request still
    returns ``200``.

    Args:
        event: API Gateway proxy event or a plain invocation payload.
        context: Unused Lambda context object.

    Returns:
        An API Gateway proxy response from :func:`build_response`.
    """
    payload = parse_event_body(event)

    # Validate up front so bad input surfaces as a clean 400 rather than
    # escaping the handler or being swallowed by the safe-default wrappers.
    try:
        filters = _extract_filters(payload)
    except ValueError as exc:
        print(f"[organization_analytics] bad request: {exc}")
        return build_response(400, {"error": str(exc)})

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        return build_response(200, build_dashboard_response(cursor, filters))

    except ValueError as exc:
        print(f"[organization_analytics] bad request: {exc}")
        return build_response(400, {"error": str(exc)})

    except Exception as exc:  # noqa: BLE001
        print(f"[organization_analytics] DB connection failed: {exc}")
        return build_response(500, {"error": "internal server error"})

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    print(json.dumps(lambda_handler({"time_filter": "ALL", "group_by": "monthly"}), indent=2))
