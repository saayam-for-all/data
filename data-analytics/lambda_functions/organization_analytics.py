"""Organization Analytics API (Issue #228).

A single AWS Lambda entry point that powers two dashboards for the Saayam
platform over ``virginia_dev_saayam_rdbms.organizations``:

* ``overview``     - registration mix, collaborator/contributor breakdowns,
                     location distribution and an activity trend.
* ``performance``  - rating quality metrics, rating distribution and
                     top-organization leaderboards.

The module follows the same conventions as ``kpi_api_analytics.py``:
an env-aware DB connection (local Postgres via env vars, otherwise the SSM
credential fallback), a ``build_response`` envelope, and a per-query
try/except strategy so a single failing query degrades to a safe empty
default (``[]`` or ``0``) instead of failing the whole request.

Guarded contributor support
---------------------------
The ``is_contributor`` column does not exist in the production database yet.
Every contributor code path is gated behind ``IS_CONTRIBUTOR_AVAILABLE``
(env var ``ORG_IS_CONTRIBUTOR``). When the flag is off the contributor
metrics return ``0`` / ``[]`` *without ever referencing the column*, so the
JSON shape is identical whether or not the migration has landed. When the
flag is on (local testing with the column present) the same functions run
real queries.

All user-supplied filter values are passed as parameterized ``%s`` values;
only trusted, whitelisted identifiers (schema name, ``date_trunc`` unit,
``LIMIT`` constant) are ever formatted into SQL text.
"""

import json
import os
from typing import Any, Optional

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"

# Number of rows returned by the "top N" performance leaderboards.
TOP_N = 10

# The production DB has no ``is_contributor`` column yet. Flip this on
# (ORG_IS_CONTRIBUTOR=true) only where the column actually exists.
IS_CONTRIBUTOR_AVAILABLE = os.environ.get("ORG_IS_CONTRIBUTOR", "false").lower() == "true"

# Whitelist mapping the public ``group_by`` values to a (date_trunc unit,
# TO_CHAR format) pair. Guards against SQL injection via the trend grouping.
GROUP_BY_MAP: dict[str, tuple[str, str]] = {
    "daily": ("day", "YYYY-MM-DD"),
    "weekly": ("week", "YYYY-MM-DD"),
    "monthly": ("month", "YYYY-MM"),
    "yearly": ("year", "YYYY"),
}
DEFAULT_GROUP_BY = "daily"

# Columns that accept a simple equality filter when the caller supplies a
# non-null value. ``is_contributor`` is appended dynamically only when the
# guard flag is enabled.
_EQUALITY_COLUMNS = (
    "org_type",
    "org_size",
    "state_id",
    "city_name",
    "org_rating",
    "is_collaborator",
)

