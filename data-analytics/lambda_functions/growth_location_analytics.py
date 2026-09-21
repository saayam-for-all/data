"""Growth & Location analytics for the Organization Analytics dashboard.

One call returns every time bucket (7D / 30D / 1Y / All / Custom) for both charts,
so the frontend can switch either chart's range without another request:

  * growth_trend               - total_organizations (all-time running total) and
                                 collaborators (per period, scoped to the window)
  * organizations_by_location  - top 4 countries by organization count

Optional request params (either pair, both, or neither):
  start_date / end_date                    -> Custom growth_trend
  location_start_date / location_end_date  -> Custom organizations_by_location

Data is read from organizations.csv, states.csv and countries.csv in MOCK_DATA_DIR
(defaults to a mock_data/ folder next to this file). Those CSVs are local-only.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data")

TOP_LOCATIONS = 4
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MIN_YEAR, MAX_YEAR = 1900, 2200  # keeps dates inside the range pandas can represent

# bucket -> (window start relative to today, trend granularity); "All" is unbounded
FIXED_BUCKETS = {
    "7D": (pd.DateOffset(days=7), "D"),
    "30D": (pd.DateOffset(days=30), "D"),
    "1Y": (pd.DateOffset(years=1), "M"),
    "All": (None, "M"),
}

REQUIRED_COLUMNS = {
    "organizations.csv": ["org_id", "state_id", "city_name", "is_collaborator", "created_at"],
    "states.csv": ["state_id", "state_name", "country_id"],
    "countries.csv": ["country_id", "country_code"],
}

RESPONSE_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


class RequestError(ValueError):
    """The request itself is invalid (returned as a 400)."""


# --- request parsing -------------------------------------------------------------
def parse_event_body(event):
    """Params come from event["body"] (JSON string or dict) or from the event itself."""
    if not event:
        return {}
    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, str):
        if not body.strip():
            return {}
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise RequestError("Request body is not valid JSON")
    if not isinstance(body, dict):
        raise RequestError("Request body must be a JSON object")
    return body


def parse_date(name, value):
    if not isinstance(value, str) or not DATE_PATTERN.match(value):
        raise RequestError(f"Invalid {name}: {value!r}. Expected format YYYY-MM-DD")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise RequestError(f"Invalid {name}: {value!r}. Not a real calendar date")
    if not MIN_YEAR <= parsed.year <= MAX_YEAR:
        raise RequestError(f"Invalid {name}: {value!r}. Year must be between {MIN_YEAR} and {MAX_YEAR}")
    return pd.Timestamp(parsed)


def parse_range(params, start_key, end_key):
    """Return (start, end) Timestamps, or None when neither key was supplied."""
    start_raw, end_raw = params.get(start_key), params.get(end_key)
    start_given = start_raw not in (None, "")
    end_given = end_raw not in (None, "")
    if not start_given and not end_given:
        return None
    if start_given != end_given:
        raise RequestError(f"{start_key} and {end_key} must be provided together")
    start = parse_date(start_key, start_raw)
    end = parse_date(end_key, end_raw)
    if start > end:
        raise RequestError(f"{start_key} must not be after {end_key}")
    return start, end


# --- data loading ----------------------------------------------------------------
def _read_csv(data_dir, filename):
    columns = REQUIRED_COLUMNS[filename]
    try:
        return pd.read_csv(os.path.join(data_dir, filename), dtype=str, usecols=columns)
    except pd.errors.EmptyDataError:  # zero-byte file
        return pd.DataFrame({c: pd.Series(dtype=str) for c in columns})


def load_data(data_dir):
    return (_read_csv(data_dir, "organizations.csv"),
            _read_csv(data_dir, "states.csv"),
            _read_csv(data_dir, "countries.csv"))


def prepare_organizations(orgs, states, countries):
    """One row per organization with its creation day, collaborator flag and country code.

    organizations.state_id -> states.country_id -> countries.country_code.
    Rows without a parseable created_at can't be placed on the timeline and are dropped.
    """
    created = pd.to_datetime(orgs["created_at"], errors="coerce", format="mixed", utc=True)
    orgs = orgs.assign(
        created=created.dt.tz_localize(None).dt.normalize(),
        is_collaborator=(orgs["is_collaborator"].fillna("").str.strip().str.lower()
                         .isin(["true", "t", "1", "yes", "y"])),
    )
    orgs = orgs[orgs["created"].notna()]

    state_country = states.dropna(subset=["state_id"]).drop_duplicates("state_id")[["state_id", "country_id"]]
    country_code = countries.dropna(subset=["country_id"]).drop_duplicates("country_id")[["country_id", "country_code"]]
    orgs = (orgs.merge(state_country, on="state_id", how="left")
                .merge(country_code, on="country_id", how="left"))
    return orgs.rename(columns={"country_code": "country"})[["created", "is_collaborator", "country"]]


# --- aggregation -----------------------------------------------------------------
def in_window(days, start, end):
    mask = pd.Series(True, index=days.index)
    if start is not None:
        mask &= days >= start
    if end is not None:
        mask &= days < end + pd.Timedelta(days=1)
    return mask


def growth_trend(orgs, start, end, freq):
    """Per-period series for organizations created inside [start, end].

    total_organizations is the all-time running total as of the end of each period
    (never reset to the window start); collaborators is that period's own count.
    Periods with no new organizations are left out.
    """
    empty = {"total_organizations": [], "collaborators": []}
    window = orgs[in_window(orgs["created"], start, end)]
    if window.empty:
        return empty

    periods = window["created"].dt.to_period(freq)
    collaborators = window["is_collaborator"].groupby(periods).sum()
    all_days = np.sort(orgs["created"].to_numpy())
    cap = None if end is None else end + pd.Timedelta(days=1)

    total_series, collaborator_series = [], []
    for period in sorted(collaborators.index):
        boundary = (period + 1).start_time
        if cap is not None and cap < boundary:
            boundary = cap
        running_total = int(np.searchsorted(all_days, boundary.to_datetime64(), side="left"))
        total_series.append({"period": str(period), "count": running_total})
        collaborator_series.append({"period": str(period), "count": int(collaborators[period])})
    return {"total_organizations": total_series, "collaborators": collaborator_series}


def organizations_by_location(orgs, start, end):
    """Top countries by organization count inside [start, end] (no 'Other' row)."""
    window = orgs[in_window(orgs["created"], start, end)]
    counts = window.dropna(subset=["country"]).groupby("country").size()
    if counts.empty:
        return []
    ranked = counts.reset_index(name="n").sort_values(["n", "country"], ascending=[False, True])
    return [{"country": country, "count": int(n)}
            for country, n in zip(ranked["country"][:TOP_LOCATIONS], ranked["n"][:TOP_LOCATIONS])]


def build_response(orgs, today, growth_range=None, location_range=None):
    result = {}
    for bucket, (offset, freq) in FIXED_BUCKETS.items():
        start = None if offset is None else today - offset
        end = None if offset is None else today
        result[bucket] = {
            "growth_trend": growth_trend(orgs, start, end, freq),
            "organizations_by_location": organizations_by_location(orgs, start, end),
        }

    result["Custom"] = {
        "growth_trend": (growth_trend(orgs, *growth_range, "D") if growth_range
                         else {"total_organizations": [], "collaborators": []}),
        "organizations_by_location": (organizations_by_location(orgs, *location_range)
                                      if location_range else []),
    }
    return result


# --- Lambda entry point -------------------------------------------------------------
def _today():
    return pd.Timestamp(datetime.now(timezone.utc).date())


def _reply(status_code, payload):
    return {"statusCode": status_code, "headers": RESPONSE_HEADERS, "body": json.dumps(payload)}


def lambda_handler(event, context):
    try:
        params = parse_event_body(event)
        growth_range = parse_range(params, "start_date", "end_date")
        location_range = parse_range(params, "location_start_date", "location_end_date")
    except RequestError as exc:
        return _reply(400, {"error": str(exc)})

    try:
        data_dir = os.environ.get("MOCK_DATA_DIR", DEFAULT_DATA_DIR)
        orgs = prepare_organizations(*load_data(data_dir))
        return _reply(200, build_response(orgs, _today(), growth_range, location_range))
    except Exception:
        logger.exception("growth_location_analytics failed")
        return _reply(500, {"error": "Internal server error"})


if __name__ == "__main__":
    sample_events = [
        ("no body", {}),
        ("growth-trend range only", {"body": json.dumps({"start_date": "2026-01-01", "end_date": "2026-06-30"})}),
        ("location range only", {"body": json.dumps({"location_start_date": "2025-01-01",
                                                     "location_end_date": "2025-12-31"})}),
        ("both ranges", {"body": json.dumps({"start_date": "2026-01-01", "end_date": "2026-06-30",
                                             "location_start_date": "2025-01-01",
                                             "location_end_date": "2025-12-31"})}),
        ("start after end (400)", {"body": json.dumps({"start_date": "2026-06-30", "end_date": "2026-01-01"})}),
    ]
    for label, sample in sample_events:
        reply = lambda_handler(sample, None)
        print(f"--- {label}: {sample.get('body', '{}')}")
        print(f"statusCode {reply['statusCode']}")
        print(json.dumps(json.loads(reply["body"]), separators=(",", ":")))
