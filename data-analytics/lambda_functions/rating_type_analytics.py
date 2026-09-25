"""Rating & Type Analytics API (Issue #380).

A standalone AWS Lambda serving the **Rating & Type** tab of the Organization
Analytics dashboard. Two charts of deliberately different kinds:

* ``rating_distribution`` - a **categorical** breakdown: organization counts per
  ``org_rating`` (1-5), window-scoped, one row per rating actually present.
* ``organization_mix_trend`` - a **time series**: two cumulative series,
  ``non_profit`` and ``for_profit``, bucketed by day or month.

Response shape
--------------
The shape depends on which Custom date-range pairs the request carries:

=========================  ===========================================
Request                    Top-level keys
=========================  ===========================================
no Custom pair             ``7D``, ``30D``, ``1Y``, ``All``, ``Custom``
                           (``Custom`` present but empty)
``rating_*`` only          ``Custom`` only - rating populated
``type_*`` only            ``Custom`` only - mix trend populated
both pairs                 ``Custom`` only - **both** populated, each
                           from its own range
=========================  ===========================================

The two pairs are fully independent: either, both, or neither may be present,
and neither takes priority.

Cumulative semantics
--------------------
``organization_mix_trend`` accumulates a running total per type, and is
**window-scoped**: every bucket restarts at zero and counts only the
organizations created inside its own window. This matches the
``growth_trend``/``total_organizations`` behaviour the issue points at, and is
what the issue's own worked example shows - its ``1Y`` series opens at 8 while
``All`` has already reached 45 at an earlier period, which is only possible if
``1Y`` restarts rather than carrying earlier history forward.

Periods are sparse: a period in which no organization of that type was created
is omitted rather than emitted as a repeat of the previous running total.
``7D``, ``30D`` and ``Custom`` group by day (``YYYY-MM-DD``); ``1Y`` and ``All``
group by month (``YYYY-MM``).

Both series keys are always present, even when empty, so the consuming chart
can rely on the shape.

Filters
-------
``country`` only - matched against either the country code or the country name,
case-insensitively, and applied to both charts. There is deliberately **no**
``organization_type`` filter on this tab: the mix trend *is* the type
breakdown, so filtering by type would leave one side of its own stacked bar.

Data sources
------------
With ``USE_MOCK_DATA`` enabled (the default) the charts are computed with
pandas from three CSVs found in ``MOCK_DATA_DIR``, which defaults to
``data-analytics/sql``. The plural filenames named by the issue are preferred,
falling back to the singular names actually tracked in this repository. No CSV
is committed by this function.

Setting ``USE_MOCK_DATA=false`` switches to PostgreSQL, using ``DB_*``
environment variables only - there is no AWS Parameter Store path. ``psycopg2``
is imported optionally so this module still runs standalone, against the mock
CSVs, on a machine where the driver is not installed.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, timedelta
from typing import Any, Mapping, Optional, Sequence, TypedDict

import pandas as pd

try:  # The driver is only needed for the real-database path.
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # pragma: no cover - exercised by running without psycopg2
    psycopg2 = None
    RealDictCursor = None


LOGGER = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
ALL_BUCKETS = (*FIXED_BUCKETS, "Custom")

# Day offsets are inclusive of today, so "7D" covers today plus the previous
# six dates. "All" is unbounded and has no offset.
BUCKET_OFFSET_DAYS: Mapping[str, Optional[int]] = {
    "7D": 6,
    "30D": 29,
    "1Y": 365,
    "All": None,
}

# Short windows are grouped by day; long ones by month.
BUCKET_GRANULARITY: Mapping[str, str] = {
    "7D": "day",
    "30D": "day",
    "1Y": "month",
    "All": "month",
    "Custom": "day",
}
PERIOD_FORMAT: Mapping[str, str] = {"day": "%Y-%m-%d", "month": "%Y-%m"}

# The two series the response always carries, in order. The stored labels are
# "Non-Profit" and "For-profit"; the API speaks snake_case, so the normalized
# key of the stored value is mapped onto the series name.
TYPE_SERIES_KEYS: Mapping[str, str] = {
    "nonprofit": "non_profit",
    "forprofit": "for_profit",
}
SERIES_ORDER = ("non_profit", "for_profit")

# The plural names are the interface the issue specifies; the singular aliases
# are what this repository actually tracks in data-analytics/sql.
INPUT_FILENAMES: Mapping[str, tuple[str, ...]] = {
    "organizations": ("organizations.csv",),
    "states": ("states.csv", "state.csv"),
    "countries": ("countries.csv", "country.csv"),
}

# The sentinel the dashboard sends instead of null to mean "no filter".
ALL_SENTINEL = "ALL"

_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

SCHEMA_NAME = "virginia_dev_saayam_rdbms"


class RatingCount(TypedDict):
    """One row of the ``rating_distribution`` chart."""

    rating: int
    count: int


class TrendPoint(TypedDict):
    """One point of an ``organization_mix_trend`` series."""

    period: str
    count: int


class RequestError(ValueError):
    """Raised when the request payload cannot be used as sent."""


class DateRangeError(RequestError):
    """Raised when a Custom date-range pair is incomplete or malformed."""


class MockDataError(RuntimeError):
    """Raised when the local CSV fixtures cannot be loaded."""


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def mock_data_dir() -> str:
    """Return the directory holding the local CSV fixtures.

    Read on every call rather than captured at import so tests can point it at
    a temporary directory without reloading the module.

    Returns:
        The configured directory, defaulting to ``data-analytics/sql``.
    """
    return os.environ.get(
        "MOCK_DATA_DIR", os.path.join(BASE_DIR, os.pardir, "sql")
    )


def use_mock_data() -> bool:
    """Report whether the pandas/CSV path is active.

    Returns:
        ``True`` unless ``USE_MOCK_DATA`` is set to a falsy value.
    """
    raw = os.environ.get("USE_MOCK_DATA", "true")
    return str(raw).strip().lower() in ("true", "t", "1", "yes", "y")


# --------------------------------------------------------------------------- #
# Response envelope
# --------------------------------------------------------------------------- #
def build_response(status_code: int, body: Any) -> dict[str, Any]:
    """Wrap a body in the standard API Gateway proxy response envelope.

    Args:
        status_code: HTTP status code to return.
        body: JSON-serializable response payload.

    Returns:
        A dict with ``statusCode``, CORS ``headers`` and a JSON string ``body``.
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        # allow_nan=False keeps a stray numpy NaN from producing invalid JSON.
        "body": json.dumps(body, default=str, allow_nan=False),
    }


