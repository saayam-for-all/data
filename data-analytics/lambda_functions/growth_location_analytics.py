"""
Growth & Location Analytics API for the Organization Dashboard's
"Growth & Location" tab (issue #336).

Returns, in a single response, both charts for all five time buckets
(7D / 30D / 1Y / All / Custom) so the frontend can switch either chart's
range instantly without a new API call:

  - growth_trend: organizations (cumulative, all-time) and collaborators
    (per-period, window-scoped) over time.
  - organizations_by_location: top 4 countries by organization count,
    window-scoped.

This is a new, standalone function - it is not a refactor of
organization_analytics.py.

Data source: organizations.csv / states.csv / countries.csv, loaded with
pandas from the directory named by the MOCK_DATA_DIR environment variable
(default: a "mock_data" folder next to this file). See the issue for the
local-testing setup and the required columns on each CSV. This lambda does
not call AWS in any way and should not be deployed directly.
"""

import json
import os

import pandas as pd

REQUIRED_ORG_COLUMNS = ["org_id", "state_id", "city_name", "is_collaborator", "created_at"]
REQUIRED_STATE_COLUMNS = ["state_id", "state_name", "country_id"]
REQUIRED_COUNTRY_COLUMNS = ["country_id", "country_code"]

FIXED_BUCKETS = ["7D", "30D", "1Y", "All"]

# bucket -> grouping granularity, per the issue's "Growth Trend Bucketing
# Granularity" table: 7D/30D/Custom group by day, 1Y/All group by month.
BUCKET_GRANULARITY = {
    "7D": "day",
    "30D": "day",
    "1Y": "month",
    "All": "month",
    "Custom": "day",
}

TOP_N_LOCATIONS = 4


class InvalidDateRangeError(ValueError):
    """Raised for a malformed or inverted Custom date range."""


def _mock_data_dir():
    return os.environ.get(
        "MOCK_DATA_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data"),
    )


def parse_event_body(event):
    """
    Normalizes the incoming Lambda event - handles both a raw dict (local/
    direct invocation) and an API-Gateway-style event with a JSON string (or
    dict) "body" key.
    """
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


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _read_required_csv(data_dir, filename, required_columns):
    path = os.path.join(data_dir, filename)
    df = pd.read_csv(path, dtype=str)
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        raise ValueError(f"{filename} is missing required column(s): {', '.join(missing)}")
    return df


def load_organizations(data_dir=None):
    """
    Loads organizations.csv/states.csv/countries.csv from data_dir (default:
    MOCK_DATA_DIR, or a "mock_data" folder next to this file) and returns a
    single DataFrame of organizations with a resolved "country_code" column
    (via state_id -> states.country_id -> countries.country_code) and typed
    "created_at" (datetime) / "is_collaborator" (bool) columns.

    An organization whose state_id doesn't match a known state, or whose
    state's country_id doesn't match a known country, gets country_code
    "Unknown" rather than being dropped, so it still counts toward
    growth-trend totals. An organization with an unparseable created_at is
    dropped (it can't be placed in any time bucket) - a message is printed
    for each one.
    """
    data_dir = data_dir or _mock_data_dir()

    organizations = _read_required_csv(data_dir, "organizations.csv", REQUIRED_ORG_COLUMNS)
    states = _read_required_csv(data_dir, "states.csv", REQUIRED_STATE_COLUMNS)
    countries = _read_required_csv(data_dir, "countries.csv", REQUIRED_COUNTRY_COLUMNS)

    states = states[["state_id", "country_id"]].drop_duplicates(subset="state_id")
    countries = countries[["country_id", "country_code"]].drop_duplicates(subset="country_id")

    merged = organizations.merge(states, on="state_id", how="left")
    merged = merged.merge(countries, on="country_id", how="left")
    merged["country_code"] = merged["country_code"].fillna("Unknown")

    merged["is_collaborator"] = (
        merged["is_collaborator"].astype(str).str.strip().str.upper().eq("TRUE")
    )

    created_at = pd.to_datetime(merged["created_at"], errors="coerce")
    for org_id in merged.loc[created_at.isna(), "org_id"]:
        print(f"Skipping organization {org_id}: unparseable created_at")
    merged = merged.loc[created_at.notna()].copy()
    merged["created_at"] = created_at.loc[created_at.notna()]

    return merged.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Windowing
# ---------------------------------------------------------------------------

def _window_mask(organizations, window_start, window_end):
    mask = pd.Series(True, index=organizations.index)
    if window_start is not None:
        mask &= organizations["created_at"] >= window_start
    if window_end is not None:
        mask &= organizations["created_at"] <= window_end
    return mask


def _fixed_window(bucket, reference_date):
    """Returns (window_start, window_end) for a fixed (non-Custom) bucket."""
    if bucket == "7D":
        return reference_date - pd.Timedelta(days=7), reference_date
    if bucket == "30D":
        return reference_date - pd.Timedelta(days=30), reference_date
    if bucket == "1Y":
        return reference_date - pd.DateOffset(years=1), reference_date
    return None, None  # "All"


def _parse_custom_range(start_value, end_value, start_field, end_field):
    """
    Validates one Custom start/end pair. Returns (start, end) as Timestamps
    (end normalized to the end of its day, so the range is inclusive), or
    (None, None) if neither value was supplied.

    Raises InvalidDateRangeError if only one of the pair is supplied, either
    value fails to parse, or start is after end.
    """
    if start_value is None and end_value is None:
        return None, None

    if start_value is None or end_value is None:
        raise InvalidDateRangeError(f"Both {start_field} and {end_field} are required together")

    start = pd.to_datetime(start_value, errors="coerce")
    end = pd.to_datetime(end_value, errors="coerce")

    if pd.isna(start) or pd.isna(end):
        raise InvalidDateRangeError(f"{start_field} and {end_field} must be valid dates (e.g. YYYY-MM-DD)")

    if start > end:
        raise InvalidDateRangeError(f"{start_field} must not be after {end_field}")

    end = end + pd.Timedelta(hours=23, minutes=59, seconds=59)
    return start, end


