"""Organization Dashboard KPIs API (#708).

Returns the four KPI cards shown at the top of the Organization dashboard:
total_organizations, total_collaborators, total_contributors and avg_org_rating.

With no dates the response has 7D/30D/1Y/All and no Custom key.
If start_date and end_date are sent (YYYY-MM-DD, both inclusive), only Custom
is returned. The country and organization_type filters apply to all four KPIs
in every case.

Data comes from organizations.csv, states.csv and countries.csv in the
mock_data folder next to this file. No environment variables are needed.
"""

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
ORGANIZATION_TYPES = ("non_profit", "for_profit")
ORG_TYPE_ALIASES = {"nonprofit": "non_profit", "forprofit": "for_profit"}
TRUE_VALUES = ("true", "t", "1", "yes")
MIN_RATING, MAX_RATING = 1, 5
DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
TIMESTAMP_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}([T ].*)?$")
MOCK_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data")

ORGANIZATION_COLUMNS = (
    "state_id",
    "org_type",
    "org_rating",
    "is_collaborator",
    "is_contributor",
    "created_at",
)
STATE_COLUMNS = ("state_id", "country_id")
COUNTRY_COLUMNS = ("country_id", "country_name", "country_code")

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}

# pandas can only hold dates between 1677 and 2262, so far-away dates are clamped.
_MIN_TIMESTAMP = pd.Timestamp.min.tz_localize("UTC")
_MAX_TIMESTAMP = pd.Timestamp.max.tz_localize("UTC")

Window = Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]


class BadRequestError(ValueError):
    """Bad input in the request (400)."""


class DataSourceError(RuntimeError):
    """Missing or unreadable file, or missing column, on our side (500)."""


# --------------------------------------------------------------------------- #
# 1. Request parsing and validation
# --------------------------------------------------------------------------- #
def parse_event_body(event) -> dict:
    """Get the request dict out of the Lambda event.

    Accepts an API Gateway event (body as JSON string or object), or the request
    dict itself. An empty event or body behaves like {}.
    """
    if not event:
        return {}
    body = event.get("body", event) if isinstance(event, dict) else event
    if body is None or (isinstance(body, str) and not body.strip()):
        return {}
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise BadRequestError("Request body is not valid JSON") from None
    if not isinstance(body, dict):
        raise BadRequestError("Request body must be a JSON object")
    return body


def normalize_country(value: str) -> str:
    """Uppercase and treat '_' as a space, e.g. 'united_states' -> 'UNITED STATES'."""
    return " ".join(value.replace("_", " ").split()).upper()


def normalize_org_type(value: str) -> str:
    """Lowercase and treat '-' and spaces like '_', so 'Non-Profit' == 'non_profit'."""
    cleaned = re.sub(r"[\s\-_]+", "_", value.strip().lower())
    return ORG_TYPE_ALIASES.get(cleaned, cleaned)


def parse_filters(body: dict) -> Tuple[Optional[str], Optional[str]]:
    """Returns (country, org_type), normalized. None means ALL."""
    country, org_type = body.get("country"), body.get("organization_type")
    if country is not None and not isinstance(country, str):
        raise BadRequestError("country must be a string")
    if org_type is not None and not isinstance(org_type, str):
        raise BadRequestError("organization_type must be a string")

    country = normalize_country(country) if country is not None else ""
    org_type = normalize_org_type(org_type) if org_type is not None else ""
    if org_type not in ORGANIZATION_TYPES + ("", "all"):
        raise BadRequestError("organization_type must be non_profit, for_profit or ALL")
    return (
        None if country in ("", "ALL") else country,
        None if org_type in ("", "all") else org_type,
    )


def is_blank(value) -> bool:
    """Blank date: null or empty/whitespace string counts as not supplied."""
    return value is None or (isinstance(value, str) and not value.strip())


