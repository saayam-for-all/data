"""
Growth & Location Analytics API

Standalone Lambda function that returns data for the Growth & Location tab
of the Organization Analytics dashboard:

  - Growth Trend Chart: total_organizations (cumulative, all-time) and
    collaborators (per-period, window-scoped) over time.
  - Organizations by Location: top 4 countries by organization count,
    window-scoped.

All five fixed/variable buckets (7D, 30D, 1Y, All, Custom) are computed in a
single response so the frontend can switch ranges without another API call.

This is a fresh function -- it does not reuse or modify organization_analytics.py.
"""

import json
import os
from datetime import datetime, timedelta

import pandas as pd

MOCK_DATA_DIR = os.environ.get("MOCK_DATA_DIR", os.path.join(os.path.dirname(__file__), "mock_data"))

DATE_FMT = "%Y-%m-%d"
DAY_PERIOD_FMT = "%Y-%m-%d"
MONTH_PERIOD_FMT = "%Y-%m"

BUCKET_NAMES = ["7D", "30D", "1Y", "All", "Custom"]


class ValidationError(Exception):
    pass


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def _load_data(data_dir=MOCK_DATA_DIR):
    # organizations.state_id holds state CODES (e.g. "AK", "TX"), not a
    # numeric id, so it must be read/joined as a string.
    orgs = pd.read_csv(
        os.path.join(data_dir, "organizations.csv"),
        dtype={"org_id": "string", "state_id": "string"},
    )
    states = pd.read_csv(
        os.path.join(data_dir, "state.csv"),
        dtype={"state_id": "string", "country_id": "Int64"},
    )
    countries = pd.read_csv(
        os.path.join(data_dir, "country.csv"),
        dtype={"country_id": "Int64", "country_code": "string"},
    )

    if orgs.empty:
        orgs["created_at"] = pd.Series(dtype="datetime64[ns]")
        orgs["is_collaborator"] = pd.Series(dtype="bool")
        orgs["country_code"] = pd.Series(dtype="object")
        return orgs

    orgs["created_at"] = pd.to_datetime(orgs["created_at"]).dt.normalize()
    orgs["is_collaborator"] = orgs["is_collaborator"].astype(str).str.strip().str.lower().isin(
        ["true", "1", "yes"]
    )

    merged = orgs.merge(states, on="state_id", how="left").merge(
        countries[["country_id", "country_code"]], on="country_id", how="left"
    )
    orgs["country_code"] = merged["country_code"]
    return orgs


# --------------------------------------------------------------------------
# Date parsing / validation
# --------------------------------------------------------------------------

def _parse_date(value, field_name):
    try:
        return datetime.strptime(value, DATE_FMT)
    except (ValueError, TypeError):
        raise ValidationError(
            "Invalid date format for '%s': expected YYYY-MM-DD" % field_name
        )


def _validate_range(start_value, end_value, start_name, end_name):
    """Returns (start_dt, end_dt) or (None, None) if neither supplied."""
    if start_value is None and end_value is None:
        return None, None
    if start_value is None or end_value is None:
        raise ValidationError(
            "Both '%s' and '%s' must be supplied together" % (start_name, end_name)
        )
    start_dt = _parse_date(start_value, start_name)
    end_dt = _parse_date(end_value, end_name)
    if start_dt > end_dt:
        raise ValidationError(
            "'%s' must not be after '%s'" % (start_name, end_name)
        )
    return start_dt, end_dt


# --------------------------------------------------------------------------
# Growth trend
# --------------------------------------------------------------------------

def _period_label(dt, granularity):
    if granularity == "day":
        return dt.strftime(DAY_PERIOD_FMT)
    return dt.strftime(MONTH_PERIOD_FMT)


