"""Growth & Location Analytics API for the Organization Dashboard (issue #336).

Standalone function (no DB) - reads organizations.csv, state.csv, and
country.csv, joins organizations -> states -> countries, and returns growth
trend + top-locations data for five fixed time buckets: 7D, 30D, 1Y, All,
Custom. The two charts filter independently: the growth trend chart uses
start_date/end_date, the location chart uses location_start_date/
location_end_date (both only apply to the Custom bucket).

Unlike the other files in this directory (which read from Postgres), this
one is CSV-based per the issue's explicit spec - see README design notes
in the PR description for why.
"""
import json
import os
from collections import OrderedDict
from datetime import datetime

import pandas as pd

DEFAULT_CSV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sql")
TOP_N_LOCATIONS = 4
STANDARD_BUCKETS = ["7D", "30D", "1Y", "All"]

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def parse_event_body(event):
    if not event:
        return {}
    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body, dict):
        return body
    return {}


def _response(status_code, payload):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(payload, default=str),
    }


def _parse_date(value):
    """Returns a pandas Timestamp, or None if value is missing/unparseable.
    Unparseable/missing dates fall back to "no restriction" rather than
    raising, so a bad Custom-range param degrades gracefully instead of
    failing the whole request."""
    if not value:
        return None
    try:
        return pd.Timestamp(value)
    except (ValueError, TypeError):
        return None


# --- Data loading --------------------------------------------------------

def load_organizations(csv_dir=DEFAULT_CSV_DIR):
    df = pd.read_csv(os.path.join(csv_dir, "organizations.csv"))
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["is_collaborator"] = df["is_collaborator"].astype(str).str.strip().str.upper() == "TRUE"
    return df


def load_states(csv_dir=DEFAULT_CSV_DIR):
    df = pd.read_csv(os.path.join(csv_dir, "state.csv"))
    # Bug fix: this source file has country_id=1 (Afghanistan) for every US
    # state; the real USA row in country.csv is country_id=233. Same issue
    # found and fixed for the mock-data-generation copy in issue #301.
    df["country_id"] = 233
    return df


def load_countries(csv_dir=DEFAULT_CSV_DIR):
    return pd.read_csv(os.path.join(csv_dir, "country.csv"))


def build_joined_dataframe(csv_dir=DEFAULT_CSV_DIR):
    orgs = load_organizations(csv_dir)
    states = load_states(csv_dir)
    countries = load_countries(csv_dir)

    merged = orgs.merge(
        states[["state_id", "country_id"]], on="state_id", how="left"
    ).merge(
        countries[["country_id", "country_name"]], on="country_id", how="left"
    )
    merged["country_name"] = merged["country_name"].fillna("Unknown")
    return merged


# --- Aggregation -----------------------------------------------------------

def resolve_standard_window(bucket_key, reference_date):
    """(window_start, window_end, granularity) for the 4 non-Custom buckets."""
    reference_date = pd.Timestamp(reference_date)
    if bucket_key == "7D":
        return reference_date - pd.Timedelta(days=6), reference_date, "day"
    if bucket_key == "30D":
        return reference_date - pd.Timedelta(days=29), reference_date, "day"
    if bucket_key == "1Y":
        start = (reference_date - pd.DateOffset(months=11)).replace(day=1)
        return start, reference_date, "month"
    if bucket_key == "All":
        return None, reference_date, "month"
    raise ValueError(f"resolve_standard_window does not handle {bucket_key!r}")


