"""Analytics lambda backing the "Rating & Type" tab of the Organization
Analytics dashboard.

Current scope: mock-data loading (organizations joined up to country), request
parsing and filter validation, and the two charts of the tab — the rating
distribution and the cumulative organization mix trend. ``lambda_handler`` and
the real-database path are added by later tasks.
"""

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

try:
    import psycopg2
except ImportError:  # psycopg2 is only needed on the real-DB path
    psycopg2 = None

try:
    import boto3
except ImportError:  # boto3 is only needed to read SSM creds for the real DB
    boto3 = None


SCHEMA_NAME = "virginia_dev_saayam_rdbms"

FIXED_BUCKETS = ["7D", "30D", "1Y", "All"]

ORG_TYPES = ["non_profit", "for_profit"]

USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "").strip().lower() == "true"

DEFAULT_MOCK_DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, "sql"
)

MOCK_DATA_DIR = os.environ.get("MOCK_DATA_DIR", DEFAULT_MOCK_DATA_DIR)

ORGANIZATION_COLUMNS = [
    "org_id",
    "org_rating",
    "org_type",
    "created_at",
    "country_code",
    "country_name",
]

BUCKET_GRANULARITY = {
    "7D": "day",
    "30D": "day",
    "1Y": "month",
    "All": "month",
    "Custom": "day",
}

ORGANIZATIONS_FILES = ["organizations.csv"]
STATES_FILES = ["states.csv", "state.csv"]
COUNTRIES_FILES = ["countries.csv", "country.csv"]

REQUIRED_ORGANIZATION_COLUMNS = [
    "org_id",
    "org_rating",
    "org_type",
    "state_id",
    "created_at",
]
REQUIRED_STATE_COLUMNS = ["state_id", "country_id"]
REQUIRED_COUNTRY_COLUMNS = ["country_id"]

DATE_FORMAT = "%Y-%m-%d"

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_BUCKET_LOOKBACK_DAYS = {"7D": 7, "30D": 30, "1Y": 365}

_PERIOD_FORMATS = {"day": "%Y-%m-%d", "month": "%Y-%m"}


class RequestValidationError(ValueError):
    """Raised when the client request is malformed.

    Callers map this to an HTTP 400 response; every other exception is an
    internal error.
    """


def build_response(status_code: int, body: Any) -> Dict[str, Any]:
    """Build an API Gateway proxy response with a JSON-serialized body."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, default=str)
    }


def empty_chart_payload() -> Dict[str, Any]:
    """Return a fresh, empty payload for one time bucket."""
    return {
        "rating_distribution": [],
        "organization_mix_trend": {"non_profit": [], "for_profit": []}
    }


def normalize_org_type(value: Any) -> Optional[str]:
    """Normalize a raw organization type to "non_profit" / "for_profit".

    Handles the mock-data spellings ("Non-Profit", "For-profit") as well as
    variants that differ only by case, whitespace, hyphens or underscores.
    Returns ``None`` for missing or unrecognized values.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    collapsed = re.sub(r"[\s_-]+", "", str(value).strip().lower())

    if collapsed == "nonprofit":
        return "non_profit"
    if collapsed == "forprofit":
        return "for_profit"
    return None


def parse_event(event: Any) -> Dict[str, Any]:
    """Extract the request payload from a Lambda event.

    Supports both API Gateway proxy events (``body`` and/or
    ``queryStringParameters``) and direct invocations where the event dict is
    itself the payload. Body values win over query-string values on conflict.
    Unknown keys are ignored.
    """
    if event is None:
        return {}

    if not isinstance(event, dict):
        raise RequestValidationError("Request must be a JSON object.")

    if "body" not in event and "queryStringParameters" not in event:
        return dict(event)

    body = event.get("body")

    if body is None or (isinstance(body, str) and not body.strip()):
        parsed_body: Dict[str, Any] = {}
    elif isinstance(body, dict):
        parsed_body = body
    elif isinstance(body, str):
        try:
            decoded = json.loads(body)
        except ValueError:
            raise RequestValidationError("Request body must be valid JSON.")
        if not isinstance(decoded, dict):
            raise RequestValidationError("Request body must be a JSON object.")
        parsed_body = decoded
    else:
        raise RequestValidationError("Request body must be a JSON object.")

    payload: Dict[str, Any] = {}

    query_params = event.get("queryStringParameters")
    if isinstance(query_params, dict):
        payload.update(query_params)

    payload.update(parsed_body)
    return payload


