"""KPI analytics for the Organization dashboard.

Returns four KPI cards: total_organizations, total_collaborators,
total_contributors and avg_org_rating.
With no dates the response has 7D/30D/1Y/All and no Custom key.
If start_date and end_date are sent (YYYY-MM-DD, both inclusive), only Custom
is returned.
The country and organization_type filters apply to all four KPIs in every case.

Data comes from organizations.csv, states.csv and countries.csv in the
mock_data folder next to this file. No environment variables are needed.

Layout (so the KPIs can grow):
  - time windows   -> fixed_window / custom_window / build_windows 
  - filters        -> filter_organizations
  - KPIs           -> one function each, listed in KPI_CALCULATORS
"""

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

import pandas as pd

logger = logging.getLogger(__name__)

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
ORGANIZATION_TYPES = ("non_profit", "for_profit")
TRUE_VALUES = ("true", "t", "1", "yes")
RATING_COLUMN = "org_rating"
REQUIRED_COLUMNS = ("is_collaborator", "is_contributor", "org_type", "state_id", RATING_COLUMN, "created_at")
REQUIRED_STATE_COLUMNS = ("state_id", "country_id")
REQUIRED_COUNTRY_COLUMNS = ("country_id", "country_name", "country_code")

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

# --------------------------------------------------------------------------
# Request parsing
# --------------------------------------------------------------------------
def parse_event_body(event):
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
    return " ".join(str(value).replace("_", " ").split()).upper()

def normalize_org_type(value):
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")

def parse_filters(body):
    country = body.get("country", "ALL")
    org_type = body.get("organization_type", "ALL")

    if country is None:
        country = "ALL"
    if org_type is None:
        org_type = "ALL"

    if not isinstance(country, str):
        raise BadRequestError("country must be text")
    if not isinstance(org_type, str):
        raise BadRequestError("organization_type must be text")

    if not country.strip():
        country = "ALL"
    if not org_type.strip():
        org_type = "ALL"

    country = normalize_country(country)
    org_type = normalize_org_type(org_type)
    if org_type not in ORGANIZATION_TYPES + ("all",):
        raise BadRequestError("organization_type must be non_profit, for_profit or ALL")
    return (
        None if country == "ALL" else country,
        None if org_type == "all" else org_type,
    )

def is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())

def parse_date(value, key):
    if not isinstance(value, str) or not DATE_PATTERN.match(value.strip()):
        raise BadRequestError(f"{key} must be a date in YYYY-MM-DD format")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise BadRequestError(f"{key} is not a real calendar date") from None

def parse_date_pair(body, start_key, end_key):
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

# --------------------------------------------------------------------------
# Time windows
# --------------------------------------------------------------------------
def utc_today():
    return datetime.now(timezone.utc).date()

def midnight(day):
    return datetime(day.year, day.month, day.day)

def fixed_window(bucket, today):
    if bucket == "All":
        return None, None
    if bucket == "1Y":
        year, month = today.year, today.month - 11
        if month < 1:
            year, month = year - 1, month + 12
        start = date(year, month, 1)
    else:
        start = today - timedelta(days=6 if bucket == "7D" else 29)
    return midnight(start), midnight(today + timedelta(days=1))

def custom_window(date_pair):
    start, end = date_pair
    return midnight(start), midnight(end + timedelta(days=1))

def build_windows(date_pair, today):
    if date_pair is None:
        return {bucket: fixed_window(bucket, today) for bucket in FIXED_BUCKETS}
    return {"Custom": custom_window(date_pair)}

def organizations_in_window(orgs, start, end):
    if start is None:
        return orgs
    return orgs[(orgs["created_at"] >= start) & (orgs["created_at"] < end)]

# --------------------------------------------------------------------------
# KPIs
# --------------------------------------------------------------------------
def calc_total_organizations(orgs):
    return int(len(orgs))

def calc_total_collaborators(orgs):
    return int(orgs["is_collaborator"].sum())

def calc_total_contributors(orgs):
    return int(orgs["is_contributor"].sum())

def calc_avg_org_rating(orgs):
    ratings = orgs["rating_value"].dropna()
    if ratings.empty:
        return None
    return round(float(ratings.mean()), 1)