def compute_growth_trend(df, granularity, window_start, window_end):
    """total_organizations: all-time cumulative running total, reported only
    for periods within the window that have at least one new organization.
    collaborators: per-period (not cumulative) count of new collaborator
    organizations within the window. Both arrays are sparse by construction
    (groupby only yields periods that actually occur in the data)."""
    if df.empty:
        return {"total_organizations": [], "collaborators": []}

    valid = df.dropna(subset=["created_at"]).copy()
    if valid.empty:
        return {"total_organizations": [], "collaborators": []}

    freq = "D" if granularity == "day" else "M"
    valid["period"] = valid["created_at"].dt.to_period(freq)

    counts = valid.groupby("period").size().sort_index()
    cumulative = counts.cumsum()
    collab_counts = valid[valid["is_collaborator"]].groupby("period").size().sort_index()

    start_period = window_start.to_period(freq) if window_start is not None else None
    end_period = window_end.to_period(freq) if window_end is not None else None

    def in_window(period):
        if start_period is not None and period < start_period:
            return False
        if end_period is not None and period > end_period:
            return False
        return True

    period_fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m"

    total_organizations = [
        {"period": period.strftime(period_fmt), "count": int(count)}
        for period, count in cumulative.items()
        if in_window(period)
    ]
    collaborators = [
        {"period": period.strftime(period_fmt), "count": int(count)}
        for period, count in collab_counts.items()
        if in_window(period)
    ]
    return {"total_organizations": total_organizations, "collaborators": collaborators}


def compute_organizations_by_location(df, window_start, window_end, top_n=TOP_N_LOCATIONS):
    """Top N countries by organization count, scoped to the window. No
    'Other' bucket and no percentage fields, per the issue's spec."""
    if df.empty:
        return []

    valid = df.dropna(subset=["created_at"])
    if window_start is not None:
        valid = valid[valid["created_at"].dt.date >= window_start.date()]
    if window_end is not None:
        valid = valid[valid["created_at"].dt.date <= window_end.date()]
    if valid.empty:
        return []

    counts = valid.groupby("country_name").size().sort_values(ascending=False)
    return [{"country": country, "count": int(count)} for country, count in counts.head(top_n).items()]


def build_bucket(df, bucket_key, reference_date, growth_start=None, growth_end=None,
                  location_start=None, location_end=None):
    if bucket_key == "Custom":
        granularity = "day"
        g_start, g_end = growth_start, growth_end
        l_start, l_end = location_start, location_end
    else:
        g_start, g_end, granularity = resolve_standard_window(bucket_key, reference_date)
        l_start, l_end = g_start, g_end

    return {
        "growth_trend": compute_growth_trend(df, granularity, g_start, g_end),
        "organizations_by_location": compute_organizations_by_location(df, l_start, l_end),
    }


def generate_response(df, growth_start=None, growth_end=None, location_start=None,
                       location_end=None, reference_date=None):
    """Returns the full 5-key response: {"7D":..., "30D":..., "1Y":..., "All":..., "Custom":...}."""
    reference_date = reference_date or datetime.now()

    response = OrderedDict()
    for bucket_key in STANDARD_BUCKETS:
        response[bucket_key] = build_bucket(df, bucket_key, reference_date)
    response["Custom"] = build_bucket(
        df, "Custom", reference_date,
        growth_start=growth_start, growth_end=growth_end,
        location_start=location_start, location_end=location_end,
    )
    return response


# --- Lambda entrypoint -----------------------------------------------------

def lambda_handler(event, context):
    try:
        params = parse_event_body(event)
        df = build_joined_dataframe()
        payload = generate_response(
            df,
            growth_start=_parse_date(params.get("start_date")),
            growth_end=_parse_date(params.get("end_date")),
            location_start=_parse_date(params.get("location_start_date")),
            location_end=_parse_date(params.get("location_end_date")),
        )
        return _response(200, payload)
    except Exception as exc:  # keep the dashboard from getting a raw 5xx traceback
        return _response(500, {"error": str(exc)})


if __name__ == "__main__":
    # Sample data (data-analytics/sql/organizations.csv) spans 2023-09 to
    # 2026-01, so a fixed reference_date inside that range gives non-empty
    # 7D/30D/1Y buckets for a local smoke test rather than relying on
    # whatever "today" happens to be when this is run.
    joined = build_joined_dataframe()
    result = generate_response(joined, reference_date=datetime(2026, 1, 15))
    print(json.dumps(result, indent=2, default=str))