# --------------------------------------------------------------------------- #
# Request parsing and validation
# --------------------------------------------------------------------------- #
def parse_event_body(event: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Return the request payload from a Lambda event.

    Accepts the shapes the other analytics endpoints accept: an API Gateway
    proxy event carrying a JSON string ``body``, a dict ``body``, or a plain
    invocation event with the filters at the top level.

    Args:
        event: The raw Lambda event.

    Returns:
        The decoded payload, or ``{}`` when it carries nothing.

    Raises:
        RequestError: If the body is a string that is not valid JSON, or
            decodes to something other than an object.
    """
    if not event:
        return {}

    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RequestError("request body must contain valid JSON") from exc
        if not isinstance(decoded, dict):
            raise RequestError("request body must decode to a JSON object")
        return decoded
    raise RequestError("request body must be a JSON object encoded as a string")


def _normalize_key(value: Any) -> str:
    """Reduce a label to a lowercase letters-only comparison key.

    Maps ``"Non-Profit"``, ``"non_profit"`` and ``"Non Profit"`` onto the
    single key ``"nonprofit"``, so a stored label resolves to a series name
    however it happens to be cased or punctuated.

    Args:
        value: Any label from the data or the request.

    Returns:
        A lowercase letters-only key (``""`` for ``None``).
    """
    return re.sub(r"[^a-z]", "", str(value or "").lower())


def _is_unset(value: Any) -> bool:
    """Report whether a filter value means "no filter".

    Treats ``None``, an empty or whitespace string and the ``"ALL"`` sentinel
    as equivalent.
    """
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.upper() == ALL_SENTINEL


def _parse_date(value: Any, field: str) -> date:
    """Parse one ``YYYY-MM-DD`` request date.

    Args:
        value: The raw request value.
        field: Field name, used in the error message.

    Returns:
        The parsed date.

    Raises:
        DateRangeError: If the value is not a valid ``YYYY-MM-DD`` date.
    """
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value.strip()):
        raise DateRangeError(f"{field} must use YYYY-MM-DD format")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise DateRangeError(
            f"{field} must be a valid calendar date in YYYY-MM-DD format"
        ) from exc


def parse_date_pair(
    payload: Mapping[str, Any], start_field: str, end_field: str
) -> Optional[tuple[date, date]]:
    """Validate one Custom date-range pair.

    Both halves must be present together. A pair that is absent entirely is
    not an error - it simply means that chart has no Custom range.

    Args:
        payload: The decoded request body.
        start_field: Name of the range's start field.
        end_field: Name of the range's end field.

    Returns:
        The ``(start, end)`` pair, or ``None`` when neither field was sent.

    Raises:
        DateRangeError: If only one half is present, either half is malformed,
            or the start falls after the end.
    """
    start_value = payload.get(start_field)
    end_value = payload.get(end_field)

    if start_value is None and end_value is None:
        return None

    # An empty string is a supplied-but-invalid date, not an absent one, so it
    # is reported as a format error rather than as a missing half.
    if isinstance(start_value, str) and not start_value.strip():
        raise DateRangeError(f"{start_field} must use YYYY-MM-DD format")
    if isinstance(end_value, str) and not end_value.strip():
        raise DateRangeError(f"{end_field} must use YYYY-MM-DD format")

    if start_value is None or end_value is None:
        raise DateRangeError(
            f"{start_field} and {end_field} must be provided together"
        )

    start = _parse_date(start_value, start_field)
    end = _parse_date(end_value, end_field)
    if start > end:
        raise DateRangeError(f"{start_field} must be on or before {end_field}")
    return start, end


def extract_filters(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Pull and validate every filter from the request payload.

    Validation happens up front, before any data is read, so a malformed
    request never reaches the CSVs or the database.

    Args:
        payload: The decoded request body.

    Returns:
        A dict with ``country``, ``rating_range`` and ``type_range``; unset
        filters are ``None``.

    Raises:
        DateRangeError: If either date-range pair is incomplete or malformed.
    """
    country = payload.get("country")

    return {
        "country": None if _is_unset(country) else str(country).strip(),
        "rating_range": parse_date_pair(
            payload, "rating_start_date", "rating_end_date"
        ),
        "type_range": parse_date_pair(payload, "type_start_date", "type_end_date"),
    }


# --------------------------------------------------------------------------- #
# Mock data loading
# --------------------------------------------------------------------------- #
def _resolve_csv(table: str, directory: str) -> str:
    """Find one input CSV, preferring the plural filename.

    Args:
        table: Logical table name, a key of :data:`INPUT_FILENAMES`.
        directory: Directory to search.

    Returns:
        The path of the first candidate filename that exists.

    Raises:
        MockDataError: If no candidate filename is present.
    """
    candidates = INPUT_FILENAMES[table]
    for filename in candidates:
        path = os.path.join(directory, filename)
        if os.path.isfile(path):
            return path
    raise MockDataError(
        f"missing {table} CSV in {directory}; expected one of: "
        f"{', '.join(candidates)}"
    )


def load_organizations(directory: Optional[str] = None) -> pd.DataFrame:
    """Load the organizations fixture, resolved down to a country.

    Joins ``organizations.state_id -> states.state_id -> states.country_id ->
    countries.country_id`` so the ``country`` filter can accept either a
    country code or a country name. Organizations whose state or country does
    not resolve are kept, with a null country, rather than being dropped -
    they still belong in the unfiltered counts.

    Args:
        directory: Directory holding the CSVs; defaults to
            :func:`mock_data_dir`.

    Returns:
        A DataFrame with ``org_id``, ``org_rating`` (nullable integer),
        ``org_type``, ``created_at``, ``country_code`` and ``country_name``.

    Raises:
        MockDataError: If a CSV is missing or lacks a required column.
    """
    directory = directory or mock_data_dir()

    organizations = pd.read_csv(_resolve_csv("organizations", directory), dtype="string")
    states = pd.read_csv(_resolve_csv("states", directory), dtype="string")
    countries = pd.read_csv(_resolve_csv("countries", directory), dtype="string")

    required = {"org_id", "org_rating", "org_type", "state_id", "created_at"}
    missing = required.difference(organizations.columns)
    if missing:
        raise MockDataError(
            "organizations CSV missing required columns: "
            f"{', '.join(sorted(missing))}"
        )

    frame = organizations.copy()
    # Per-row coercion so one malformed value cannot fail the whole load.
    frame["created_at"] = pd.to_datetime(
        frame["created_at"], errors="coerce", format="mixed"
    )
    frame["org_rating"] = pd.to_numeric(
        frame["org_rating"], errors="coerce"
    ).astype("Int64")

    state_lookup = states.loc[:, ["state_id", "country_id"]].drop_duplicates("state_id")
    country_columns = [
        column
        for column in ("country_id", "country_code", "country_name")
        if column in countries.columns
    ]
    country_lookup = countries.loc[:, country_columns].drop_duplicates("country_id")

    frame = frame.merge(state_lookup, how="left", on="state_id", sort=False)
    frame = frame.merge(country_lookup, how="left", on="country_id", sort=False)
    for column in ("country_code", "country_name"):
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame


# --------------------------------------------------------------------------- #
# Filtering
# --------------------------------------------------------------------------- #
def apply_filters(frame: pd.DataFrame, filters: Mapping[str, Any]) -> pd.DataFrame:
    """Apply the ``country`` filter to both charts' source data.

    Matched on a normalized key against both the country code and the country
    name, so ``afg`` and ``Afghanistan`` both resolve.

    Args:
        frame: The loaded organizations frame.
        filters: The validated filter dict.

    Returns:
        A filtered view; the input is never mutated.
    """
    country = filters.get("country")
    if country is None:
        return frame

    key = _normalize_key(country)
    codes = frame["country_code"].map(_normalize_key)
    names = frame["country_name"].map(_normalize_key)
    return frame[(codes == key) | (names == key)]


def window_frame(
    frame: pd.DataFrame,
    start: Optional[date],
    end: Optional[date],
) -> pd.DataFrame:
    """Restrict a frame to organizations created within a window.

    Both bounds are inclusive. ``None`` for both means unbounded, which is how
    the ``All`` bucket is expressed.

    Args:
        frame: The frame to restrict.
        start: Inclusive lower bound, or ``None``.
        end: Inclusive upper bound, or ``None``.

    Returns:
        The rows inside the window. Rows whose ``created_at`` could not be
        parsed are excluded from every bounded window.
    """
    if start is None and end is None:
        return frame

    created = frame["created_at"]
    mask = created.notna()
    if start is not None:
        mask &= created >= pd.Timestamp(start)
    if end is not None:
        # Inclusive of the whole end date, not just its midnight.
        mask &= created < pd.Timestamp(end) + pd.Timedelta(days=1)
    return frame[mask]


def bucket_window(
    bucket: str, today: Optional[date] = None
) -> tuple[Optional[date], Optional[date]]:
    """Return the inclusive ``(start, end)`` window for a fixed bucket.

    Args:
        bucket: One of :data:`FIXED_BUCKETS`.
        today: Reference date; defaults to the current date.

    Returns:
        The window bounds. ``All`` returns ``(None, None)``.

    Raises:
        KeyError: If ``bucket`` is not a known fixed bucket.
    """
    offset = BUCKET_OFFSET_DAYS[bucket]
    if offset is None:
        return None, None
    reference = today or date.today()
    return reference - timedelta(days=offset), reference


# --------------------------------------------------------------------------- #
# Chart 1 - rating distribution (categorical)
# --------------------------------------------------------------------------- #
def build_rating_chart(frame: pd.DataFrame) -> list[RatingCount]:
    """Count organizations per star rating.

    Only ratings actually present in the window are emitted - the 1-5 scale is
    deliberately **not** zero-filled. Organizations with no rating are left out
    rather than collected into a bucket of their own.

    Args:
        frame: The window-scoped, filtered frame.

    Returns:
        One row per rating, ascending by rating so the chart reads left to
        right.
    """
    if frame.empty or "org_rating" not in frame.columns:
        return []

    ratings = frame["org_rating"].dropna()
    if ratings.empty:
        return []

    counts = ratings.value_counts()
    return [
        {"rating": int(rating), "count": int(count)}
        for rating, count in sorted(counts.items())
    ]


# --------------------------------------------------------------------------- #
# Chart 2 - organization mix trend (cumulative time series)
# --------------------------------------------------------------------------- #
def empty_mix_trend() -> dict[str, list[TrendPoint]]:
    """Return the mix trend with both series present and empty."""
    return {series: [] for series in SERIES_ORDER}


def build_mix_trend(
    frame: pd.DataFrame, granularity: str
) -> dict[str, list[TrendPoint]]:
    """Build the cumulative non-profit / for-profit series.

    Each series is a running total over the periods inside this window,
    restarting at zero - the counts are cumulative within the bucket, not
    carried forward from before it. Periods in which no organization of that
    type was created are omitted rather than repeated, so the series is sparse.

    Args:
        frame: The window-scoped, filtered frame.
        granularity: ``"day"`` or ``"month"``.

    Returns:
        Both series keys, always present, each a list of ``{"period",
        "count"}`` points ordered oldest first.

    Raises:
        KeyError: If ``granularity`` is not a supported value.
    """
    trend = empty_mix_trend()
    fmt = PERIOD_FORMAT[granularity]

    if frame.empty or "org_type" not in frame.columns:
        return trend

    working = frame.dropna(subset=["created_at"])
    if working.empty:
        return trend

    periods = working["created_at"].dt.strftime(fmt)
    # An unrecognized org_type resolves to None and is skipped, rather than
    # silently creating a third series the response contract does not allow.
    series_names = working["org_type"].map(
        lambda value: TYPE_SERIES_KEYS.get(_normalize_key(value))
    )

    for series in SERIES_ORDER:
        matching = periods[series_names == series]
        if matching.empty:
            continue
        running = 0
        points: list[TrendPoint] = []
        for period, count in matching.value_counts().sort_index().items():
            running += int(count)
            points.append({"period": str(period), "count": running})
        trend[series] = points

    return trend


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def empty_bucket() -> dict[str, Any]:
    """Return a bucket with both charts empty."""
    return {"rating_distribution": [], "organization_mix_trend": empty_mix_trend()}


def build_bucket(
    frame: pd.DataFrame,
    start: Optional[date],
    end: Optional[date],
    granularity: str,
) -> dict[str, Any]:
    """Build one bucket's two charts from a single window.

    Args:
        frame: The filtered frame, not yet window-scoped.
        start: Inclusive window start, or ``None`` for unbounded.
        end: Inclusive window end, or ``None`` for unbounded.
        granularity: Period granularity for the mix trend.

    Returns:
        A bucket holding exactly the two chart keys.
    """
    windowed = window_frame(frame, start, end)
    return {
        "rating_distribution": build_rating_chart(windowed),
        "organization_mix_trend": build_mix_trend(windowed, granularity),
    }


def build_analytics(
    frame: pd.DataFrame,
    filters: Mapping[str, Any],
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Assemble the whole response body.

    Applies the country filter once, then either computes the four fixed
    buckets or collapses to a Custom-only response, depending on which date
    ranges the request carried.

    Args:
        frame: The loaded organizations frame.
        filters: The validated filter dict from :func:`extract_filters`.
        today: Reference date for the fixed buckets; defaults to the current
            date. Supplied by tests so bucket windows are deterministic.

    Returns:
        Either the five fixed-bucket keys, or a single ``Custom`` key.
    """
    filtered = apply_filters(frame, filters)
    rating_range = filters.get("rating_range")
    type_range = filters.get("type_range")

    # Either Custom pair collapses the response to Custom only; each pair
    # drives its own chart from its own window, independently of the other.
    if rating_range or type_range:
        custom = empty_bucket()
        if rating_range:
            custom["rating_distribution"] = build_rating_chart(
                window_frame(filtered, *rating_range)
            )
        if type_range:
            custom["organization_mix_trend"] = build_mix_trend(
                window_frame(filtered, *type_range),
                BUCKET_GRANULARITY["Custom"],
            )
        return {"Custom": custom}

    response: dict[str, Any] = {}
    for bucket in FIXED_BUCKETS:
        start, end = bucket_window(bucket, today)
        response[bucket] = build_bucket(
            filtered, start, end, BUCKET_GRANULARITY[bucket]
        )
    response["Custom"] = empty_bucket()
    return response


# --------------------------------------------------------------------------- #
# PostgreSQL path
# --------------------------------------------------------------------------- #
def get_db_connection() -> Any:
    """Open a Postgres connection described entirely by environment variables.

    Built from ``DB_HOST``/``DB_NAME``/``DB_USER``/``DB_PASSWORD``/``DB_PORT``.
    There is intentionally no AWS Parameter Store fallback, so an
    unconfigured environment is an error rather than an implicit escalation to
    shared credentials.

    Returns:
        An open ``psycopg2`` connection.

    Raises:
        RuntimeError: If ``psycopg2`` is not installed or ``DB_HOST`` is unset.
    """
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is not installed; set USE_MOCK_DATA=true to run against "
            "the local CSV fixtures instead."
        )

    db_host = os.environ.get("DB_HOST")
    if not db_host:
        raise RuntimeError(
            "DB_HOST is not set. rating_type_analytics has no AWS Parameter "
            "Store fallback by design - set the DB_* environment variables, "
            "or use USE_MOCK_DATA=true."
        )

    return psycopg2.connect(
        host=db_host,
        database=os.environ.get("DB_NAME", "saayam_local"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
        port=os.environ.get("DB_PORT", "5432"),
    )


def load_organizations_from_db() -> pd.DataFrame:
    """Load the same organizations frame from PostgreSQL.

    The join and column names mirror :func:`load_organizations` so every chart
    function downstream is shared between the two paths.

    Returns:
        A DataFrame in the same shape :func:`load_organizations` returns.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            f"""
            SELECT o.org_id,
                   o.org_rating,
                   o.org_type,
                   o.created_at,
                   c.country_code,
                   c.country_name
            FROM {SCHEMA_NAME}.organizations o
            LEFT JOIN {SCHEMA_NAME}.state s   ON s.state_id = o.state_id
            LEFT JOIN {SCHEMA_NAME}.country c ON c.country_id = s.country_id
            """
        )
        frame = pd.DataFrame([dict(row) for row in cursor.fetchall()])
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    if frame.empty:
        return pd.DataFrame(
            columns=[
                "org_id", "org_rating", "org_type", "created_at",
                "country_code", "country_name",
            ]
        )
    frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce")
    frame["org_rating"] = pd.to_numeric(
        frame["org_rating"], errors="coerce"
    ).astype("Int64")
    return frame


def load_data() -> pd.DataFrame:
    """Load organizations from whichever source is configured."""
    if use_mock_data():
        return load_organizations()
    return load_organizations_from_db()


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #
def lambda_handler(
    event: Optional[dict[str, Any]], context: Any = None
) -> dict[str, Any]:
    """Serve the Rating & Type tab.

    Malformed filter input is rejected with ``400`` before any data is read.
    Anything else that fails returns ``500`` without leaking paths, rows or
    tracebacks; the detail goes to the log instead.

    Args:
        event: API Gateway proxy event or a plain invocation payload.
        context: Unused Lambda context object.

    Returns:
        An API Gateway proxy response from :func:`build_response`.
    """
    try:
        payload = parse_event_body(event)
        filters = extract_filters(payload)
    except RequestError as exc:
        LOGGER.warning("rating_type_analytics bad request: %s", exc)
        return build_response(400, {"error": str(exc)})

    try:
        frame = load_data()
        return build_response(200, build_analytics(frame, filters))
    except Exception:  # noqa: BLE001 - every remaining failure is a server error
        LOGGER.exception("rating_type_analytics request failed")
        return build_response(500, {"error": "internal server error"})


# --------------------------------------------------------------------------- #
# Local run
# --------------------------------------------------------------------------- #
def _sample_events() -> Sequence[tuple[str, dict[str, Any]]]:
    """Build the sample requests printed by the local runner.

    The Custom ranges are derived from the dates actually present in the
    configured CSVs, so the examples stay meaningful when the fixture changes.
    """
    try:
        created = load_organizations()["created_at"].dropna()
    except Exception:  # noqa: BLE001 - the runner still prints the error path
        created = pd.Series(dtype="datetime64[ns]")

    if created.empty:
        first = midpoint = last = "1970-01-01"
    else:
        ordered = created.sort_values()
        first = ordered.iloc[0].date().isoformat()
        last = ordered.iloc[-1].date().isoformat()
        midpoint = ordered.iloc[len(ordered) // 2].date().isoformat()

    return (
        ("No body", {}),
        ("Country filter", {"country": "AFG"}),
        (
            "Rating Custom range only",
            {"rating_start_date": first, "rating_end_date": midpoint},
        ),
        (
            "Type Custom range only",
            {"type_start_date": midpoint, "type_end_date": last},
        ),
        (
            "Both Custom ranges together",
            {
                "rating_start_date": first,
                "rating_end_date": midpoint,
                "type_start_date": midpoint,
                "type_end_date": last,
            },
        ),
        ("Validation error - half a pair", {"rating_start_date": first}),
    )


def _run_local_samples() -> None:
    """Invoke the real handler for each sample event and print the result."""
    for label, event in _sample_events():
        response = lambda_handler(event)
        print(f"=== {label} ===")
        print("Request:")
        print(json.dumps(event, indent=2))
        print(f"Response (HTTP {response['statusCode']}):")
        print(json.dumps(json.loads(response["body"]), indent=2))
        print()


if __name__ == "__main__":
    _run_local_samples()