KPI_CALCULATORS = {
    "total_organizations": calc_total_organizations,
    "total_collaborators": calc_total_collaborators,
    "total_contributors": calc_total_contributors,
    "avg_org_rating": calc_avg_org_rating,
}

def calculate_kpis(orgs):
    """All KPIs for one window's organizations."""
    return {name: calculate(orgs) for name, calculate in KPI_CALCULATORS.items()}

# --------------------------------------------------------------------------
# Data loading and filters
# --------------------------------------------------------------------------
def read_mock_csv(*filenames):
    for filename in filenames:
        path = os.path.join(MOCK_DATA_DIR, filename)
        if os.path.exists(path):
            return pd.read_csv(path, dtype=str)
    raise DataSourceError(f"{filenames[0]} not found in mock_data folder")

def validate_columns(data, required_columns, filename):
    missing = [col for col in required_columns if col not in data.columns]
    if missing:
        raise DataSourceError(
            f"{filename} is missing column(s): {', '.join(missing)}"
        )

def to_bool(series):
    return series.fillna("").str.strip().str.lower().isin(TRUE_VALUES)

def load_data():
    orgs = read_mock_csv("organizations.csv")
    states = read_mock_csv("states.csv")
    countries = read_mock_csv("countries.csv")

    validate_columns(orgs, REQUIRED_COLUMNS, "organizations.csv")
    validate_columns(states, REQUIRED_STATE_COLUMNS, "states.csv")
    validate_columns(countries, REQUIRED_COUNTRY_COLUMNS, "countries.csv")

    created = pd.to_datetime(orgs["created_at"], errors="coerce", format="ISO8601", utc=True)
    orgs["created_at"] = created.dt.tz_convert(None)
    orgs["is_collaborator"] = to_bool(orgs["is_collaborator"])
    orgs["is_contributor"] = to_bool(orgs["is_contributor"])
    orgs["rating_value"] = pd.to_numeric(orgs[RATING_COLUMN], errors="coerce")

    orgs = orgs.drop(
        columns=[
            col
            for col in ("country_id", "country_name", "country_code")
            if col in orgs.columns
        ]
    )
    state_lookup = states[["state_id", "country_id"]].drop_duplicates("state_id")
    country_lookup = countries[
        ["country_id", "country_name", "country_code"]
    ].drop_duplicates("country_id")

    orgs = orgs.merge(state_lookup, on="state_id", how="left")
    orgs = orgs.merge(country_lookup, on="country_id", how="left")

    return orgs[orgs["created_at"].notna()], countries

def filter_organizations(orgs, countries, country, org_type):
    if org_type:
        orgs = orgs[orgs["org_type"].fillna("").map(normalize_org_type) == org_type]
    if country:
        names = countries["country_name"].fillna("").map(normalize_country)
        codes = countries["country_code"].fillna("").map(normalize_country)
        match = (names == country) | (codes == country)

        if not match.any():
            raise BadRequestError("Unknown country")

        country_ids = countries.loc[match, "country_id"]
        orgs = orgs[orgs["country_id"].isin(country_ids)]

    return orgs

# --------------------------------------------------------------------------
# Lambda
# --------------------------------------------------------------------------
def build_body(orgs, windows):
    return {
        label: calculate_kpis(organizations_in_window(orgs, start, end))
        for label, (start, end) in windows.items()
    }

def build_response(status_code, body):
    return {"statusCode": status_code, "headers": HEADERS, "body": json.dumps(body)}

def lambda_handler(event, context):
    try:
        body = parse_event_body(event)
        country, org_type = parse_filters(body)
        date_pair = parse_date_pair(body, "start_date", "end_date")
    except BadRequestError as exc:
        return build_response(400, {"error": str(exc)})
    try:
        windows = build_windows(date_pair, utc_today())
        orgs, countries = load_data()
        orgs = filter_organizations(orgs, countries, country, org_type)
        return build_response(200, build_body(orgs, windows))
    except BadRequestError as exc:
        return build_response(400, {"error": str(exc)})
    except DataSourceError as exc:
        logger.error("Org KPI analytics: %s", exc)
        return build_response(500, {"error": str(exc)})
    except Exception:
        logger.exception("Org KPI analytics failed")
        return build_response(500, {"error": "Internal server error"})

handler = lambda_handler