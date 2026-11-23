"""Organization Dashboard KPI cards (#708).

Returns total_organizations, total_collaborators, total_contributors and
avg_org_rating for each time window.
With no dates the response has 7D/30D/1Y/All and no Custom key.
If start_date and end_date are sent (YYYY-MM-DD, both inclusive), only Custom
is returned.
The country and organization_type filters apply to every window.

Data comes from organizations.csv, states.csv and countries.csv in the
mock_data folder next to this file. No environment variables are needed.
"""

import json
import logging
import math
import os
import re
from datetime import date, datetime, timedelta, timezone

import pandas as pd

logger = logging.getLogger(__name__)

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
CUSTOM_BUCKET = "Custom"
ORGANIZATION_TYPES = ("non_profit", "for_profit")
ORG_TYPE_ALIASES = {"nonprofit": "non_profit", "forprofit": "for_profit"}
TRUE_VALUES = ("true", "t", "1", "yes")
ORG_COLUMNS = (
    "state_id", "org_type", "org_rating", "is_collaborator", "is_contributor", "created_at",
)
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MOCK_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data")

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


class BadRequestError(ValueError):
    """Bad input in the request (400)."""


class DataSourceError(RuntimeError):
    """Missing file or column on our side (500)."""


# --------------------------------------------------------------------------- #
# Request parsing and validation
# --------------------------------------------------------------------------- #
def parse_event_body(event):
    """Get the filters dict out of the Lambda event."""
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


def normalize_country(value):
    """Uppercase and treat '_' as a space, e.g. 'united_states' -> 'UNITED STATES'."""
    return " ".join(str(value).replace("_", " ").split()).upper()


def normalize_org_type(value):
    """Lowercase and treat '-' and spaces like '_', so 'Non-Profit' == 'non_profit'."""
    normalized = re.sub(r"[\s\-_]+", "_", str(value).strip().lower())
    return ORG_TYPE_ALIASES.get(normalized, normalized)


def parse_filters(body):
    """Returns (country, org_type), normalized. None means ALL."""
    country = body.get("country")
    org_type = body.get("organization_type")
    country = "ALL" if country is None else country
    org_type = "ALL" if org_type is None else org_type
    if not isinstance(country, str) or not isinstance(org_type, str):
        raise BadRequestError("country and organization_type must be text")
    country = normalize_country(country)
    org_type = normalize_org_type(org_type)
    if org_type not in ORGANIZATION_TYPES + ("all", ""):
        raise BadRequestError("organization_type must be non_profit, for_profit or ALL")
    return (
        None if country in ("", "ALL") else country,
        None if org_type in ("", "all") else org_type,
    )


def is_blank(value):
    """Blank date: null or empty/whitespace string counts as not supplied."""
    return value is None or (isinstance(value, str) and not value.strip())


def parse_date(value, key):
    """Parse a YYYY-MM-DD string into a date."""
    if not isinstance(value, str) or not DATE_PATTERN.match(value.strip()):
        raise BadRequestError(f"{key} must be a date in YYYY-MM-DD format")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise BadRequestError(f"{key} is not a real calendar date") from None


def parse_date_pair(body, start_key="start_date", end_key="end_date"):
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


# --------------------------------------------------------------------------- #
# Time windows
# --------------------------------------------------------------------------- #
def utc_today():
    """created_at is stored in UTC, so use the UTC date."""
    return datetime.now(timezone.utc).date()


def midnight(day):
    """date -> datetime at 00:00."""
    return datetime(day.year, day.month, day.day)


def fixed_window(bucket, today):
    """(start, end) for a fixed bucket; end is exclusive (start of tomorrow).

    7D/30D/1Y stop at the end of today, so future-dated rows are left out.
    All has no bounds.
    """
    if bucket == "All":
        return None, None
    if bucket == "1Y":
        # current month plus the 11 months before it
        year, month = today.year, today.month - 11
        if month < 1:
            year, month = year - 1, month + 12
        start = date(year, month, 1)
    elif bucket in ("7D", "30D"):
        # today counts as one of the days, so 7D = today + the 6 days before
        start = today - timedelta(days=6 if bucket == "7D" else 29)
    else:
        raise ValueError(f"Unknown bucket: {bucket}")
    return midnight(start), midnight(today + timedelta(days=1))


def custom_window(date_pair):
    """End date is inclusive, so go up to midnight of the next day."""
    start, end = date_pair
    return midnight(start), midnight(end + timedelta(days=1))


def resolve_windows(date_pair, today):
    """{bucket: (start, end)} for this request: the fixed buckets, or only Custom."""
    if date_pair is None:
        return {bucket: fixed_window(bucket, today) for bucket in FIXED_BUCKETS}
    return {CUSTOM_BUCKET: custom_window(date_pair)}


def select_window(orgs, start, end):
    """Rows created in [start, end). None bounds mean no limit."""
    if start is None and end is None:
        return orgs
    return orgs[(orgs["created_at"] >= start) & (orgs["created_at"] < end)]