_BOOLEAN_FILTERS = frozenset({"is_collaborator", "is_contributor"})


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
    """Open a Postgres connection, preferring local env vars over SSM.

    If ``DB_HOST`` is present in the environment the connection is built from
    ``DB_HOST``/``DB_NAME``/``DB_USER``/``DB_PASSWORD``/``DB_PORT`` (local
    development / testing). Otherwise the unchanged SSM credential fallback
    from ``kpi_api_analytics.py`` is used for the deployed Lambda.

    Returns:
        An open ``psycopg2`` connection.
    """
    db_host = os.environ.get("DB_HOST")
    if db_host:
        return psycopg2.connect(
            host=db_host,
            database=os.environ.get("DB_NAME", "saayam_local"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", ""),
            port=os.environ.get("DB_PORT", "5432"),
        )

    # --- SSM fallback (unchanged from kpi_api_analytics.py) ---
    ssm = boto3.client("ssm", region_name="us-east-1")
    response = ssm.get_parameter(
        Name="/dev/saayam/db/Virginia/Analytics/user",
        WithDecryption=True,
    )
    creds = json.loads(response["Parameter"]["Value"])
    return psycopg2.connect(
        host=creds["HOST"],
        database=creds["DATABASE NAME"],
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require",
    )


# --------------------------------------------------------------------------- #
# Filter helpers
# --------------------------------------------------------------------------- #
def _as_bool(value: Any) -> Optional[bool]:
    """Coerce a JSON/string/int value into a bool, or ``None`` if unset.

    Args:
        value: Raw filter value (bool, str, int or None).

    Returns:
        ``True``/``False`` for recognized truthy/falsy inputs, else ``None``
        (meaning "no filter"). ``False`` is preserved as a real filter value.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "t", "1", "yes", "y"):
        return True
    if text in ("false", "f", "0", "no", "n"):
        return False
    return None


def resolve_group_by(group_by: Optional[str]) -> tuple[str, str]:
    """Validate ``group_by`` against the whitelist and return SQL parts.

    Args:
        group_by: One of ``daily``/``weekly``/``monthly``/``yearly``
            (case-insensitive). Anything else falls back to the default.

    Returns:
        A ``(date_trunc_unit, to_char_format)`` tuple.
    """
    key = (group_by or DEFAULT_GROUP_BY).strip().lower()
    return GROUP_BY_MAP.get(key, GROUP_BY_MAP[DEFAULT_GROUP_BY])


def build_date_filter(
    time_filter: Optional[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[str, list[Any]]:
    """Build a ``created_at`` date predicate and its bind params.

    Mirrors the ``build_date_filter`` shape in ``kpi_api_analytics.py`` but
    filters on ``organizations.created_at`` (the registration timestamp).

    Args:
        time_filter: ``7D``/``30D``/``1Y``/``ALL``/``CUSTOM``
            (case-insensitive; defaults to ``ALL``).
        start_date: Inclusive lower bound, required for ``CUSTOM``.
        end_date: Inclusive upper bound, required for ``CUSTOM``.

    Returns:
        A ``(predicate, params)`` tuple. ``predicate`` is ``""`` (with an
        empty param list) for ``ALL`` or any unrecognized value.

    Raises:
        ValueError: If ``CUSTOM`` is requested without both dates.
    """
    tf = (time_filter or "ALL").strip().upper()
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
    # ALL or unrecognized -> no date restriction.
    return "", []


def build_org_filters(
    filters: dict[str, Any],
    extra: Optional[str] = None,
) -> tuple[str, list[Any]]:
    """Compose a full ``WHERE`` clause from the common org filters.

    Combines the ``created_at`` date predicate with equality predicates for
    every supplied (non-null) filter among ``org_type``, ``org_size``,
    ``state_id``, ``city_name``, ``org_rating`` and ``is_collaborator``, plus
    an optional trusted ``extra`` raw predicate. ``is_contributor`` is only
    added when ``IS_CONTRIBUTOR_AVAILABLE`` is ``True``.

    Every user-supplied value is bound as a ``%s`` parameter. The base table
    must be aliased ``o`` (and, for location queries, ``state`` aliased ``s``).

    Args:
        filters: The parsed common-filter dict from the event.
        extra: An optional raw predicate (no bind params) appended with
            ``AND``; used for trusted constants such as ``o.is_collaborator
            = TRUE`` or ``o.org_rating IS NOT NULL``.

    Returns:
        A ``(where_clause, params)`` tuple. ``where_clause`` is ``""`` when no
        predicates apply, otherwise a ready-to-use ``"WHERE ..."`` string.
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

    equality_columns = list(_EQUALITY_COLUMNS)
    if IS_CONTRIBUTOR_AVAILABLE:
        equality_columns.append("is_contributor")

    for column in equality_columns:
        raw_value = filters.get(column)
        value = _as_bool(raw_value) if column in _BOOLEAN_FILTERS else raw_value
        if value is not None:
            predicates.append(f"o.{column} = %s")
            params.append(value)

    if extra:
        predicates.append(extra)

    where_clause = f"WHERE {' AND '.join(predicates)}" if predicates else ""
    return where_clause, params


# --------------------------------------------------------------------------- #
# Overview fetchers
# --------------------------------------------------------------------------- #
def fetch_total_organizations(cursor: Any, filters: dict[str, Any]) -> int:
    """Return the total organization count for the current filters."""
    where, params = build_org_filters(filters)
    cursor.execute(
        f"SELECT COUNT(*) AS total FROM {SCHEMA_NAME}.organizations o {where}",
        params,
    )
    row = cursor.fetchone()
    return int(row["total"]) if row and row["total"] is not None else 0


def fetch_organizations_by_type(cursor: Any, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Return counts grouped by ``org_type``."""
    where, params = build_org_filters(filters)
    cursor.execute(
        f"""
        SELECT o.org_type AS org_type, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where}
        GROUP BY o.org_type
        ORDER BY count DESC
        """,
        params,
    )
    return [
        {"org_type": row["org_type"], "count": int(row["count"])}
        for row in cursor.fetchall()
    ]


def fetch_organizations_by_size(cursor: Any, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Return counts grouped by ``org_size``."""
    where, params = build_org_filters(filters)
    cursor.execute(
        f"""
        SELECT o.org_size AS org_size, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where}
        GROUP BY o.org_size
        ORDER BY count DESC
        """,
        params,
    )
    return [
        {"org_size": row["org_size"], "count": int(row["count"])}
        for row in cursor.fetchall()
    ]


def fetch_collaborator_summary(cursor: Any, filters: dict[str, Any]) -> tuple[int, int]:
    """Return ``(collaborator_count, non_collaborator_count)``."""
    where, params = build_org_filters(filters)
    cursor.execute(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE)  AS collaborators,
            COUNT(*) FILTER (WHERE o.is_collaborator IS FALSE) AS non_collaborators
        FROM {SCHEMA_NAME}.organizations o
        {where}
        """,
        params,
    )
    row = cursor.fetchone()
    if not row:
        return 0, 0
    return int(row["collaborators"] or 0), int(row["non_collaborators"] or 0)


def fetch_collaborator_distribution(cursor: Any, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Return TRUE/FALSE counts for ``is_collaborator``."""
    where, params = build_org_filters(filters)
    cursor.execute(
        f"""
        SELECT o.is_collaborator AS is_collaborator, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where}
        GROUP BY o.is_collaborator
        ORDER BY o.is_collaborator DESC NULLS LAST
        """,
        params,
    )
    return [
        {"is_collaborator": row["is_collaborator"], "count": int(row["count"])}
        for row in cursor.fetchall()
    ]


def fetch_contributor_summary(cursor: Any, filters: dict[str, Any]) -> tuple[int, int]:
    """Return ``(contributor_count, non_contributor_count)``.

    GUARDED: returns ``(0, 0)`` without touching the column when
    ``IS_CONTRIBUTOR_AVAILABLE`` is ``False``.
    """
    if not IS_CONTRIBUTOR_AVAILABLE:
        return 0, 0
    where, params = build_org_filters(filters)
    cursor.execute(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE o.is_contributor IS TRUE)  AS contributors,
            COUNT(*) FILTER (WHERE o.is_contributor IS FALSE) AS non_contributors
        FROM {SCHEMA_NAME}.organizations o
        {where}
        """,
        params,
    )
    row = cursor.fetchone()
    if not row:
        return 0, 0
    return int(row["contributors"] or 0), int(row["non_contributors"] or 0)


def fetch_contributor_distribution(cursor: Any, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Return TRUE/FALSE counts for ``is_contributor``.

    GUARDED: returns ``[]`` without touching the column when
    ``IS_CONTRIBUTOR_AVAILABLE`` is ``False``.
    """
    if not IS_CONTRIBUTOR_AVAILABLE:
        return []
    where, params = build_org_filters(filters)
    cursor.execute(
        f"""
        SELECT o.is_contributor AS is_contributor, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where}
        GROUP BY o.is_contributor
        ORDER BY o.is_contributor DESC NULLS LAST
        """,
        params,
    )
    return [
        {"is_contributor": row["is_contributor"], "count": int(row["count"])}
        for row in cursor.fetchall()
    ]


def fetch_organizations_by_location(cursor: Any, filters: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return counts by state (LEFT JOIN ``state``) and by ``city_name``.

    The single ``organizations_by_location`` response key carries both
    required breakdowns under ``by_state`` and ``by_city``.

    Returns:
        ``{"by_state": [...], "by_city": [...]}``.
    """
    where, params = build_org_filters(filters)

    cursor.execute(
        f"""
        SELECT o.state_id AS state_id,
               s.state_name AS state_name,
               COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        LEFT JOIN {SCHEMA_NAME}.state s ON o.state_id = s.state_id
        {where}
        GROUP BY o.state_id, s.state_name
        ORDER BY count DESC
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
        SELECT o.city_name AS city_name, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where}
        GROUP BY o.city_name
        ORDER BY count DESC
        """,
        params,
    )
    by_city = [
        {"city_name": row["city_name"], "count": int(row["count"])}
        for row in cursor.fetchall()
    ]

    return {"by_state": by_state, "by_city": by_city}


def fetch_organization_activity_trend(cursor: Any, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the registration trend grouped by ``group_by``, ascending.

    Each element is ``{"period": <formatted date>, "count": int}``.
    """
    unit, fmt = resolve_group_by(filters.get("group_by"))
    where, params = build_org_filters(filters)
    query = f"""
        SELECT TO_CHAR(DATE_TRUNC(%s, o.created_at), %s) AS period,
               COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where}
        GROUP BY DATE_TRUNC(%s, o.created_at)
        ORDER BY DATE_TRUNC(%s, o.created_at) ASC
    """
    cursor.execute(query, [unit, fmt] + params + [unit, unit])
    return [
        {"period": row["period"], "count": int(row["count"])}
        for row in cursor.fetchall()
    ]


# --------------------------------------------------------------------------- #
# Performance fetchers
# --------------------------------------------------------------------------- #
def fetch_performance_summary(cursor: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """Return rating summary: average, rated, unrated and five-star counts."""
    where, params = build_org_filters(filters)
    cursor.execute(
        f"""
        SELECT
            ROUND(AVG(o.org_rating)::numeric, 2)               AS average_rating,
            COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL)   AS rated,
            COUNT(*) FILTER (WHERE o.org_rating IS NULL)       AS unrated,
            COUNT(*) FILTER (WHERE o.org_rating = 5)           AS five_star
        FROM {SCHEMA_NAME}.organizations o
        {where}
        """,
        params,
    )
    row = cursor.fetchone()
    if not row:
        return {
            "average_rating": 0.0,
            "rated_organizations": 0,
            "unrated_organizations": 0,
            "five_star_organizations": 0,
        }
    return {
        "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0.0,
        "rated_organizations": int(row["rated"] or 0),
        "unrated_organizations": int(row["unrated"] or 0),
        "five_star_organizations": int(row["five_star"] or 0),
    }


def fetch_rating_distribution(cursor: Any, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Return counts grouped by ``org_rating`` (1..5), ascending by rating."""
    where, params = build_org_filters(filters, extra="o.org_rating IS NOT NULL")
    cursor.execute(
        f"""
        SELECT o.org_rating AS rating, COUNT(*) AS count
        FROM {SCHEMA_NAME}.organizations o
        {where}
        GROUP BY o.org_rating
        ORDER BY o.org_rating ASC
        """,
        params,
    )
    return [
        {"rating": int(row["rating"]), "count": int(row["count"])}
        for row in cursor.fetchall()
    ]


def fetch_top_rated_organizations(cursor: Any, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the top ``TOP_N`` organizations by rating (NULLS LAST)."""
    where, params = build_org_filters(filters)
    cursor.execute(
        f"""
        SELECT o.org_id, o.org_name, o.org_type, o.org_size, o.org_rating
        FROM {SCHEMA_NAME}.organizations o
        {where}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
        LIMIT {TOP_N}
        """,
        params,
    )
    return _serialize_org_rows(cursor.fetchall())


def fetch_top_collaborator_organizations(cursor: Any, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the top ``TOP_N`` collaborator organizations by rating."""
    where, params = build_org_filters(filters, extra="o.is_collaborator = TRUE")
    cursor.execute(
        f"""
        SELECT o.org_id, o.org_name, o.org_type, o.org_size, o.org_rating
        FROM {SCHEMA_NAME}.organizations o
        {where}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
        LIMIT {TOP_N}
        """,
        params,
    )
    return _serialize_org_rows(cursor.fetchall())


def fetch_top_contributor_organizations(cursor: Any, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the top ``TOP_N`` contributor organizations by rating.

    GUARDED: returns ``[]`` without touching the column when
    ``IS_CONTRIBUTOR_AVAILABLE`` is ``False``.
    """
    if not IS_CONTRIBUTOR_AVAILABLE:
        return []
    where, params = build_org_filters(filters, extra="o.is_contributor = TRUE")
    cursor.execute(
        f"""
        SELECT o.org_id, o.org_name, o.org_type, o.org_size, o.org_rating
        FROM {SCHEMA_NAME}.organizations o
        {where}
        ORDER BY o.org_rating DESC NULLS LAST, o.org_name ASC
        LIMIT {TOP_N}
        """,
        params,
    )
    return _serialize_org_rows(cursor.fetchall())


def fetch_ratings_by_organization_type(cursor: Any, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Return average rating grouped by ``org_type``."""
    where, params = build_org_filters(filters)
    cursor.execute(
        f"""
        SELECT o.org_type AS org_type,
               ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
               COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_count
        FROM {SCHEMA_NAME}.organizations o
        {where}
        GROUP BY o.org_type
        ORDER BY average_rating DESC NULLS LAST
        """,
        params,
    )
    return [
        {
            "org_type": row["org_type"],
            "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0.0,
            "rated_count": int(row["rated_count"] or 0),
        }
        for row in cursor.fetchall()
    ]


def fetch_ratings_by_organization_size(cursor: Any, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Return average rating grouped by ``org_size``."""
    where, params = build_org_filters(filters)
    cursor.execute(
        f"""
        SELECT o.org_size AS org_size,
               ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
               COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_count
        FROM {SCHEMA_NAME}.organizations o
        {where}
        GROUP BY o.org_size
        ORDER BY average_rating DESC NULLS LAST
        """,
        params,
    )
    return [
        {
            "org_size": row["org_size"],
            "average_rating": float(row["average_rating"]) if row["average_rating"] is not None else 0.0,
            "rated_count": int(row["rated_count"] or 0),
        }
        for row in cursor.fetchall()
    ]


def _serialize_org_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize leaderboard org rows into JSON-friendly dicts."""
    return [
        {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "org_type": row["org_type"],
            "org_size": row["org_size"],
            "org_rating": int(row["org_rating"]) if row["org_rating"] is not None else None,
        }
        for row in rows
    ]


# --------------------------------------------------------------------------- #
# Dashboard builders (per-query try/except, safe defaults)
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


def build_overview_response(cursor: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """Assemble the full ``organization_overview`` payload."""
    by_type = _safe(lambda: fetch_organizations_by_type(cursor, filters), [], "organizations_by_type")
    type_counts = {row["org_type"]: row["count"] for row in by_type}

    collaborators, non_collaborators = _safe(
        lambda: fetch_collaborator_summary(cursor, filters), (0, 0), "collaborator_summary"
    )
    contributors, non_contributors = _safe(
        lambda: fetch_contributor_summary(cursor, filters), (0, 0), "contributor_summary"
    )

    return {
        "organization_overview": {
            "summary": {
                "total_organizations": _safe(
                    lambda: fetch_total_organizations(cursor, filters), 0, "total_organizations"
                ),
                "non_profit_organizations": int(type_counts.get("non_profit", 0)),
                "for_profit_organizations": int(type_counts.get("for_profit", 0)),
                "collaborator_organizations": collaborators,
                "non_collaborator_organizations": non_collaborators,
                "contributor_organizations": contributors,
                "non_contributor_organizations": non_contributors,
            },
            "organization_activity_trend": _safe(
                lambda: fetch_organization_activity_trend(cursor, filters), [], "organization_activity_trend"
            ),
            "organizations_by_type": by_type,
            "organizations_by_size": _safe(
                lambda: fetch_organizations_by_size(cursor, filters), [], "organizations_by_size"
            ),
            "organizations_by_location": _safe(
                lambda: fetch_organizations_by_location(cursor, filters),
                {"by_state": [], "by_city": []},
                "organizations_by_location",
            ),
            "collaborator_distribution": _safe(
                lambda: fetch_collaborator_distribution(cursor, filters), [], "collaborator_distribution"
            ),
            "contributor_distribution": _safe(
                lambda: fetch_contributor_distribution(cursor, filters), [], "contributor_distribution"
            ),
        }
    }


def build_performance_response(cursor: Any, filters: dict[str, Any]) -> dict[str, Any]:
    """Assemble the full ``organization_performance`` payload."""
    return {
        "organization_performance": {
            "summary": _safe(
                lambda: fetch_performance_summary(cursor, filters),
                {
                    "average_rating": 0.0,
                    "rated_organizations": 0,
                    "unrated_organizations": 0,
                    "five_star_organizations": 0,
                },
                "performance_summary",
            ),
            "rating_distribution": _safe(
                lambda: fetch_rating_distribution(cursor, filters), [], "rating_distribution"
            ),
            "top_rated_organizations": _safe(
                lambda: fetch_top_rated_organizations(cursor, filters), [], "top_rated_organizations"
            ),
            "top_collaborator_organizations": _safe(
                lambda: fetch_top_collaborator_organizations(cursor, filters), [], "top_collaborator_organizations"
            ),
            "top_contributor_organizations": _safe(
                lambda: fetch_top_contributor_organizations(cursor, filters), [], "top_contributor_organizations"
            ),
            "ratings_by_organization_type": _safe(
                lambda: fetch_ratings_by_organization_type(cursor, filters), [], "ratings_by_organization_type"
            ),
            "ratings_by_organization_size": _safe(
                lambda: fetch_ratings_by_organization_size(cursor, filters), [], "ratings_by_organization_size"
            ),
        }
    }


# --------------------------------------------------------------------------- #
# Event parsing + handler
# --------------------------------------------------------------------------- #
def _extract_filters(event: dict[str, Any]) -> dict[str, Any]:
    """Pull the common filter values out of the raw Lambda event.

    Args:
        event: The raw (already-defaulted) event dict.

    Returns:
        A dict of the recognized common filters (missing keys omitted).
    """
    keys = (
        "time_filter",
        "start_date",
        "end_date",
        "org_type",
        "org_size",
        "state_id",
        "city_name",
        "org_rating",
        "is_collaborator",
        "is_contributor",
        "group_by",
    )
    return {key: event[key] for key in keys if event.get(key) is not None}


def lambda_handler(event: Optional[dict[str, Any]], context: Any = None) -> dict[str, Any]:
    """Route an analytics request to the overview or performance dashboard.

    The event branches on ``dashboard_type`` (``overview`` or
    ``performance``). Unknown or missing values default to ``overview``.
    The DB connection is wrapped in try/except (returning ``statusCode`` 500
    on failure); each query degrades to a safe empty default; the cursor and
    connection are always closed.

    Args:
        event: Lambda event with ``dashboard_type`` plus optional common
            filters. ``None`` is treated as an empty event.
        context: Unused Lambda context object.

    Returns:
        An API Gateway proxy response from ``build_response``.
    """
    event = event or {}
    dashboard_type = str(event.get("dashboard_type") or "overview").strip().lower()
    if dashboard_type not in ("overview", "performance"):
        dashboard_type = "overview"

    filters = _extract_filters(event)

    # Validate CUSTOM date range up front so it surfaces as a clean 400 rather
    # than being swallowed by the per-query safe-default wrappers below.
    try:
        build_date_filter(
            filters.get("time_filter"),
            filters.get("start_date"),
            filters.get("end_date"),
        )
    except ValueError as exc:
        print(f"[organization_analytics] bad request: {exc}")
        return build_response(400, {"error": str(exc)})

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if dashboard_type == "performance":
            body = build_performance_response(cursor, filters)
        else:
            body = build_overview_response(cursor, filters)

        return build_response(200, body)

    except ValueError as exc:
        # Invalid filter combination (e.g. CUSTOM without dates).
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
    print(json.dumps(lambda_handler({"dashboard_type": "overview"}, None), indent=2))
    print(json.dumps(lambda_handler({"dashboard_type": "performance"}, None), indent=2))
