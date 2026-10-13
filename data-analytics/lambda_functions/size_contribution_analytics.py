"""Size & Contribution Analytics API (Issue #376).

A standalone AWS Lambda serving the **Size & Contribution** tab of the
Organization Analytics dashboard. Two charts:

* ``organizations_by_size`` - organization counts per ``org_size`` category.
* ``collaborator_vs_contributor`` - collaborator and contributor counts, each
  computed independently.

Response shape
--------------
The shape depends on which Custom date-range pairs the request carries:

============================  ==========================================
Request                       Top-level keys
============================  ==========================================
no Custom pair                ``7D``, ``30D``, ``1Y``, ``All``, ``Custom``
                              (``Custom`` present but empty)
``size_*`` only               ``Custom`` only - size populated
``contribution_*`` only       ``Custom`` only - contribution populated
both pairs                    ``Custom`` only - **both** populated, each
                              from its own range
============================  ==========================================

The two pairs are fully independent: either, both, or neither may be present,
and neither takes priority. The volunteer-side reference implementation has a
bug here - ``volunteer_application_analytics.py`` returns unconditionally
inside its first Custom branch, so a request carrying both pairs silently
loses the second. That behaviour is deliberately **not** reproduced.

Both charts are window-scoped snapshots: each bucket counts only the
organizations created inside that bucket's own window, after the ``country``
and ``organization_type`` filters are applied. Neither chart is cumulative.

Collaborator and contributor are not a partition
------------------------------------------------
``is_collaborator`` and ``is_contributor`` are two independent flags. An
organization may be both, or neither, so the two counts are not complements,
and they are not expected to sum to the bucket total or to 100%. Each
percentage is that count's share of the bucket's total organization count.
When ``is_contributor`` is missing from the data entirely, Contributor
degrades to ``0`` rather than failing the request.

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
from datetime import date, datetime, timedelta
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

# The four fixed buckets, always computed together when no Custom pair is sent.
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

# Values accepted as boolean true. The mock CSVs use three different
# encodings - TRUE/FALSE, True/False and a literal NULL - so the comparison is
# made on a lowercased string rather than on bool().
_TRUE_TOKENS = frozenset({"true", "t", "1", "yes", "y"})

SCHEMA_NAME = "virginia_dev_saayam_rdbms"


class SizeCount(TypedDict):
    """One row of the ``organizations_by_size`` chart."""

    size: str
    count: int


class ContributionCount(TypedDict):
    """One row of the ``collaborator_vs_contributor`` chart."""

    type: str
    count: int
    percentage: float


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
    single key ``"nonprofit"``, so a request filter matches however the value
    happens to be cased in the data.

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
        A dict with ``country``, ``organization_type``, ``size_range`` and
        ``contribution_range``; unset filters are ``None``.

    Raises:
        DateRangeError: If either date-range pair is incomplete or malformed.
    """
    country = payload.get("country")
    organization_type = payload.get("organization_type")

    return {
        "country": None if _is_unset(country) else str(country).strip(),
        "organization_type": (
            None if _is_unset(organization_type) else str(organization_type).strip()
        ),
        "size_range": parse_date_pair(payload, "size_start_date", "size_end_date"),
        "contribution_range": parse_date_pair(
            payload, "contribution_start_date", "contribution_end_date"
        ),
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


def _to_bool(series: pd.Series) -> pd.Series:
    """Coerce a mock-CSV boolean column to real booleans.

    The fixtures use ``TRUE``/``FALSE``, ``True``/``False`` and a literal
    ``NULL`` across different files, so the comparison is made on a lowercased
    string. Anything unrecognized becomes ``False``.
    """
    return series.astype("string").str.strip().str.lower().isin(_TRUE_TOKENS)


def load_organizations(directory: Optional[str] = None) -> pd.DataFrame:
    """Load the organizations fixture, resolved down to a country.

    Joins ``organizations.state_id -> states.state_id -> states.country_id ->
    countries.country_id`` so the ``country`` filter can accept either a
    country code or a country name. Organizations whose state or country does
    not resolve are kept, with a null country, rather than being dropped -
    they still belong in the size and contribution counts.

    Args:
        directory: Directory holding the CSVs; defaults to
            :func:`mock_data_dir`.

    Returns:
        A DataFrame with ``org_id``, ``org_size``, ``org_type``,
        ``is_collaborator``, ``is_contributor``, ``created_at``,
        ``country_code`` and ``country_name``.

    Raises:
        MockDataError: If a CSV is missing or lacks a required column.
    """
    directory = directory or mock_data_dir()

    organizations = pd.read_csv(_resolve_csv("organizations", directory), dtype="string")
    states = pd.read_csv(_resolve_csv("states", directory), dtype="string")
    countries = pd.read_csv(_resolve_csv("countries", directory), dtype="string")

    required = {"org_id", "org_size", "state_id", "created_at", "is_collaborator"}
    missing = required.difference(organizations.columns)
    if missing:
        raise MockDataError(
            "organizations CSV missing required columns: "
            f"{', '.join(sorted(missing))}"
        )

    frame = organizations.copy()
    # Per-row parsing so one malformed timestamp cannot fail the whole load.
    frame["created_at"] = pd.to_datetime(
        frame["created_at"], errors="coerce", format="mixed"
    )
    frame["is_collaborator"] = _to_bool(frame["is_collaborator"])
    if "is_contributor" in frame.columns:
        frame["is_contributor"] = _to_bool(frame["is_contributor"])
    if "org_type" not in frame.columns:
        frame["org_type"] = pd.NA

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
    """Apply the ``country`` and ``organization_type`` filters.

    Both are matched on a normalized key, so ``non_profit`` matches a stored
    ``Non-Profit`` and ``afg`` matches ``AFG``. ``country`` is compared against
    both the country code and the country name.

    Args:
        frame: The loaded organizations frame.
        filters: The validated filter dict.

    Returns:
        A filtered copy; the input is never mutated.
    """
    result = frame

    country = filters.get("country")
    if country is not None:
        key = _normalize_key(country)
        codes = result["country_code"].map(_normalize_key)
        names = result["country_name"].map(_normalize_key)
        result = result[(codes == key) | (names == key)]

    organization_type = filters.get("organization_type")
    if organization_type is not None:
        key = _normalize_key(organization_type)
        result = result[result["org_type"].map(_normalize_key) == key]

    return result


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
# Charts
# --------------------------------------------------------------------------- #
def build_size_chart(frame: pd.DataFrame) -> list[SizeCount]:
    """Count organizations per ``org_size`` category.

    Only categories actually present in the window are emitted, using the
    stored value verbatim - the list is not zero-filled against a hardcoded
    set of categories.

    Args:
        frame: The window-scoped, filtered frame.

    Returns:
        One row per size category, ordered by descending count then by size
        for deterministic output.
    """
    if frame.empty or "org_size" not in frame.columns:
        return []

    sizes = frame["org_size"].dropna()
    if sizes.empty:
        return []

    counts = sizes.value_counts()
    ordered = sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))
    return [{"size": str(size), "count": int(count)} for size, count in ordered]