def parse_date(value, key: str) -> date:
    """Parse a YYYY-MM-DD string into a date."""
    if not isinstance(value, str) or not DATE_PATTERN.match(value.strip()):
        raise BadRequestError(f"{key} must be a date in YYYY-MM-DD format")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise BadRequestError(f"{key} is not a real calendar date") from None


def parse_date_pair(body: dict, start_key: str, end_key: str) -> Optional[Tuple[date, date]]:
    """Returns (start, end), or None if the pair wasn't sent."""
    start, end = body.get(start_key), body.get(end_key)
    start_blank, end_blank = is_blank(start), is_blank(end)
    if start_blank and end_blank:
        return None
    if start_blank or end_blank:
        raise BadRequestError(f"{start_key} and {end_key} must be sent together")
    start, end = parse_date(start, start_key), parse_date(end, end_key)
    if start > end:
        raise BadRequestError(f"{start_key} must be on or before {end_key}")
    return start, end


def parse_request(event) -> Tuple[Optional[str], Optional[str], Optional[Tuple[date, date]]]:
    """Validate the whole request. Returns (country, org_type, date_pair)."""
    body = parse_event_body(event)
    country, org_type = parse_filters(body)
    date_pair = parse_date_pair(body, "start_date", "end_date")
    return country, org_type, date_pair


# --------------------------------------------------------------------------- #
# 2. CSV loading and schema checks
# --------------------------------------------------------------------------- #
def read_mock_csv(filename: str, required_columns) -> pd.DataFrame:
    """Read one CSV from the mock_data folder as text and check its columns."""
    path = os.path.join(MOCK_DATA_DIR, filename)
    try:
        # keep_default_na=False so real values like the state code "NA" stay text
        df = pd.read_csv(
            path, dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8-sig"
        )
    except FileNotFoundError:
        raise DataSourceError(f"{filename} not found in mock_data folder") from None
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError, OSError):
        raise DataSourceError(f"{filename} could not be read") from None

    df.columns = [str(column).strip() for column in df.columns]
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise DataSourceError(f"{filename} is missing column(s): {', '.join(missing)}")
    return df