def _build_growth_trend(orgs, window_start, window_end, granularity):
    """
    window_start / window_end: pandas Timestamps (inclusive), or None for
    "no lower/upper bound" (used by the All bucket).

    total_organizations: absolute cumulative count as of each included
    period's end, computed against the FULL dataset (not window-limited).
    collaborators: per-period count of collaborator orgs created within
    that period, scoped to the window.
    """
    empty = {"total_organizations": [], "collaborators": []}
    if orgs.empty:
        return empty

    windowed = orgs
    if window_start is not None:
        windowed = windowed[windowed["created_at"] >= window_start]
    if window_end is not None:
        windowed = windowed[windowed["created_at"] <= window_end]

    if windowed.empty:
        return empty

    period_col = windowed["created_at"].apply(lambda d: _period_label(d, granularity))
    windowed = windowed.assign(period=period_col)

    # Determine the periods that had at least one org created within the window.
    activity = windowed.groupby("period").size()
    # Sort periods chronologically. Since period labels are YYYY-MM-DD or
    # YYYY-MM, lexicographic sort order matches chronological order.
    included_periods = sorted(activity.index.tolist())

    # For cumulative total_organizations, we need each period's end boundary
    # (in absolute time) so we can count all-time orgs created at-or-before it.
    if granularity == "day":
        period_end_lookup = {p: pd.Timestamp(p) for p in included_periods}
    else:
        period_end_lookup = {
            p: (pd.Timestamp(p + "-01") + pd.offsets.MonthEnd(0)) for p in included_periods
        }

    all_created = orgs["created_at"]

    total_organizations = []
    collaborators = []
    for p in included_periods:
        period_end = period_end_lookup[p]
        cumulative_count = int((all_created <= period_end).sum())
        total_organizations.append({"period": p, "count": cumulative_count})

        period_rows = windowed[windowed["period"] == p]
        collab_count = int(period_rows["is_collaborator"].sum())
        collaborators.append({"period": p, "count": collab_count})

    return {"total_organizations": total_organizations, "collaborators": collaborators}


# --------------------------------------------------------------------------
# Organizations by location
# --------------------------------------------------------------------------

def _build_organizations_by_location(orgs, window_start, window_end, top_n=4):
    if orgs.empty:
        return []

    windowed = orgs
    if window_start is not None:
        windowed = windowed[windowed["created_at"] >= window_start]
    if window_end is not None:
        windowed = windowed[windowed["created_at"] <= window_end]

    if windowed.empty:
        return []

    windowed = windowed.dropna(subset=["country_code"])
    if windowed.empty:
        return []

    counts = (
        windowed.groupby("country_code")
        .size()
        .sort_values(ascending=False)
    )
    counts = counts.head(top_n)

    return [
        {"country": country, "count": int(count)}
        for country, count in counts.items()
    ]


# --------------------------------------------------------------------------
# Fixed bucket window helpers
# --------------------------------------------------------------------------

def _fixed_windows(reference_date):
    """
    Returns a dict of bucket -> (start, end, granularity) for the four
    fixed buckets. `end` is always the reference date (today), normalized.
    `start` is None for "All" (no lower bound).
    """
    today = pd.Timestamp(reference_date).normalize()
    return {
        "7D": (today - pd.Timedelta(days=7), today, "day"),
        "30D": (today - pd.Timedelta(days=30), today, "day"),
        # Trailing 12 calendar months (per spec), not a fixed 365-day window.
        "1Y": (today - pd.DateOffset(months=12), today, "month"),
        "All": (None, today, "month"),
    }


# --------------------------------------------------------------------------
# Handler
# --------------------------------------------------------------------------

def handler(event, context=None):
    event = event or {}

    if "body" in event:
        raw_body = event.get("body")
        if raw_body is None or raw_body == "":
            body = {}
        elif isinstance(raw_body, str):
            try:
                body = json.loads(raw_body)
            except json.JSONDecodeError:
                return _error_response("Invalid JSON body")
        else:
            body = raw_body
    else:
        # Allow passing params directly as the event for local testing.
        body = event

    try:
        growth_start, growth_end = _validate_range(
            body.get("start_date"), body.get("end_date"), "start_date", "end_date"
        )
        location_start, location_end = _validate_range(
            body.get("location_start_date"),
            body.get("location_end_date"),
            "location_start_date",
            "location_end_date",
        )
    except ValidationError as e:
        return _error_response(str(e))

    try:
        orgs = _load_data()
    except FileNotFoundError as e:
        return _error_response("Required data file not found: %s" % str(e))

    reference_date = datetime.now()
    fixed_windows = _fixed_windows(reference_date)

    response = {}
    for bucket in ["7D", "30D", "1Y", "All"]:
        start, end, granularity = fixed_windows[bucket]
        response[bucket] = {
            "growth_trend": _build_growth_trend(orgs, start, end, granularity),
            "organizations_by_location": _build_organizations_by_location(orgs, start, end),
        }

    custom_growth_trend = {"total_organizations": [], "collaborators": []}
    custom_location = []
    if growth_start is not None:
        custom_growth_trend = _build_growth_trend(orgs, growth_start, growth_end, "day")
    if location_start is not None:
        custom_location = _build_organizations_by_location(orgs, location_start, location_end)

    response["Custom"] = {
        "growth_trend": custom_growth_trend,
        "organizations_by_location": custom_location,
    }

    return {
        "statusCode": 200,
        "body": json.dumps(response),
    }