def _percentage(count: int, total: int) -> float:
    """Return ``count`` as a percentage of ``total``, to one decimal place.

    Args:
        count: Numerator.
        total: Denominator; ``0`` yields ``0.0`` rather than raising.

    Returns:
        The percentage, or ``0.0`` when ``total`` is zero.
    """
    if not total:
        return 0.0
    return round(count * 100.0 / total, 1)


def build_contribution_chart(frame: pd.DataFrame) -> list[ContributionCount]:
    """Count collaborators and contributors independently.

    The two rows are **not** a partition: an organization can be both or
    neither, since ``is_collaborator`` and ``is_contributor`` are separate
    flags. Each count is measured against the window's total organization
    count, so the two need not sum to that total or to 100%.

    A missing ``is_contributor`` column degrades to ``0`` rather than raising,
    so the chart still renders against data where the column has not landed.

    Args:
        frame: The window-scoped, filtered frame.

    Returns:
        Exactly two rows, ``Collaborator`` then ``Contributor``, or ``[]``
        when the window holds no organizations.
    """
    total = int(len(frame))
    if not total:
        return []

    collaborators = (
        int(frame["is_collaborator"].fillna(False).sum())
        if "is_collaborator" in frame.columns
        else 0
    )
    contributors = (
        int(frame["is_contributor"].fillna(False).sum())
        if "is_contributor" in frame.columns
        else 0
    )

    return [
        {
            "type": "Collaborator",
            "count": collaborators,
            "percentage": _percentage(collaborators, total),
        },
        {
            "type": "Contributor",
            "count": contributors,
            "percentage": _percentage(contributors, total),
        },
    ]