# ---------------------------------------------------------------------------
# Growth Trend chart
# ---------------------------------------------------------------------------

def _period_key_series(created_at, granularity):
    fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m"
    return created_at.dt.strftime(fmt)


def _period_end(period, granularity):
    freq = "D" if granularity == "day" else "M"
    return pd.Period(period, freq=freq).end_time


def build_growth_trend(organizations, window_start, window_end, granularity):
    """
    Builds the growth_trend section for one bucket:
      - total_organizations: absolute, all-time running total (across the
        WHOLE dataset, not window-restricted) as of each period.
      - collaborators: per-period count of is_collaborator organizations
        created within the bucket's own window (not cumulative).
    Both series share the same set of periods: every period in which at
    least one organization was created within the window. Periods with no
    activity are omitted entirely (sparse, not zero-filled).
    """
    windowed = organizations.loc[_window_mask(organizations, window_start, window_end)]

    if windowed.empty:
        return {"total_organizations": [], "collaborators": []}

    period_key = _period_key_series(windowed["created_at"], granularity)
    periods = sorted(period_key.unique())

    all_created_at = organizations["created_at"]
    total_series = [
        {"period": period, "count": int((all_created_at <= _period_end(period, granularity)).sum())}
        for period in periods
    ]

    collaborator_counts = period_key[windowed["is_collaborator"]].value_counts()
    collaborators_series = [
        {"period": period, "count": int(collaborator_counts.get(period, 0))}
        for period in periods
    ]

    return {"total_organizations": total_series, "collaborators": collaborators_series}


# ---------------------------------------------------------------------------
# Organizations By Location chart
# ---------------------------------------------------------------------------

def build_organizations_by_location(organizations, window_start, window_end):
    """
    Top TOP_N_LOCATIONS countries by organization count, window-scoped (not
    cumulative). No "Other" row, no percentage field. Ties are broken by
    country code (ascending) for a deterministic order. Fewer than
    TOP_N_LOCATIONS distinct countries in-window -> all of them are returned.
    """
    windowed = organizations.loc[_window_mask(organizations, window_start, window_end)]

    if windowed.empty:
        return []

    counts = (
        windowed.groupby("country_code")
        .size()
        .reset_index(name="count")
        .sort_values(["count", "country_code"], ascending=[False, True])
        .head(TOP_N_LOCATIONS)
    )

    return [
        {"country": row.country_code, "count": int(row.count)}
        for row in counts.itertuples()
    ]


# ---------------------------------------------------------------------------
# Response assembly
# ---------------------------------------------------------------------------

def _build_bucket(organizations, window_start, window_end, granularity):
    return {
        "growth_trend": build_growth_trend(organizations, window_start, window_end, granularity),
        "organizations_by_location": build_organizations_by_location(organizations, window_start, window_end),
    }


def build_growth_location_response(organizations, request_body, reference_date=None):
    """
    Builds the full 5-bucket response body. Raises InvalidDateRangeError
    (the caller turns this into a 400) for a malformed Custom range.
    """
    reference_date = reference_date if reference_date is not None else pd.Timestamp.now().normalize()

    response = {}
    for bucket in FIXED_BUCKETS:
        window_start, window_end = _fixed_window(bucket, reference_date)
        response[bucket] = _build_bucket(organizations, window_start, window_end, BUCKET_GRANULARITY[bucket])

    growth_start, growth_end = _parse_custom_range(
        request_body.get("start_date"), request_body.get("end_date"), "start_date", "end_date"
    )
    location_start, location_end = _parse_custom_range(
        request_body.get("location_start_date"), request_body.get("location_end_date"),
        "location_start_date", "location_end_date",
    )

    custom_growth_trend = (
        build_growth_trend(organizations, growth_start, growth_end, BUCKET_GRANULARITY["Custom"])
        if growth_start is not None
        else {"total_organizations": [], "collaborators": []}
    )
    custom_location = (
        build_organizations_by_location(organizations, location_start, location_end)
        if location_start is not None
        else []
    )

    response["Custom"] = {
        "growth_trend": custom_growth_trend,
        "organizations_by_location": custom_location,
    }

    return response


def lambda_handler(event, context):
    request_body = parse_event_body(event)

    try:
        organizations = load_organizations()
    except (OSError, ValueError) as error:
        print(f"Failed to load organizations data: {error}")
        return build_response(500, {"error": "Failed to load organizations data"})

    try:
        response_body = build_growth_location_response(organizations, request_body)
    except InvalidDateRangeError as error:
        return build_response(400, {"error": str(error)})

    return build_response(200, response_body)


if __name__ == "__main__":
    # Local run only - point MOCK_DATA_DIR at a folder with organizations.csv
    # / states.csv / countries.csv (see the issue for required columns), or
    # drop them in a "mock_data" folder next to this file.
    test_events = [
        {},
        {"start_date": "2026-01-01", "end_date": "2026-06-30"},
        {"location_start_date": "2025-01-01", "location_end_date": "2025-12-31"},
        {
            "start_date": "2026-01-01", "end_date": "2026-06-30",
            "location_start_date": "2025-01-01", "location_end_date": "2025-12-31",
        },
    ]

    for test_event in test_events:
        print(f"--- Testing payload: {test_event} ---")
        result = lambda_handler(test_event, None)
        if result["statusCode"] == 200:
            print(json.dumps(json.loads(result["body"]), indent=2))
        else:
            print(json.dumps(result, indent=2))