# --------------------------------------------------------------------------- #
# Data loading and cleaning
# --------------------------------------------------------------------------- #
def read_mock_csv(filename, required):
    """Read a CSV from the mock_data folder as plain text and check its columns."""
    path = os.path.join(MOCK_DATA_DIR, filename)
    if not os.path.exists(path):
        raise DataSourceError(f"{filename} not found in mock_data folder")
    try:
        df = pd.read_csv(path, dtype=str)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame()
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise DataSourceError(f"{filename} is missing column(s): {', '.join(missing)}")
    return df


def parse_created_at(series):
    """Timestamps with or without a UTC offset -> naive UTC. Unreadable values -> NaT."""
    parsed = pd.to_datetime(series, errors="coerce", utc=True, format="ISO8601")
    return parsed.dt.tz_localize(None)


def to_bool(series):
    """Only true/t/1/yes (any case) count as True; 'False', blanks etc. are False."""
    return series.fillna("").astype(str).str.strip().str.lower().isin(TRUE_VALUES)


def to_rating(series):
    """Numeric ratings; missing, non-numeric and infinite values become NaN."""
    ratings = pd.to_numeric(series, errors="coerce")
    return ratings.where(~ratings.isin([math.inf, -math.inf]))


def load_organizations():
    """organizations.csv with clean types; rows without a readable created_at dropped."""
    orgs = read_mock_csv("organizations.csv", ORG_COLUMNS)
    orgs["created_at"] = parse_created_at(orgs["created_at"])
    orgs = orgs[orgs["created_at"].notna()].copy()
    orgs["is_collaborator"] = to_bool(orgs["is_collaborator"])
    orgs["is_contributor"] = to_bool(orgs["is_contributor"])
    orgs["org_rating"] = to_rating(orgs["org_rating"])
    orgs["org_type"] = orgs["org_type"].fillna("").map(normalize_org_type)
    return orgs


def load_country_state_ids(country):
    """state_ids for a country name or code. Raises BadRequestError if unknown."""
    countries = read_mock_csv("countries.csv", ("country_id", "country_code", "country_name"))
    match = (
        (countries["country_code"].fillna("").map(normalize_country) == country)
        | (countries["country_name"].fillna("").map(normalize_country) == country)
    )
    if not match.any():
        raise BadRequestError("Unknown country")
    states = read_mock_csv("states.csv", ("state_id", "country_id"))
    return states.loc[states["country_id"].isin(countries.loc[match, "country_id"]), "state_id"]


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
def apply_filters(orgs, state_ids, org_type):
    """Apply the country (as state_ids) and organization_type filters once."""
    if state_ids is not None:
        orgs = orgs[orgs["state_id"].isin(state_ids)]
    if org_type is not None:
        orgs = orgs[orgs["org_type"] == org_type]
    return orgs


# --------------------------------------------------------------------------- #
# KPI calculations
# --------------------------------------------------------------------------- #
def total_organizations(orgs):
    """Number of organizations in the window."""
    return int(len(orgs))


def total_collaborators(orgs):
    """Organizations flagged as collaborators."""
    return int(orgs["is_collaborator"].sum())


def total_contributors(orgs):
    """Organizations flagged as contributors (independent of the collaborator flag)."""
    return int(orgs["is_contributor"].sum())


def avg_org_rating(orgs):
    """Mean of the valid ratings, rounded to 1 decimal; None if nothing is rated."""
    ratings = orgs["org_rating"].dropna()
    if ratings.empty:
        return None
    return round(float(ratings.mean()), 1)


# Response key -> calculation, in output order. Add new KPIs here.
KPI_CALCULATIONS = (
    ("total_organizations", total_organizations),
    ("total_collaborators", total_collaborators),
    ("total_contributors", total_contributors),
    ("avg_org_rating", avg_org_rating),
)


def compute_kpis(orgs):
    """Every KPI for one window's organizations."""
    return {name: calculate(orgs) for name, calculate in KPI_CALCULATIONS}


# --------------------------------------------------------------------------- #
# Response and handler
# --------------------------------------------------------------------------- #
def build_body(orgs, windows):
    """{bucket: KPIs} for already-filtered organizations."""
    return {bucket: compute_kpis(select_window(orgs, start, end))
            for bucket, (start, end) in windows.items()}


def build_response(status_code, body):
    """Same response format as the other analytics lambdas."""
    return {"statusCode": status_code, "headers": HEADERS, "body": json.dumps(body)}


def lambda_handler(event, context):
    """Lambda entry point."""
    try:
        body = parse_event_body(event)
        country, org_type = parse_filters(body)
        date_pair = parse_date_pair(body)
        state_ids = load_country_state_ids(country) if country else None
        orgs = apply_filters(load_organizations(), state_ids, org_type)
        windows = resolve_windows(date_pair, utc_today())
        return build_response(200, build_body(orgs, windows))
    except BadRequestError as exc:
        return build_response(400, {"error": str(exc)})
    except DataSourceError as exc:
        logger.error("Organization KPI analytics: %s", exc)
        return build_response(500, {"error": str(exc)})
    except Exception:
        logger.exception("Organization KPI analytics failed")
        return build_response(500, {"error": "Internal server error"})
