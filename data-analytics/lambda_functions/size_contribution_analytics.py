"""Size & Contribution Analytics Lambda (Issue #376).

Standalone analytics function for the "Size & Contribution" tab of the
Organization Analytics dashboard: Organizations By Size and Collaborators vs
Contributors. This is a fresh implementation (not a refactor of
``organization_analytics.py``), following the same request/response pattern
as the Growth & Location Analytics API.

Local testing uses mock CSV data (``USE_MOCK_DATA`` / ``MOCK_DATA_DIR``) via
pandas, exactly as required by the issue. The real Postgres path uses
``psycopg2``, imported optionally so this module still loads (and the mock
path still works) in environments where ``psycopg2`` isn't installed.

NOTE: This module implements the full issue #376 scope with one documented
exception (the live-Postgres data loader -- see ``load_live_data()``'s
docstring for the schema-verification blocker):
    - optional ``psycopg2`` import
    - mock-data configuration (``USE_MOCK_DATA`` / ``MOCK_DATA_DIR``)
    - ``load_mock_data()``: loads + joins the organizations/states/countries
      mock CSVs
    - reusable ``country`` / ``organization_type`` filters
    - date-pair validation for the ``size_*`` / ``contribution_*`` Custom
      range filters
    - ``organizations_by_size()`` and ``collaborator_vs_contributor()``
      chart calculations
    - ``build_size_contribution_response()``: the fixed-bucket
      (``7D``/``30D``/``1Y``/``All``) and Custom-range response assembly
      described in the issue
    - ``lambda_handler()``: the AWS Lambda / API Gateway entry point
    - ``get_db_connection()`` / ``load_live_data()``: the optional live-DB
      path (connection works; the query itself is intentionally NOT
      implemented -- see blocker above)
    - an ``if __name__ == "__main__":`` block running six local scenarios
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

try:
    import psycopg2  # noqa: F401  (optional: only needed for the live-DB path)
except ImportError:  # pragma: no cover - expected in mock-data-only environments
    psycopg2 = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _str_to_bool(value: str) -> bool:
    """Parse a truthy/falsy environment variable string into a bool."""
    return value.strip().lower() in ("1", "true", "yes", "on")


# When True (default), data is read from local mock CSVs via pandas instead
# of a live Postgres connection. Matches the ``USE_MOCK_DATA`` pattern
# required by issue #376.
USE_MOCK_DATA: bool = _str_to_bool(os.environ.get("USE_MOCK_DATA", "true"))

# Directory containing organizations.csv / states.csv / countries.csv for
# local testing. Defaults to the repo's existing mock-data-generation
# directory (sibling of data-analytics/lambda_functions/).
_DEFAULT_MOCK_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "mock-data-generation",
)
MOCK_DATA_DIR: str = os.environ.get("MOCK_DATA_DIR", _DEFAULT_MOCK_DATA_DIR)

ALL_FILTER_VALUE = "ALL"

ORGANIZATIONS_CSV = "organizations.csv"
STATES_CSV = "states.csv"
COUNTRIES_CSV = "countries.csv"


class DateRangeError(ValueError):
    """Raised when a start/end date pair is missing, malformed, or inverted."""


# ---------------------------------------------------------------------------
# Mock data loading
# ---------------------------------------------------------------------------

def load_mock_data(mock_data_dir: Optional[str] = None) -> pd.DataFrame:
    """Load and join the organizations/states/countries mock CSVs.

    Reads ``organizations.csv``, ``states.csv``, and ``countries.csv`` from
    ``mock_data_dir`` (defaults to :data:`MOCK_DATA_DIR`) and resolves each
    organization's country by joining
    ``organizations.state_id -> states.country_id -> countries.country_id``.

    Args:
        mock_data_dir: Directory containing the three CSV files. Defaults to
            :data:`MOCK_DATA_DIR` when not provided.

    Returns:
        A copy of the organizations DataFrame with ``country_id``,
        ``country_code``, and ``country_name`` columns joined in, and
        ``created_at`` parsed to ``datetime64`` (unparseable or missing
        values become ``NaT`` rather than raising).

    Raises:
        FileNotFoundError: If any of the three expected CSV files is missing
            from ``mock_data_dir``.
    """
    data_dir = mock_data_dir or MOCK_DATA_DIR

    org_path = os.path.join(data_dir, ORGANIZATIONS_CSV)
    states_path = os.path.join(data_dir, STATES_CSV)
    countries_path = os.path.join(data_dir, COUNTRIES_CSV)

    for path in (org_path, states_path, countries_path):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Required mock data file not found: {path}")

    organizations_df = pd.read_csv(org_path)
    states_df = pd.read_csv(states_path)
    countries_df = pd.read_csv(countries_path)

    # organizations.state_id -> states.country_id
    merged_df = organizations_df.merge(
        states_df[["state_id", "country_id"]],
        on="state_id",
        how="left",
    )

    # states.country_id -> countries.country_code / country_name
    merged_df = merged_df.merge(
        countries_df[["country_id", "country_code", "country_name"]],
        on="country_id",
        how="left",
    )

    # Parse created_at safely: unparseable/missing values become NaT instead
    # of raising, so one bad row can't crash the whole load.
    merged_df["created_at"] = pd.to_datetime(merged_df["created_at"], errors="coerce")

    return merged_df


# ---------------------------------------------------------------------------
# Reusable filters
# ---------------------------------------------------------------------------

def filter_by_country(df: pd.DataFrame, country: Optional[str] = None) -> pd.DataFrame:
    """Filter organizations by country name or country code.

    Args:
        df: Organizations DataFrame, must include ``country_code`` and
            ``country_name`` columns (as produced by :func:`load_mock_data`).
        country: Country name (e.g. ``"UNITED_STATES"``) or country code
            (e.g. ``"USA"``), case-insensitive. ``None`` or ``"ALL"``
            (any case) returns ``df`` unfiltered.

    Returns:
        A new, filtered DataFrame. ``df`` itself is not mutated.
    """
    if country is None or str(country).strip().upper() == ALL_FILTER_VALUE:
        return df

    needle = str(country).strip().upper()
    code_match = df["country_code"].astype(str).str.upper() == needle
    name_match = df["country_name"].astype(str).str.upper() == needle
    return df[code_match | name_match]


def filter_by_organization_type(df: pd.DataFrame, organization_type: Optional[str] = None) -> pd.DataFrame:
    """Filter organizations by ``org_type``.

    Args:
        df: Organizations DataFrame, must include an ``org_type`` column.
        organization_type: ``"non_profit"`` or ``"for_profit"``,
            case-insensitive. ``None`` or ``"ALL"`` (any case) returns
            ``df`` unfiltered.

    Returns:
        A new, filtered DataFrame. ``df`` itself is not mutated.
    """
    if organization_type is None or str(organization_type).strip().upper() == ALL_FILTER_VALUE:
        return df

    needle = str(organization_type).strip().lower()
    return df[df["org_type"].astype(str).str.lower() == needle]


def apply_common_filters(
    df: pd.DataFrame,
    country: Optional[str] = None,
    organization_type: Optional[str] = None,
) -> pd.DataFrame:
    """Apply the shared ``country`` and ``organization_type`` filters together.

    Args:
        df: Organizations DataFrame.
        country: See :func:`filter_by_country`.
        organization_type: See :func:`filter_by_organization_type`.

    Returns:
        A new DataFrame filtered by both criteria.
    """
    filtered_df = filter_by_country(df, country)
    filtered_df = filter_by_organization_type(filtered_df, organization_type)
    return filtered_df


# ---------------------------------------------------------------------------
# Date-pair validation
# ---------------------------------------------------------------------------

def validate_date_pair(
    start_date: Optional[str],
    end_date: Optional[str],
    start_field: str = "start_date",
    end_field: str = "end_date",
) -> Optional[Tuple[datetime, datetime]]:
    """Validate a start/end date pair for a Custom date-range filter.

    Rules (per issue #376's "proper error handling" requirement):
        * Neither ``start_date`` nor ``end_date`` supplied -> the pair is
          considered absent. Returns ``None`` (not an error).
        * Exactly one of the two supplied -> :class:`DateRangeError`
          ("missing half of a pair").
        * Both supplied but either fails to parse as ``YYYY-MM-DD`` ->
          :class:`DateRangeError`.
        * Both parse but ``start_date`` is after ``end_date`` ->
          :class:`DateRangeError`.

    Args:
        start_date: Start date string, expected format ``YYYY-MM-DD``.
        end_date: End date string, expected format ``YYYY-MM-DD``.
        start_field: Field name used in error messages (lets callers
            distinguish the ``size_*`` vs ``contribution_*`` pairs).
        end_field: Field name used in error messages.

    Returns:
        ``None`` if neither date was supplied; otherwise a
        ``(start, end)`` tuple of parsed :class:`datetime.datetime` objects.

    Raises:
        DateRangeError: On a missing half, malformed date, or start > end.
    """
    has_start = start_date is not None and str(start_date).strip() != ""
    has_end = end_date is not None and str(end_date).strip() != ""

    if not has_start and not has_end:
        return None

    if has_start != has_end:
        missing_field = end_field if has_start else start_field
        raise DateRangeError(
            f"Both '{start_field}' and '{end_field}' are required together; "
            f"'{missing_field}' is missing."
        )

    try:
        parsed_start = datetime.strptime(str(start_date).strip(), "%Y-%m-%d")
    except ValueError as exc:
        raise DateRangeError(
            f"'{start_field}' must be in YYYY-MM-DD format, got: {start_date!r}"
        ) from exc

    try:
        parsed_end = datetime.strptime(str(end_date).strip(), "%Y-%m-%d")
    except ValueError as exc:
        raise DateRangeError(
            f"'{end_field}' must be in YYYY-MM-DD format, got: {end_date!r}"
        ) from exc

    if parsed_start > parsed_end:
        raise DateRangeError(
            f"'{start_field}' ({start_date}) must not be after '{end_field}' ({end_date})."
        )

    return parsed_start, parsed_end


# ---------------------------------------------------------------------------
# Chart calculations
# ---------------------------------------------------------------------------

# String representations treated as boolean True when a flag column isn't
# already a native bool dtype (covers real booleans plus common mock-data /
# CSV / JSON string encodings). Anything else (including "false"/"no"/"0"
# and any unrecognized value) falls through to False in _coerce_bool_series.
_TRUTHY_STRINGS = {"true", "1", "yes", "y", "t"}


def _coerce_bool_series(series: pd.Series) -> pd.Series:
    """Safely coerce a column of real booleans or boolean-like strings to bool.

    Handles native ``bool`` values, and common string representations such
    as ``"True"``/``"false"``, ``"1"``/``"0"``, and ``"yes"``/``"no"``
    (case-insensitive). Missing values (``NaN``/``None``) and any
    unrecognized value are treated as ``False`` rather than raising, so a
    single messy row can't crash the calculation.

    Args:
        series: A pandas Series expected to represent a boolean flag.

    Returns:
        A ``bool``-dtype Series of the same length as ``series``.
    """
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)

    def _parse_one(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if pd.isna(value):
            return False
        text = str(value).strip().lower()
        if text in _TRUTHY_STRINGS:
            return True
        # Anything not recognized as truthy ("false"/"no"/"0" and any
        # unexpected value) is treated as False rather than raising.
        return False

    return series.apply(_parse_one).astype(bool)


def organizations_by_size(df: pd.DataFrame) -> List[Dict[str, Union[str, int]]]:
    """Count organizations grouped by ``org_size``.

    Uses only the ``org_size`` category values actually present in ``df`` --
    categories are never hardcoded (e.g. no assumption of exactly
    ``small``/``medium``/``large``) and absent categories are never
    zero-filled, per issue #376's "omit empty periods" rule.

    Args:
        df: Organizations DataFrame, already filtered/windowed by the
            caller, expected to include an ``org_size`` column.

    Returns:
        A list of ``{"size": <value>, "count": <int>}`` dicts, one per
        distinct ``org_size`` value present, ordered by descending count
        (matching the issue's sample responses). Returns ``[]`` for an
        empty DataFrame or if ``org_size`` is missing entirely.
    """
    if df.empty or "org_size" not in df.columns:
        return []

    size_counts = df["org_size"].dropna().value_counts()
    return [
        {"size": size, "count": int(count)}
        for size, count in size_counts.items()
    ]


def collaborator_vs_contributor(df: pd.DataFrame) -> List[Dict[str, Union[str, int, float]]]:
    """Compute independent Collaborator / Contributor counts and percentages.

    ``is_collaborator`` and ``is_contributor`` are independent flags, not a
    partition of each other -- an organization can be both, neither, or only
    one. Each count/percentage is computed independently against the total
    number of organizations in ``df``; the two rows are not required to sum
    to that total or to 100%, and Contributor is never derived as the
    complement of Collaborator.

    Args:
        df: Organizations DataFrame, already filtered/windowed by the
            caller, expected to include an ``is_collaborator`` column and
            optionally an ``is_contributor`` column. Values may be native
            booleans or common string encodings (``"True"``/``"false"``,
            ``"1"``/``"0"``, ``"yes"``/``"no"``), handled via
            :func:`_coerce_bool_series`.

    Returns:
        Exactly two dicts, in this order:
            ``{"type": "Collaborator", "count": <int>, "percentage": <float>}``
            ``{"type": "Contributor", "count": <int>, "percentage": <float>}``
        Percentages are each count's share of ``len(df)``, rounded to 1
        decimal place. For an empty DataFrame, both rows are zero-count,
        zero-percentage (no division by zero). If ``is_contributor`` is
        missing from ``df``, the Contributor row is zero-count,
        zero-percentage rather than raising.
    """
    total = len(df)

    if total == 0:
        return [
            {"type": "Collaborator", "count": 0, "percentage": 0.0},
            {"type": "Contributor", "count": 0, "percentage": 0.0},
        ]

    if "is_collaborator" in df.columns:
        collaborator_count = int(_coerce_bool_series(df["is_collaborator"]).sum())
    else:
        collaborator_count = 0

    if "is_contributor" in df.columns:
        contributor_count = int(_coerce_bool_series(df["is_contributor"]).sum())
    else:
        contributor_count = 0

    collaborator_percentage = round((collaborator_count / total) * 100, 1)
    contributor_percentage = round((contributor_count / total) * 100, 1)

    return [
        {"type": "Collaborator", "count": collaborator_count, "percentage": collaborator_percentage},
        {"type": "Contributor", "count": contributor_count, "percentage": contributor_percentage},
    ]


# ---------------------------------------------------------------------------
# Time-window filtering & response assembly
# ---------------------------------------------------------------------------

# Fixed bucket keys returned when no Custom date-range params are supplied,
# in response order. "Custom" is added separately (it's not reference-date
# bounded the same way).
FIXED_TIME_BUCKETS: Tuple[str, ...] = ("7D", "30D", "1Y", "All")


def get_window_bounds(
    bucket: str,
    reference_date: datetime,
) -> Optional[Tuple[datetime, datetime]]:
    """Resolve the inclusive ``[start, end]`` bounds for a fixed time bucket.

    Calendar-date aligned (``CURRENT_DATE`` semantics, like
    ``kpi_api_analytics.py``'s ``CURRENT_DATE - INTERVAL 'N days'``), not an
    exact-timestamp subtraction -- so each bucket spans a whole number of
    calendar dates anchored on "today" (``reference_date``'s date), and
    future-dated rows are always excluded (``created_at`` can't exceed the
    end-of-today upper bound):

        * ``"7D"``  -> ``[today - 6 days, end_of_today]`` (7 calendar dates
          incl. today)
        * ``"30D"`` -> ``[today - 29 days, end_of_today]`` (30 calendar
          dates incl. today)
        * ``"1Y"``  -> ``[today - 12 calendar months, end_of_today]``, via
          ``pandas.DateOffset(years=1)`` for leap-year-correct arithmetic
          (mirrors ``CURRENT_DATE - INTERVAL '1 year'``)
        * ``"All"`` -> ``None`` (unbounded -- "all records"; not
          future-date-capped since it isn't a dated window)

    Args:
        bucket: One of ``"7D"``, ``"30D"``, ``"1Y"``, ``"All"``.
        reference_date: The "now" the trailing windows are measured back
            from (injectable for deterministic tests; only its calendar
            date matters for bounded buckets).

    Returns:
        An inclusive ``(start, end)`` tuple, or ``None`` for ``"All"``.

    Raises:
        ValueError: If ``bucket`` isn't one of the four fixed buckets.
    """
    today = datetime.combine(reference_date.date(), datetime.min.time())
    end_of_today = datetime.combine(reference_date.date(), datetime.max.time())

    if bucket == "7D":
        return today - timedelta(days=6), end_of_today
    if bucket == "30D":
        return today - timedelta(days=29), end_of_today
    if bucket == "1Y":
        return today - pd.DateOffset(years=1), end_of_today
    if bucket == "All":
        return None
    raise ValueError(f"Unknown fixed time bucket: {bucket!r}")


def filter_by_created_at_window(
    df: pd.DataFrame,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> pd.DataFrame:
    """Filter organizations whose ``created_at`` falls within ``[start, end]``.

    Both bounds are inclusive. Rows with missing/invalid ``created_at``
    (``NaT``, from :func:`load_mock_data`'s ``errors="coerce"`` parsing) are
    excluded whenever the window is bounded, so they're never incorrectly
    counted inside a dated window. When both ``start`` and ``end`` are
    ``None`` (the ``"All"`` bucket), ``df`` is returned unmodified --
    ``"All"`` means all records, dated or not.

    Args:
        df: Organizations DataFrame, expected to include ``created_at``
            when either bound is supplied.
        start: Inclusive lower bound, or ``None`` for no lower bound.
        end: Inclusive upper bound, or ``None`` for no upper bound.

    Returns:
        A new, filtered DataFrame.
    """
    if start is None and end is None:
        return df

    if "created_at" not in df.columns:
        return df.iloc[0:0]

    windowed_df = df[df["created_at"].notna()]
    if start is not None:
        windowed_df = windowed_df[windowed_df["created_at"] >= start]
    if end is not None:
        windowed_df = windowed_df[windowed_df["created_at"] <= end]
    return windowed_df


def _inclusive_end_of_day(value: datetime) -> datetime:
    """Push a date/midnight-datetime to the last microsecond of that day.

    Custom range endpoints are parsed by :func:`validate_date_pair` from
    plain ``YYYY-MM-DD`` strings, which land at midnight (``00:00:00``).
    Used as-is, an inclusive ``created_at <= end`` comparison would exclude
    every row created later that same calendar day. This expands ``end`` to
    ``23:59:59.999999`` so the whole end date is included.

    Args:
        value: A ``datetime`` (typically at midnight).

    Returns:
        A ``datetime`` for the same calendar date, at the last microsecond.
    """
    return datetime.combine(value.date(), datetime.max.time())


def _empty_chart_bucket() -> Dict[str, list]:
    """Return a bucket shape with both charts empty (``[]``)."""
    return {"organizations_by_size": [], "collaborator_vs_contributor": []}


def build_fixed_bucket(
    df: pd.DataFrame,
    bucket: str,
    reference_date: datetime,
) -> Dict[str, list]:
    """Build one fixed bucket's (``7D``/``30D``/``1Y``/``All``) chart payload.

    The DataFrame passed in is expected to already have the
    ``country``/``organization_type`` filters applied -- this function only
    applies the bucket's own ``created_at`` window on top, so both charts
    are window-scoped (a snapshot of that window), never cumulative.

    Args:
        df: Country/organization_type-filtered organizations DataFrame.
        bucket: One of ``"7D"``, ``"30D"``, ``"1Y"``, ``"All"``.
        reference_date: "Now" for the trailing-window calculation.

    Returns:
        ``{"organizations_by_size": [...], "collaborator_vs_contributor": [...]}``
        computed from the rows whose ``created_at`` falls in that bucket's
        window.
    """
    bounds = get_window_bounds(bucket, reference_date)
    start, end = bounds if bounds is not None else (None, None)
    windowed_df = filter_by_created_at_window(df, start, end)
    return {
        "organizations_by_size": organizations_by_size(windowed_df),
        "collaborator_vs_contributor": collaborator_vs_contributor(windowed_df),
    }


def build_size_contribution_response(
    df: pd.DataFrame,
    country: Optional[str] = None,
    organization_type: Optional[str] = None,
    size_start_date: Optional[str] = None,
    size_end_date: Optional[str] = None,
    contribution_start_date: Optional[str] = None,
    contribution_end_date: Optional[str] = None,
    reference_date: Optional[datetime] = None,
) -> Dict[str, Dict[str, list]]:
    """Build the full Size & Contribution Analytics response (issue #376).

    Applies the ``country``/``organization_type`` filters once, up front
    (``ALL``/``None`` = no filtering), then branches on whether either
    Custom date-range pair was supplied:

        * **Neither pair** -- returns the 5 top-level keys ``"7D"``,
          ``"30D"``, ``"1Y"``, ``"All"``, ``"Custom"``. Each fixed bucket is
          window-scoped (not cumulative); ``"Custom"`` is both charts empty.
        * **Either/both pairs** -- returns exactly ``{"Custom": {...}}`` (no
          fixed buckets). ``organizations_by_size`` is populated iff
          ``size_start_date``/``size_end_date`` was given;
          ``collaborator_vs_contributor`` iff
          ``contribution_start_date``/``contribution_end_date`` was given --
          independently, no priority, no silent dropping of either.

    Both pairs are validated via :func:`validate_date_pair` regardless of
    branch, so a lone half-pair (e.g. ``size_start_date`` with nothing else)
    always raises rather than being treated as "no Custom params".

    Args:
        df: Organizations DataFrame as returned by :func:`load_mock_data`
            (or an equivalent live-DB DataFrame) -- must include
            ``org_size``, ``is_collaborator``, ``created_at``, ``org_type``,
            ``country_code``, ``country_name`` (``is_contributor`` is
            optional, per :func:`collaborator_vs_contributor`).
        country: See :func:`filter_by_country`.
        organization_type: See :func:`filter_by_organization_type`.
        size_start_date / size_end_date: Custom range (``YYYY-MM-DD``,
            inclusive) for ``organizations_by_size``; both or neither.
        contribution_start_date / contribution_end_date: Custom range
            (``YYYY-MM-DD``, inclusive) for ``collaborator_vs_contributor``;
            both or neither.
        reference_date: "Now" for the ``7D``/``30D``/``1Y`` windows.
            Defaults to :func:`datetime.now`; injectable for deterministic
            tests.

    Returns:
        The full 5-key dict or the Custom-only 1-key dict described above --
        plain ``dict``/``list``/``str``/``int``/``float``, directly
        JSON-serializable.

    Raises:
        DateRangeError: If either date-range pair is incomplete, malformed,
            or has ``start`` after ``end``.
    """
    effective_reference_date = reference_date if reference_date is not None else datetime.now()

    filtered_df = apply_common_filters(df, country=country, organization_type=organization_type)

    # Validate both pairs up front, unconditionally, so malformed/partial
    # input is rejected even when it wouldn't otherwise change the response
    # shape (e.g. a lone start date with no end date).
    size_range = validate_date_pair(size_start_date, size_end_date, "size_start_date", "size_end_date")
    contribution_range = validate_date_pair(
        contribution_start_date, contribution_end_date, "contribution_start_date", "contribution_end_date"
    )

    if size_range is None and contribution_range is None:
        response: Dict[str, Dict[str, list]] = {
            bucket: build_fixed_bucket(filtered_df, bucket, effective_reference_date)
            for bucket in FIXED_TIME_BUCKETS
        }
        response["Custom"] = _empty_chart_bucket()
        return response

    custom_bucket = _empty_chart_bucket()

    if size_range is not None:
        size_start, size_end = size_range
        size_windowed_df = filter_by_created_at_window(
            filtered_df, size_start, _inclusive_end_of_day(size_end)
        )
        custom_bucket["organizations_by_size"] = organizations_by_size(size_windowed_df)

    if contribution_range is not None:
        contribution_start, contribution_end = contribution_range
        contribution_windowed_df = filter_by_created_at_window(
            filtered_df, contribution_start, _inclusive_end_of_day(contribution_end)
        )
        custom_bucket["collaborator_vs_contributor"] = collaborator_vs_contributor(contribution_windowed_df)

    return {"Custom": custom_bucket}


# ---------------------------------------------------------------------------
# Live-database path (connection implemented; query intentionally NOT --
# see load_live_data()'s docstring for the schema-verification blocker)
# ---------------------------------------------------------------------------

def get_db_connection():
    """Open a Postgres connection for the live-database path.

    Reads connection parameters entirely from environment variables
    (``DB_HOST``, ``DB_PORT``, ``DB_NAME``, ``DB_USER``, ``DB_PASSWORD``) --
    the same variable names already used by
    ``data-engineering/src/main.py``'s ``get_db_connection()`` /
    ``data-engineering/.env.example`` -- rather than the ``boto3``/AWS
    Parameter Store pattern used by this directory's other standalone
    Lambdas (``kpi_api_analytics.py``, ``beneficiariesTrendAnalysis.py``).
    That SSM-based pattern is not used here because issue #376 explicitly
    restricts this module's dependencies to ``pandas``, optional
    ``psycopg2``, and the standard library -- ``boto3`` is not on that list.

    No credentials, hosts, or connection strings are hardcoded anywhere in
    this module; every value comes from the environment, and callers are
    responsible for populating it (e.g. via a local ``.env`` file, never
    committed).

    Returns:
        A new, open ``psycopg2`` connection.

    Raises:
        RuntimeError: If ``psycopg2`` isn't installed -- it's required for
            this path (``USE_MOCK_DATA=false``).
    """
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is not installed. It is required for the live-database "
            "path (USE_MOCK_DATA=false); install it or set USE_MOCK_DATA=true "
            "to use the local mock-data path instead."
        )
    return psycopg2.connect(
        host=os.environ.get("DB_HOST"),
        port=os.environ.get("DB_PORT"),
        dbname=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
    )


def load_live_data(conn) -> pd.DataFrame:
    """Load organizations data from the live Postgres database.

    **Intentionally not implemented -- a documented blocker, not an
    oversight.** Per issue #376's instruction to "inspect the available
    schema before constructing SQL" and "explain the blocker instead of
    inventing a production-ready implementation," every schema-related
    artifact in this repository was checked. All of them agree the columns
    this issue needs are unconfirmed in production:

        1. ``database/Saayam_Table.column.names_data.xlsx`` (also mirrored
           at ``data-analytics/sql/``) is the closest thing to an
           authoritative real-schema export in this repo (a
           table/column/primary-key dump, schema-prefixed
           ``virginia_dev_saayam_rdbms``, the same schema this issue's data
           lives in). For the ``organizations`` table it lists exactly one
           confirmed column: ``org_id`` (its primary key). It does not list
           ``org_size``, ``is_collaborator``, ``is_contributor``,
           ``org_rating``, ``created_at``, ``country_code``, or
           ``country_name`` anywhere, for any table. Related tables fare no
           better for this issue's needs: ``state``/``country`` each list
           only their own primary key (no confirmed ``country_id`` join
           column on ``state``); and a separate ``user_org_map`` table
           (``user_id`` + ``org_id`` + ``user_role`` + ``created_at`` +
           ``last_updated_at``) suggests collaborator/contributor status may
           actually be modeled as a *role on a user-organization mapping
           table* in production, not as two independent boolean columns
           directly on ``organizations`` the way the mock CSVs assume.
        2. ``data-engineering/infrastructure/db/init/001_organizations.sql``
           (seeded for the separate, already-merged issue #228 FastAPI
           endpoint) explicitly flags its own columns as unverified: "org_size,
           rating, and registered_at are ASSUMED (no DDL for this table
           exists in the repo) -- verify against the real
           virginia_dev_saayam_rdbms.organizations table." It also has no
           ``is_contributor`` column, uses ``registered_at`` not
           ``created_at``, and capitalizes ``org_size`` values
           (``"Small"``/``"Medium"``/``"Large"``) rather than this issue's
           lowercase enum.
        3. An now-deleted local-dev schema from issue #228's history
           (``data-analytics/sql/organizations_schema.sql``, commit
           ``6a8ad11``) did include ``is_contributor``, but its own header
           comment says: "is_contributor is a NEW field that may not yet be
           present in the current dev database ... NOT YET IN DEV DB."
        4. The mock CSV's ``org_size``/``org_rating``/``is_collaborator``/
           ``is_contributor`` columns were added by issue #301's mock-data
           generator commit explicitly as "aliases ... so the CSV matches
           both db_info and the issue contract" -- i.e. shaped to satisfy
           the issue spec, not copied from a confirmed production table.

    Writing SQL against unverified/mismatched columns would either crash at
    runtime or silently produce wrong numbers in production, so this
    function raises rather than guessing. What the team needs to confirm
    before this path can be implemented: the real DDL (or a
    ``\\d+ virginia_dev_saayam_rdbms.organizations`` / equivalent) for
    ``organizations``, ``states``, and ``countries`` -- specifically whether
    ``is_contributor`` exists (or collaborator/contributor is modeled via
    ``user_org_map.user_role`` instead), the real ``created_at``-equivalent
    column name, the real ``org_size`` enum casing, and the real
    state/country join path. Local development and testing should use
    ``USE_MOCK_DATA=true`` (the default) instead.

    Args:
        conn: An open ``psycopg2`` connection (see :func:`get_db_connection`).

    Raises:
        NotImplementedError: Always, until the real schema is confirmed.
    """
    raise NotImplementedError(
        "Live-database loading is not implemented: the organizations table's "
        "is_contributor/created_at/state_id-country_id columns have not been "
        "verified against a real schema (see load_live_data() docstring for "
        "details). Use USE_MOCK_DATA=true for local development and testing."
    )


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def build_response(status_code: int, body: Dict) -> Dict:
    """Build the standard Lambda response envelope.

    Mirrors ``kpi_api_analytics.py``'s ``build_response()`` exactly: a plain,
    JSON-serializable ``body`` dict (not pre-serialized to a string), a
    ``statusCode``, and permissive CORS headers.

    Args:
        status_code: The HTTP status code to report.
        body: A JSON-serializable dict.

    Returns:
        ``{"statusCode": ..., "headers": {...}, "body": ...}``.
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": body,
    }


def _extract_event_params(event: object) -> Dict:
    """Extract the filter parameters dict from a raw Lambda ``event``.

    Supports two shapes:
        * **Direct invocation** -- ``event`` itself *is* the params dict
          (e.g. ``{"country": "USA"}``), as used when this Lambda is
          invoked directly (not through API Gateway).
        * **API Gateway proxy integration** -- ``event["body"]`` is a JSON
          *string* holding the params dict. A missing/``None``/empty body is
          treated the same as ``{}`` (no filters). A ``body`` that's already
          a dict (some direct-invoke test harnesses do this) is accepted
          as-is, without requiring re-serialization.

    Args:
        event: The raw Lambda event.

    Returns:
        The parsed params dict (``{}`` if there are no params).

    Raises:
        ValueError: If ``event["body"]`` is present, non-empty, and is not
            valid JSON.
    """
    if not isinstance(event, dict):
        return {}

    if "body" in event:
        raw_body = event.get("body")
        if raw_body is None or raw_body == "":
            return {}
        if isinstance(raw_body, dict):
            return raw_body
        try:
            parsed = json.loads(raw_body)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Malformed JSON in request body: {exc}") from exc
        return parsed if isinstance(parsed, dict) else {}

    return event


def lambda_handler(event, context):
    """AWS Lambda entry point for the Size & Contribution Analytics API.

    Parses ``country``, ``organization_type``, ``size_start_date``,
    ``size_end_date``, ``contribution_start_date``, and
    ``contribution_end_date`` from ``event`` (direct invocation or an API
    Gateway JSON-string ``body``, per :func:`_extract_event_params`), loads
    the organizations data (mock CSVs when ``USE_MOCK_DATA=true``, the
    live database otherwise), and delegates every calculation to
    :func:`build_size_contribution_response` -- no analytics logic is
    duplicated here.

    Status codes:
        * ``200`` -- success; ``body`` is the analytics response described
          in :func:`build_size_contribution_response`.
        * ``400`` -- malformed request JSON, or an invalid Custom date range
          (missing half of a pair, bad format, or ``start`` after ``end``).
        * ``500`` -- the data source (mock CSVs or live database) couldn't
          be loaded. The response body never includes credentials, file
          paths, connection details, or raw exception text -- those are
          logged server-side via ``print()`` only.

    Args:
        event: The raw Lambda event (direct dict or API Gateway proxy event).
        context: The Lambda context object (unused; accepted for the
            standard ``lambda_handler(event, context)`` signature).

    Returns:
        The standard response envelope from :func:`build_response`.
    """
    try:
        params = _extract_event_params(event)
    except ValueError as exc:
        print(f"Malformed request body: {exc}")
        return build_response(400, {"error": "Malformed request body. Expected valid JSON."})

    country = params.get("country")
    organization_type = params.get("organization_type")
    size_start_date = params.get("size_start_date")
    size_end_date = params.get("size_end_date")
    contribution_start_date = params.get("contribution_start_date")
    contribution_end_date = params.get("contribution_end_date")

    try:
        if USE_MOCK_DATA:
            organizations_df = load_mock_data()
        else:
            conn = get_db_connection()
            try:
                organizations_df = load_live_data(conn)
            finally:
                conn.close()
    except FileNotFoundError as exc:
        print(f"Mock data load failed: {exc}")
        return build_response(500, {"error": "Analytics data is currently unavailable."})
    except NotImplementedError as exc:
        print(f"Live-database path not implemented: {exc}")
        return build_response(500, {"error": "Analytics data is currently unavailable."})
    except Exception as exc:  # noqa: BLE001 - last-resort guard around data loading/DB connection
        print(f"Unexpected error loading analytics data: {exc}")
        return build_response(500, {"error": "Analytics data is currently unavailable."})

    try:
        response_body = build_size_contribution_response(
            organizations_df,
            country=country,
            organization_type=organization_type,
            size_start_date=size_start_date,
            size_end_date=size_end_date,
            contribution_start_date=contribution_start_date,
            contribution_end_date=contribution_end_date,
        )
    except DateRangeError as exc:
        print(f"Invalid date range in request: {exc}")
        return build_response(400, {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001 - last-resort guard around the analytics calculation
        print(f"Unexpected error computing analytics: {exc}")
        return build_response(500, {"error": "Failed to compute analytics."})

    return build_response(200, response_body)


if __name__ == "__main__":
    _SCENARIOS = [
        ("Empty payload", {}),
        ("Country filter (USA)", {"country": "USA"}),
        ("Organization-type filter (non_profit)", {"organization_type": "non_profit"}),
        (
            "Size Custom range only",
            {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"},
        ),
        (
            "Contribution Custom range only",
            {"contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"},
        ),
        (
            "Both Custom ranges together",
            {
                "size_start_date": "2026-01-01",
                "size_end_date": "2026-06-30",
                "contribution_start_date": "2025-01-01",
                "contribution_end_date": "2025-12-31",
            },
        ),
    ]

    for title, payload in _SCENARIOS:
        print(f"=== {title} ===")
        # Round-trips through a JSON string body to also exercise the API
        # Gateway proxy-integration parsing path (_extract_event_params).
        sample_event = {"body": json.dumps(payload)}
        sample_result = lambda_handler(sample_event, None)
        print(f"statusCode: {sample_result['statusCode']}")
        print(json.dumps(sample_result["body"], indent=2, default=str))
        print()