def empty_bucket() -> dict[str, list]:
    """Return a bucket with both charts empty."""
    return {"organizations_by_size": [], "collaborator_vs_contributor": []}


def build_bucket(
    frame: pd.DataFrame,
    start: Optional[date],
    end: Optional[date],
    include_size: bool = True,
    include_contribution: bool = True,
) -> dict[str, list]:
    """Build one bucket's two charts from a single window.

    Args:
        frame: The filtered frame, not yet window-scoped.
        start: Inclusive window start, or ``None`` for unbounded.
        end: Inclusive window end, or ``None`` for unbounded.
        include_size: Whether to populate ``organizations_by_size``.
        include_contribution: Whether to populate
            ``collaborator_vs_contributor``.

    Returns:
        A bucket holding exactly the two chart keys.
    """
    windowed = window_frame(frame, start, end)
    return {
        "organizations_by_size": build_size_chart(windowed) if include_size else [],
        "collaborator_vs_contributor": (
            build_contribution_chart(windowed) if include_contribution else []
        ),
    }


def build_analytics(
    frame: pd.DataFrame,
    filters: Mapping[str, Any],
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Assemble the whole response body.

    Applies the shared filters once, then either computes the four fixed
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
    size_range = filters.get("size_range")
    contribution_range = filters.get("contribution_range")

    # Either Custom pair collapses the response to Custom only; each pair
    # drives its own chart from its own window, independently of the other.
    if size_range or contribution_range:
        custom = empty_bucket()
        if size_range:
            custom["organizations_by_size"] = build_size_chart(
                window_frame(filtered, *size_range)
            )
        if contribution_range:
            custom["collaborator_vs_contributor"] = build_contribution_chart(
                window_frame(filtered, *contribution_range)
            )
        return {"Custom": custom}

    response: dict[str, Any] = {}
    for bucket in FIXED_BUCKETS:
        start, end = bucket_window(bucket, today)
        response[bucket] = build_bucket(filtered, start, end)
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
            "DB_HOST is not set. size_contribution_analytics has no AWS "
            "Parameter Store fallback by design - set the DB_* environment "
            "variables, or use USE_MOCK_DATA=true."
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
                   o.org_size,
                   o.org_type,
                   o.is_collaborator,
                   o.is_contributor,
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
                "org_id", "org_size", "org_type", "is_collaborator",
                "is_contributor", "created_at", "country_code", "country_name",
            ]
        )
    frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce")
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
    """Serve the Size & Contribution tab.

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
        LOGGER.warning("size_contribution_analytics bad request: %s", exc)
        return build_response(400, {"error": str(exc)})

    try:
        frame = load_data()
        return build_response(200, build_analytics(frame, filters))
    except Exception:  # noqa: BLE001 - every remaining failure is a server error
        LOGGER.exception("size_contribution_analytics request failed")
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
        first = last = "1970-01-01"
        midpoint = "1970-01-01"
    else:
        ordered = created.sort_values()
        first = ordered.iloc[0].date().isoformat()
        last = ordered.iloc[-1].date().isoformat()
        midpoint = ordered.iloc[len(ordered) // 2].date().isoformat()

    return (
        ("No body", {}),
        ("Country filter", {"country": "AFG"}),
        ("Organization type filter", {"organization_type": "non_profit"}),
        (
            "Size Custom range only",
            {"size_start_date": first, "size_end_date": midpoint},
        ),
        (
            "Contribution Custom range only",
            {"contribution_start_date": midpoint, "contribution_end_date": last},
        ),
        (
            "Both Custom ranges together",
            {
                "size_start_date": first,
                "size_end_date": midpoint,
                "contribution_start_date": midpoint,
                "contribution_end_date": last,
            },
        ),
        (
            "Validation error - half a pair",
            {"size_start_date": first},
        ),
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