def _is_missing(value: Any) -> bool:
    """Return True when a payload value counts as "not supplied"."""
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


def _parse_date(value: Any, key: str) -> date:
    """Parse a strict ``YYYY-MM-DD`` string into a ``date``.

    The value must match ``YYYY-MM-DD`` exactly — zero-padded, with no time
    component — and must also be a real calendar date.
    """
    if isinstance(value, str):
        candidate = value.strip()
        if _DATE_PATTERN.match(candidate):
            try:
                return datetime.strptime(candidate, DATE_FORMAT).date()
            except ValueError:
                pass

    raise RequestValidationError(
        f"{key} must be a date in YYYY-MM-DD format (got '{value}')."
    )


def parse_date_pair(
    payload: Dict[str, Any], start_key: str, end_key: str
) -> Optional[Tuple[date, date]]:
    """Parse an inclusive start/end date pair from the payload.

    Returns ``None`` when neither key is supplied. Both keys must be given
    together, both must be strict ``YYYY-MM-DD`` strings, and the start must
    not be after the end (a single-day range is valid).
    """
    raw_start = payload.get(start_key)
    raw_end = payload.get(end_key)

    start_missing = _is_missing(raw_start)
    end_missing = _is_missing(raw_end)

    if start_missing and end_missing:
        return None

    if start_missing or end_missing:
        raise RequestValidationError(
            f"{start_key} and {end_key} must be provided together."
        )

    start = _parse_date(raw_start, start_key)
    end = _parse_date(raw_end, end_key)

    if start > end:
        raise RequestValidationError(f"{start_key} cannot be after {end_key}.")

    return start, end