def load_tables() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load organizations, states and countries."""
    return (
        read_mock_csv("organizations.csv", ORGANIZATION_COLUMNS),
        read_mock_csv("states.csv", STATE_COLUMNS),
        read_mock_csv("countries.csv", COUNTRY_COLUMNS),
    )


# --------------------------------------------------------------------------- #
# 3. Data normalization
# --------------------------------------------------------------------------- #
def parse_utc_timestamp(value) -> pd.Timestamp:
    """Parse one created_at value to a UTC timestamp, or NaT if it can't be read.

    Values without a timezone are taken as UTC; values with an offset (or Z)
    are converted to UTC. Each value is parsed on its own, so mixed formats in
    one column are fine on every pandas version.
    """
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.match(value.strip()):
        return pd.NaT
    try:
        timestamp = pd.Timestamp(value.strip())
    except (ValueError, OverflowError):
        return pd.NaT
    if pd.isna(timestamp):
        return pd.NaT
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def to_bool(series: pd.Series) -> pd.Series:
    """Anything other than true/t/1/yes counts as False (so "false" is False)."""
    return series.fillna("").str.strip().str.lower().isin(TRUE_VALUES)


def clean_ids(series: pd.Series) -> pd.Series:
    """IDs as trimmed text, with missing values as ''."""
    return series.fillna("").str.strip()


def prepare_organizations(orgs: pd.DataFrame) -> pd.DataFrame:
    """Normalize the organizations table once, up front.

    Rows whose created_at can't be read are dropped, so they count in no KPI.
    Ratings that are missing, not numbers, not finite or outside 1-5 become NaN
    (they are never turned into 0).
    """
    prepared = pd.DataFrame(index=orgs.index)
    prepared["state_id"] = clean_ids(orgs["state_id"])
    prepared["org_type"] = orgs["org_type"].fillna("").map(normalize_org_type)
    prepared["is_collaborator"] = to_bool(orgs["is_collaborator"])
    prepared["is_contributor"] = to_bool(orgs["is_contributor"])

    ratings = pd.to_numeric(orgs["org_rating"], errors="coerce")
    prepared["org_rating"] = ratings.where(ratings.between(MIN_RATING, MAX_RATING))

    created_at = orgs["created_at"].map(parse_utc_timestamp)
    prepared["created_at"] = pd.to_datetime(created_at, utc=True, errors="coerce")
    return prepared[prepared["created_at"].notna()]


# --------------------------------------------------------------------------- #
# 4. Country resolution
# --------------------------------------------------------------------------- #
def resolve_country(countries: pd.DataFrame, country: Optional[str]) -> Optional[pd.Series]:
    """Match a country name or code (already normalized) against countries.csv.

    Returns the matching country_ids, or None when there is no country filter.
    Raises BadRequestError if the country doesn't exist in countries.csv.
    """
    if country is None:
        return None
    codes = countries["country_code"].fillna("").map(normalize_country)
    names = countries["country_name"].fillna("").map(normalize_country)
    country_ids = clean_ids(countries.loc[(codes == country) | (names == country), "country_id"])
    country_ids = country_ids[country_ids != ""]
    if country_ids.empty:
        raise BadRequestError("Unknown country")
    return country_ids


# --------------------------------------------------------------------------- #
# 5. Organization type and country filtering (applied once per request)
# --------------------------------------------------------------------------- #
def apply_filters(
    orgs: pd.DataFrame,
    states: pd.DataFrame,
    country_ids: Optional[pd.Series],
    org_type: Optional[str],
) -> pd.DataFrame:
    """Keep only organizations matching both filters (AND).

    The country is checked with isin() on the states of that country rather than
    a join, so an organization can never be counted twice.
    """
    if org_type is not None:
        orgs = orgs[orgs["org_type"] == org_type]
    if country_ids is not None:
        # org -> state -> country
        in_country = clean_ids(states["country_id"]).isin(country_ids)
        state_ids = clean_ids(states.loc[in_country, "state_id"])
        orgs = orgs[orgs["state_id"].isin(state_ids[state_ids != ""])]
    return orgs


# --------------------------------------------------------------------------- #
# 6. Time windows (all the window rules live here)
# --------------------------------------------------------------------------- #
def utc_today() -> date:
    """created_at is in UTC, so use the UTC date. Read once per request."""
    return datetime.now(timezone.utc).date()


def utc_midnight(day: date) -> pd.Timestamp:
    """00:00 UTC of a date, clamped to the range pandas supports."""
    try:
        return pd.Timestamp(year=day.year, month=day.month, day=day.day, tz="UTC")
    except (ValueError, OverflowError):
        return _MIN_TIMESTAMP if day.year < 1970 else _MAX_TIMESTAMP


def fixed_window(bucket: str, today: date) -> Window:
    """(start, end) for a fixed bucket. Start is inclusive, end is exclusive.

    7D  = today and the 6 days before it.
    30D = today and the 29 days before it.
    1Y  = the current month and the 11 months before it, from the 1st.
    All = every organization with a readable created_at (no limits).
    """
    if bucket == "All":
        return None, None
    if bucket == "1Y":
        year, month = today.year, today.month - 11
        if month < 1:
            year, month = year - 1, month + 12
        start = date(year, month, 1)
    else:
        start = today - timedelta(days=6 if bucket == "7D" else 29)
    return utc_midnight(start), utc_midnight(today + timedelta(days=1))


def custom_window(date_pair: Tuple[date, date]) -> Window:
    """Both dates are inclusive, so the end is midnight of the following day."""
    start, end = date_pair
    try:
        end_exclusive = utc_midnight(end + timedelta(days=1))
    except OverflowError:  # end is 9999-12-31
        end_exclusive = _MAX_TIMESTAMP
    return utc_midnight(start), end_exclusive


def resolve_windows(date_pair: Optional[Tuple[date, date]], today: date) -> Dict[str, Window]:
    """The windows to report: 7D/30D/1Y/All, or only Custom if dates were sent."""
    if date_pair is None:
        return {bucket: fixed_window(bucket, today) for bucket in FIXED_BUCKETS}
    return {"Custom": custom_window(date_pair)}


# --------------------------------------------------------------------------- #
# 7. Window-specific data selection
# --------------------------------------------------------------------------- #
def select_window(orgs: pd.DataFrame, window: Window) -> pd.DataFrame:
    """Organizations created in the window. A None bound means no limit."""
    start, end = window
    if start is not None:
        orgs = orgs[orgs["created_at"] >= start]
    if end is not None:
        orgs = orgs[orgs["created_at"] < end]
    return orgs


# --------------------------------------------------------------------------- #
# 8. KPI calculations (one function per KPI, each gets the same window data)
# --------------------------------------------------------------------------- #
def calculate_total_organizations(window_orgs: pd.DataFrame) -> int:
    """Number of organizations created in the window."""
    return int(len(window_orgs))


def calculate_total_collaborators(window_orgs: pd.DataFrame) -> int:
    """Number of those organizations flagged as collaborators."""
    return int(window_orgs["is_collaborator"].sum())


def calculate_total_contributors(window_orgs: pd.DataFrame) -> int:
    """Number of those organizations flagged as contributors (independent of collaborator)."""
    return int(window_orgs["is_contributor"].sum())


def calculate_avg_org_rating(window_orgs: pd.DataFrame) -> Optional[float]:
    """Mean of the valid ratings, rounded to 1 decimal, or None if there are none."""
    ratings = window_orgs["org_rating"].dropna()
    if ratings.empty:
        return None
    return round(float(ratings.mean()), 1)


# To add a KPI, write a calculate_* function and add it here.
KPI_CALCULATORS: Dict[str, Callable[[pd.DataFrame], object]] = {
    "total_organizations": calculate_total_organizations,
    "total_collaborators": calculate_total_collaborators,
    "total_contributors": calculate_total_contributors,
    "avg_org_rating": calculate_avg_org_rating,
}


# --------------------------------------------------------------------------- #
# 9. Response construction
# --------------------------------------------------------------------------- #
def calculate_kpis(window_orgs: pd.DataFrame) -> dict:
    """All KPIs for one window."""
    return {name: calculate(window_orgs) for name, calculate in KPI_CALCULATORS.items()}


def build_body(orgs: pd.DataFrame, windows: Dict[str, Window]) -> dict:
    """KPIs per window, calculated from the already filtered organizations."""
    return {name: calculate_kpis(select_window(orgs, window)) for name, window in windows.items()}


def build_response(status_code: int, body: dict) -> dict:
    """Same response format as the other analytics lambdas."""
    return {
        "statusCode": status_code,
        "headers": HEADERS,
        "body": json.dumps(body, allow_nan=False),
    }


# --------------------------------------------------------------------------- #
# 10. Lambda handler
# --------------------------------------------------------------------------- #
def lambda_handler(event, context):
    """Lambda entry point."""
    try:
        country, org_type, date_pair = parse_request(event)
    except BadRequestError as exc:
        return build_response(400, {"error": str(exc)})

    try:
        today = utc_today()  # one reference date for every window
        organizations, states, countries = load_tables()
        country_ids = resolve_country(countries, country)
        orgs = apply_filters(prepare_organizations(organizations), states, country_ids, org_type)
        return build_response(200, build_body(orgs, resolve_windows(date_pair, today)))
    except BadRequestError as exc:
        return build_response(400, {"error": str(exc)})
    except DataSourceError as exc:
        logger.error("Org KPI analytics: %s", exc)
        return build_response(500, {"error": str(exc)})
    except Exception:
        logger.exception("Org KPI analytics failed")
        return build_response(500, {"error": "Internal server error"})
