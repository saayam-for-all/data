"""Organization Dashboard KPIs for the Organization dashboard (#708).

Returns the four KPI cards shown at the top of the dashboard:

* total_organizations   organizations created in the window
* total_collaborators   of those, how many are flagged as collaborators
* total_contributors    of those, how many are flagged as contributors
* avg_org_rating        average rating of those, rounded to 1 decimal
                        (organizations without a rating are ignored; null
                        when there is nothing to average)

With no dates the response has 7D/30D/1Y/All and no Custom key. If start_date
and end_date are sent (YYYY-MM-DD, both inclusive), only Custom is returned.
The country and organization_type filters apply to all four KPIs in every case.
A valid country with no organizations in the window returns 200 with zero
counts and a null average.

How the file is organized, so it can grow:

* Time windows are worked out in one place (fixed_window / custom_window) and
  any KPI reuses them through window_for().
* Each KPI is its own small function, listed in KPIS. Adding a KPI means
  writing one function and adding one line to KPIS.
* Filters are applied once (apply_filters), before any KPI is calculated.

Data comes from organizations.csv, states.csv and countries.csv in the
mock_data folder next to this file. No environment variables are needed.
"""

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

logger = logging.getLogger(__name__)

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
ORGANIZATION_TYPES = ("non_profit", "for_profit")
TRUE_VALUES = ("true", "t", "1", "yes")
REQUIRED_COLUMNS = (
    "org_id", "org_rating", "is_collaborator", "org_type", "state_id", "created_at",
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
# Request handling
# --------------------------------------------------------------------------- #
def parse_event_body(event):
    """Get the filters dict out of the Lambda event (JSON string or object)."""
    if not event:
        return {}
    body = event.get("body", event) if isinstance(event, dict) else event
    if body is None or body == "":
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
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def parse_filters(body):
    """Returns (country, org_type). None means ALL."""
    country = body.get("country") or "ALL"
    org_type = body.get("organization_type") or "ALL"
    if not isinstance(country, str) or not isinstance(org_type, str):
        raise BadRequestError("country and organization_type must be text")
    country = normalize_country(country)
    org_type = normalize_org_type(org_type)
    if org_type not in ORGANIZATION_TYPES + ("all",):
        raise BadRequestError("organization_type must be non_profit, for_profit or ALL")
    return (
        None if country == "ALL" else country,
        None if org_type == "all" else org_type,
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


def parse_date_pair(body, start_key, end_key):
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
# Time windows (one place, reused by every KPI)
# --------------------------------------------------------------------------- #
def utc_today():
    """created_at is stored in UTC, so use the UTC date."""
    return datetime.now(timezone.utc).date()


def midnight(day):
    """date -> datetime at 00:00."""
    return datetime(day.year, day.month, day.day)


def fixed_window(bucket, today):
    """(start, end) for a fixed bucket. End is exclusive, i.e. start of tomorrow."""
    if bucket == "All":
        return None, None
    if bucket == "1Y":
        # current month plus the 11 months before it
        year, month = today.year, today.month - 11
        if month < 1:
            year, month = year - 1, month + 12
        start = date(year, month, 1)
    else:
        # today counts as one of the days, so 7D = today + the 6 days before
        start = today - timedelta(days=6 if bucket == "7D" else 29)
    return midnight(start), midnight(today + timedelta(days=1))


def custom_window(date_pair):
    """End date is inclusive, so go up to midnight of the next day."""
    start, end = date_pair
    return midnight(start), midnight(end + timedelta(days=1))


def window_for(orgs, start, end):
    """The organizations created in [start, end). No start means all of them."""
    if start is None:
        return orgs
    return orgs[(orgs["created_at"] >= start) & (orgs["created_at"] < end)]


# --------------------------------------------------------------------------- #
# KPIs (one clearly named step each; add a new KPI by adding a line to KPIS)
# --------------------------------------------------------------------------- #
def total_organizations(window):
    """Number of organizations in the window."""
    return int(len(window))


def total_collaborators(window):
    """Number of organizations in the window flagged as collaborators."""
    return int(window["is_collaborator"].sum())


def total_contributors(window):
    """Number of organizations in the window flagged as contributors."""
    return int(window["is_contributor"].sum())


def avg_org_rating(window):
    """Average rating to 1 decimal (half up); None if no organization is rated."""
    ratings = pd.to_numeric(window["org_rating"], errors="coerce").dropna()
    if ratings.empty:
        return None
    mean = Decimal(repr(float(ratings.mean())))
    return float(mean.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


KPIS = (
    ("total_organizations", total_organizations),
    ("total_collaborators", total_collaborators),
    ("total_contributors", total_contributors),
    ("avg_org_rating", avg_org_rating),
)


def calculate_kpis(orgs, start, end):
    """All KPIs for one window, calculated from the same organizations."""
    window = window_for(orgs, start, end)
    return {name: calculate(window) for name, calculate in KPIS}


def build_body(orgs, date_pair, today):
    """{} -> 7D/30D/1Y/All; a date pair -> only Custom."""
    if date_pair is None:
        return {
            bucket: calculate_kpis(orgs, *fixed_window(bucket, today))
            for bucket in FIXED_BUCKETS
        }
    return {"Custom": calculate_kpis(orgs, *custom_window(date_pair))}


# --------------------------------------------------------------------------- #
# Data and filters (filters are applied once, before any KPI)
# --------------------------------------------------------------------------- #
def read_mock_csv(*filenames):
    """Read the first of these CSVs found in the mock_data folder, as plain text."""
    for filename in filenames:
        path = os.path.join(MOCK_DATA_DIR, filename)
        if os.path.exists(path):
            return pd.read_csv(path, dtype=str)
    raise DataSourceError(f"{filenames[0]} not found in mock_data folder")


def to_bool(series):
    """Anything other than true/t/1/yes counts as False."""
    return series.fillna("").str.strip().str.lower().isin(TRUE_VALUES)


def parse_created_at(series):
    """Read created_at, with or without a timezone offset, as naive UTC.

    A value like 2025-08-17T12:41:00+00:00 gives the same result as
    2025-08-17 12:41:00. Values that can't be read become NaT and are ignored.
    """
    parsed = pd.to_datetime(series, errors="coerce", utc=True, format="mixed")
    return parsed.dt.tz_localize(None)


def load_organizations():
    """Read and clean organizations.csv."""
    orgs = read_mock_csv("organizations.csv")
    missing = [col for col in REQUIRED_COLUMNS if col not in orgs.columns]
    if missing:
        raise DataSourceError(f"organizations.csv is missing column(s): {', '.join(missing)}")

    orgs["created_at"] = parse_created_at(orgs["created_at"])
    orgs["is_collaborator"] = to_bool(orgs["is_collaborator"])
    # is_contributor isn't in every dataset yet, count it as False if missing
    if "is_contributor" in orgs.columns:
        orgs["is_contributor"] = to_bool(orgs["is_contributor"])
    else:
        orgs["is_contributor"] = False
    return orgs[orgs["created_at"].notna()]


def apply_filters(orgs, country, org_type):
    """Apply country and organization_type once. None means no filter."""
    if org_type:
        orgs = orgs[orgs["org_type"].fillna("").map(normalize_org_type) == org_type]
    if country:
        # org -> state -> country
        # the repo's sample data uses state.csv / country.csv in some branches
        states = read_mock_csv("states.csv", "state.csv")
        countries = read_mock_csv("countries.csv", "country.csv")
        match = countries["country_code"].fillna("").map(normalize_country) == country
        if "country_name" in countries.columns:
            match |= countries["country_name"].fillna("").map(normalize_country) == country
        country_ids = countries.loc[match, "country_id"]
        state_ids = states.loc[states["country_id"].isin(country_ids), "state_id"]
        orgs = orgs[orgs["state_id"].isin(state_ids)]
    return orgs


def build_response(status_code, body):
    """Same response format as the other analytics lambdas."""
    return {"statusCode": status_code, "headers": HEADERS, "body": json.dumps(body)}


def lambda_handler(event, context):
    """Lambda entry point."""
    try:
        body = parse_event_body(event)
        country, org_type = parse_filters(body)
        date_pair = parse_date_pair(body, "start_date", "end_date")
    except BadRequestError as exc:
        return build_response(400, {"error": str(exc)})

    try:
        orgs = apply_filters(load_organizations(), country, org_type)
        return build_response(200, build_body(orgs, date_pair, utc_today()))
    except DataSourceError as exc:
        logger.error("Organization KPI analytics: %s", exc)
        return build_response(500, {"error": str(exc)})
    except Exception:
        logger.exception("Organization KPI analytics failed")
        return build_response(500, {"error": "Internal server error"})