def _error_response(message):
    return {
        "statusCode": 400,
        "body": json.dumps({"error": message}),
    }


# --------------------------------------------------------------------------
# Local test harness
# --------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("TEST 1: No body")
    print("=" * 70)
    result = handler({})
    print(json.dumps(json.loads(result["body"]), indent=2))

    print("\n" + "=" * 70)
    print("TEST 2: Only growth-trend custom range (start_date/end_date)")
    print("=" * 70)
    result = handler({
        "body": json.dumps({
            "start_date": "2026-06-01",
            "end_date": "2026-09-13",
        })
    })
    parsed = json.loads(result["body"])
    print(json.dumps(parsed["Custom"], indent=2))

    print("\n" + "=" * 70)
    print("TEST 3: Only location custom range (location_start_date/location_end_date)")
    print("=" * 70)
    result = handler({
        "body": json.dumps({
            "location_start_date": "2025-09-01",
            "location_end_date": "2026-09-13",
        })
    })
    parsed = json.loads(result["body"])
    print(json.dumps(parsed["Custom"], indent=2))

    print("\n" + "=" * 70)
    print("TEST 4: Both custom ranges supplied")
    print("=" * 70)
    result = handler({
        "body": json.dumps({
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "location_start_date": "2025-01-01",
            "location_end_date": "2025-12-31",
        })
    })
    parsed = json.loads(result["body"])
    print(json.dumps(parsed["Custom"], indent=2))

    print("\n" + "=" * 70)
    print("TEST 5: Invalid date format -> expect 400")
    print("=" * 70)
    result = handler({"body": json.dumps({"start_date": "06/01/2026", "end_date": "2026-09-13"})})
    print(result)

    print("\n" + "=" * 70)
    print("TEST 6: start_date after end_date -> expect 400")
    print("=" * 70)
    result = handler({"body": json.dumps({"start_date": "2026-09-13", "end_date": "2026-01-01"})})
    print(result)

    print("\n" + "=" * 70)
    print("SANITY CHECKS")
    print("=" * 70)
    orgs_df = _load_data()
    all_bucket = json.loads(handler({})["body"])["All"]
    last_all_total = all_bucket["growth_trend"]["total_organizations"][-1]["count"] if all_bucket["growth_trend"]["total_organizations"] else 0
    print("Dataset row count:", len(orgs_df))
    print("Last 'All' cumulative total_organizations entry:", last_all_total)
    assert last_all_total == len(orgs_df), "Cumulative total should equal full dataset row count"
    print("OK: cumulative total matches dataset size")

    loc_sum_all = sum(r["count"] for r in all_bucket["organizations_by_location"])
    print("organizations_by_location sum ('All' bucket):", loc_sum_all, "vs dataset size:", len(orgs_df))

    periods_1y = [r["period"] for r in json.loads(handler({})["body"])["1Y"]["growth_trend"]["total_organizations"]]
    print("1Y periods (should be YYYY-MM, monthly):", periods_1y[:5])

    periods_7d = [r["period"] for r in json.loads(handler({})["body"])["7D"]["growth_trend"]["total_organizations"]]
    print("7D periods (should be YYYY-MM-DD, daily):", periods_7d[:5])

    print("\nAll sanity checks passed.")