def parse_filters(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize the country and custom-range filters.

    Returns ``{"country", "rating_range", "type_range"}``, where the ranges
    are ``None`` unless the client asked for a custom window.
    """
    raw_country = payload.get("country")

    if raw_country is None:
        country = "ALL"
    elif not isinstance(raw_country, str):
        raise RequestValidationError("country must be a string.")
    else:
        country = raw_country.strip() or "ALL"

    rating_range = parse_date_pair(payload, "rating_start_date", "rating_end_date")
    type_range = parse_date_pair(payload, "type_start_date", "type_end_date")

    return {
        "country": country,
        "rating_range": rating_range,
        "type_range": type_range
    }


def get_bucket_range(
    bucket: str, today: Optional[date] = None
) -> Optional[Tuple[date, date]]:
    """Return the inclusive date range covered by a fixed time bucket.

    ``today`` is injectable so callers and tests can pin "now". ``"All"``
    returns ``None``, meaning no date bounds at all.
    """
    if bucket == "All":
        return None

    if bucket not in _BUCKET_LOOKBACK_DAYS:
        raise ValueError(
            f"Invalid time bucket '{bucket}'. Must be one of: {', '.join(FIXED_BUCKETS)}."
        )

    reference = today or datetime.now().date()
    return reference - timedelta(days=_BUCKET_LOOKBACK_DAYS[bucket]), reference


def filter_by_date_range(
    df: pd.DataFrame, date_range: Optional[Tuple[date, date]]
) -> pd.DataFrame:
    """Keep rows whose ``created_at`` falls inside an inclusive date range.

    The upper bound is applied as ``< end + 1 day`` so any timestamp on the
    end date is included. A ``None`` range leaves the frame unbounded.
    """
    if date_range is None or df.empty:
        return df.copy()

    start, end = date_range
    created_at = pd.to_datetime(df["created_at"], errors="coerce")

    mask = (
        created_at.notna()
        & (created_at >= pd.Timestamp(start))
        & (created_at < pd.Timestamp(end) + pd.Timedelta(days=1))
    )
    return df[mask].copy()


def build_rating_distribution(df: pd.DataFrame) -> List[Dict[str, int]]:
    """Count organizations per star rating, ascending.

    ``df`` must already be country- and window-filtered. Rows without a
    rating are dropped; rows without a type still count. Only ratings that
    actually occur are emitted — missing ratings are not zero-filled.
    """
    if df.empty:
        return []

    ratings = pd.to_numeric(df["org_rating"], errors="coerce").dropna()
    if ratings.empty:
        return []

    counts = ratings.value_counts().sort_index()
    return [
        {"rating": int(rating), "count": int(count)}
        for rating, count in counts.items()
    ]


def _period_keys(created_at: pd.Series, granularity: str) -> pd.Series:
    """Format timestamps as period labels for the requested granularity."""
    if granularity not in _PERIOD_FORMATS:
        raise ValueError(
            f"Invalid granularity '{granularity}'. Must be 'day' or 'month'."
        )
    return created_at.dt.strftime(_PERIOD_FORMATS[granularity])


def build_organization_mix_trend(
    df: pd.DataFrame,
    date_range: Optional[Tuple[date, date]],
    granularity: str
) -> Dict[str, List[Dict[str, Any]]]:
    """Build the cumulative non-profit vs for-profit trend.

    ``df`` is country-filtered but NOT window-filtered: counts are all-time
    running totals, so organizations created before the window still count.
    Only periods that gained at least one organization of that type inside
    ``date_range`` are emitted, and the value for such a period is the
    all-time running total as of the end of that period. Rows without a type
    are excluded. Both series are always present and non-decreasing.
    """
    trend: Dict[str, List[Dict[str, Any]]] = {org_type: [] for org_type in ORG_TYPES}

    if df.empty:
        return trend

    typed = df[df["org_type"].notna()].copy()
    typed["created_at"] = pd.to_datetime(typed["created_at"], errors="coerce")
    typed = typed[typed["created_at"].notna()]

    if typed.empty:
        return trend

    for org_type in ORG_TYPES:
        subset = typed[typed["org_type"] == org_type]
        if subset.empty:
            continue

        running_total = (
            _period_keys(subset["created_at"], granularity)
            .value_counts()
            .sort_index()
            .cumsum()
        )

        in_window = filter_by_date_range(subset, date_range)
        if in_window.empty:
            continue

        active_periods = set(_period_keys(in_window["created_at"], granularity))

        trend[org_type] = [
            {"period": period, "count": int(total)}
            for period, total in running_total.items()
            if period in active_periods
        ]

    return trend


def _read_csv_any(directory: str, candidates: List[str], **kwargs: Any) -> pd.DataFrame:
    """Read the first CSV among ``candidates`` that exists in ``directory``.

    Raises ``FileNotFoundError`` naming every candidate that was tried when
    none of them exist.
    """
    return pd.read_csv(_resolve_csv_path(directory, candidates), **kwargs)


def _resolve_csv_path(directory: str, candidates: List[str]) -> str:
    """Return the path of the first candidate CSV that exists in ``directory``."""
    for name in candidates:
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            return path

    tried = ", ".join(candidates)
    raise FileNotFoundError(
        f"None of the expected mock CSV files were found in '{directory}'. Tried: {tried}"
    )


def _read_mock_csv(
    directory: str, candidates: List[str], empty_ok: bool = False
) -> Optional[pd.DataFrame]:
    """Read a mock CSV as strings, tolerating a zero-byte file.

    Returns ``None`` for a zero-byte file when ``empty_ok`` is set; otherwise
    a zero-byte file raises ``ValueError`` naming the file.
    """
    try:
        return _read_csv_any(directory, candidates, dtype=str)
    except pd.errors.EmptyDataError:
        if empty_ok:
            return None

        source = os.path.basename(_resolve_csv_path(directory, candidates))
        raise ValueError(f"Mock file '{source}' is empty.")


def _require_columns(
    df: pd.DataFrame, required: List[str], directory: str, candidates: List[str]
) -> None:
    """Raise a clear ``ValueError`` when a mock CSV is missing columns."""
    missing = [column for column in required if column not in df.columns]
    if not missing:
        return

    source = os.path.basename(_resolve_csv_path(directory, candidates))
    raise ValueError(
        f"Mock file '{source}' is missing required column(s): {', '.join(missing)}."
    )


def _empty_organizations_frame() -> pd.DataFrame:
    """Return an empty organizations DataFrame with the canonical columns."""
    empty = pd.DataFrame(columns=ORGANIZATION_COLUMNS)
    empty["org_rating"] = empty["org_rating"].astype("Int64")
    empty["created_at"] = pd.to_datetime(empty["created_at"], errors="coerce")
    return empty


def _clean_key(series: pd.Series) -> pd.Series:
    """Coerce a join key to a stripped string series so "1" and 1 match."""
    return series.astype(str).str.strip()


def load_mock_organizations(mock_dir: Optional[str] = None) -> pd.DataFrame:
    """Load organizations from the mock CSVs, joined out to their country.

    Organizations are LEFT joined to states and then to countries, so rows
    with an unknown state or country are kept with null country fields.
    Ratings are kept only when they are whole numbers in 1..5; rows whose
    ``created_at`` cannot be parsed are dropped. An empty organizations file
    yields an empty frame; raises ``ValueError`` when a source CSV is empty
    or is missing a column the join or output shape depends on.
    """
    directory = mock_dir or MOCK_DATA_DIR

    organizations = _read_mock_csv(directory, ORGANIZATIONS_FILES, empty_ok=True)
    states = _read_mock_csv(directory, STATES_FILES)
    countries = _read_mock_csv(directory, COUNTRIES_FILES)

    if organizations is None:
        return _empty_organizations_frame()

    _require_columns(
        organizations, REQUIRED_ORGANIZATION_COLUMNS, directory, ORGANIZATIONS_FILES
    )
    _require_columns(states, REQUIRED_STATE_COLUMNS, directory, STATES_FILES)
    _require_columns(countries, REQUIRED_COUNTRY_COLUMNS, directory, COUNTRIES_FILES)

    if "country_code" not in countries.columns and "country_name" not in countries.columns:
        source = os.path.basename(_resolve_csv_path(directory, COUNTRIES_FILES))
        raise ValueError(
            f"Mock file '{source}' must provide at least one of: country_code, country_name."
        )

    if organizations.empty:
        return _empty_organizations_frame()

    orgs = organizations.copy()
    orgs["state_id"] = _clean_key(orgs["state_id"])

    states = states[REQUIRED_STATE_COLUMNS].copy()
    states["state_id"] = _clean_key(states["state_id"])
    states["country_id"] = _clean_key(states["country_id"])

    countries = countries.copy()
    for column in ("country_code", "country_name"):
        if column not in countries.columns:
            countries[column] = pd.NA

    countries = countries[["country_id", "country_code", "country_name"]].copy()
    countries["country_id"] = _clean_key(countries["country_id"])

    merged = orgs.merge(states, on="state_id", how="left")
    merged = merged.merge(countries, on="country_id", how="left")

    result = pd.DataFrame({
        "org_id": merged["org_id"].astype(str).str.strip(),
        "org_rating": pd.to_numeric(merged["org_rating"], errors="coerce"),
        "org_type": merged["org_type"].map(normalize_org_type),
        "created_at": pd.to_datetime(merged["created_at"], errors="coerce"),
        "country_code": merged["country_code"],
        "country_name": merged["country_name"]
    })

    ratings = result["org_rating"]
    valid_rating = ratings.notna() & (ratings % 1 == 0) & ratings.between(1, 5)
    result["org_rating"] = ratings.where(valid_rating).astype("Int64")

    result = result[result["created_at"].notna()].reset_index(drop=True)

    if result.empty:
        return _empty_organizations_frame()

    return result[ORGANIZATION_COLUMNS]


def _normalize_country_token(value: Any) -> str:
    """Lowercase a country code/name and treat "_" and " " as equivalent."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"[\s_]+", " ", str(value).strip().lower())


def apply_country_filter(df: pd.DataFrame, country: Optional[str]) -> pd.DataFrame:
    """Filter organizations by country code or country name.

    ``None``, ``""`` and ``"ALL"`` (any case) leave the frame untouched.
    Matching is case-insensitive and treats underscores and spaces as
    equivalent, so "USA", "usa", "United States of America" and
    "UNITED_STATES_OF_AMERICA" all select the same rows. An unrecognized
    country yields an empty DataFrame rather than an error.
    """
    if country is None:
        return df

    wanted = _normalize_country_token(country)
    if wanted in ("", "all"):
        return df

    if df.empty:
        return df

    codes = df["country_code"].map(_normalize_country_token)
    names = df["country_name"].map(_normalize_country_token)

    return df[(codes == wanted) | (names == wanted)]
