"""
Growth & Location Analytics API for the Organization Analytics dashboard
(issue #336).

Standalone function -- not a refactor of organization_analytics.py -- that
returns data for the "Growth & Location" tab:

  - Growth Trend chart: total_organizations (absolute, all-time running
    total) and collaborators (per-period, window-scoped) over time.
  - Organizations by Location chart: top 4 countries by organization
    count, window-scoped.

All fixed time buckets (7D/30D/1Y/All) are returned in a single response
so the frontend can switch either chart's range without a new API call.
Each chart also has its own independent Custom date-range parameters.

Data source: organizations.csv / states.csv / countries.csv, loaded with
pandas from MOCK_DATA_DIR. Per the issue, these mock CSVs are local-only
and are NOT committed as part of this PR.
"""

import json
import os
from datetime import datetime, timedelta

import pandas as pd

MOCK_DATA_DIR = os.environ.get(
    "MOCK_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data"),
)

ORGANIZATIONS_CSV = os.path.join(MOCK_DATA_DIR, "organizations.csv")
STATES_CSV = os.path.join(MOCK_DATA_DIR, "states.csv")
COUNTRIES_CSV = os.path.join(MOCK_DATA_DIR, "countries.csv")

TOP_LOCATIONS_LIMIT = 4

BUCKET_GRANULARITY = {
    "7D": "day",
    "30D": "day",
    "1Y": "month",
    "All": "month",
    "Custom": "day",
}


class InvalidFilterError(Exception):
    """Raised when a request's date-range filters fail validation."""


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body) if not isinstance(body, str) else body,
    }


def get_default_response():
    empty_bucket = {
        "growth_trend": {"total_organizations": [], "collaborators": []},
        "organizations_by_location": [],
    }
    return {
        "7D": json.loads(json.dumps(empty_bucket)),
        "30D": json.loads(json.dumps(empty_bucket)),
        "1Y": json.loads(json.dumps(empty_bucket)),
        "All": json.loads(json.dumps(empty_bucket)),
        "Custom": json.loads(json.dumps(empty_bucket)),
    }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(data_dir=None):
    """Loads organizations/states/countries CSVs into DataFrames.

    Returns empty-but-correctly-shaped DataFrames if a file is missing or
    empty, so downstream aggregation code doesn't need to special-case it.
    """
    org_path = os.path.join(data_dir, "organizations.csv") if data_dir else ORGANIZATIONS_CSV
    states_path = os.path.join(data_dir, "states.csv") if data_dir else STATES_CSV
    countries_path = os.path.join(data_dir, "countries.csv") if data_dir else COUNTRIES_CSV

    try:
        df_orgs = pd.read_csv(org_path)
        df_orgs["created_at"] = pd.to_datetime(df_orgs["created_at"], errors="coerce")
        if "is_collaborator" in df_orgs.columns:
            df_orgs["is_collaborator"] = df_orgs["is_collaborator"].astype(bool)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        df_orgs = pd.DataFrame(columns=["org_id", "state_id", "city_name", "is_collaborator", "created_at"])

    try:
        df_states = pd.read_csv(states_path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        df_states = pd.DataFrame(columns=["state_id", "state_name", "country_id"])

    try:
        df_countries = pd.read_csv(countries_path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        df_countries = pd.DataFrame(columns=["country_id", "country_code"])

    return df_orgs, df_states, df_countries


# ---------------------------------------------------------------------------
# Filter validation
# ---------------------------------------------------------------------------

def _parse_date(value, field_name):
    try:
        return pd.Timestamp(datetime.strptime(value, "%Y-%m-%d"))
    except (ValueError, TypeError):
        raise InvalidFilterError(f"{field_name} must be a valid date in YYYY-MM-DD format")


def validate_date_pair(start_value, end_value, start_field, end_field):
    """Validates one start/end pair. Returns (start_ts, end_ts) or (None, None)
    if neither value was supplied. Raises InvalidFilterError on bad input."""
    if start_value is None and end_value is None:
        return None, None
    if start_value is None or end_value is None:
        raise InvalidFilterError(f"Both {start_field} and {end_field} are required together")

    start_ts = _parse_date(start_value, start_field)
    end_ts = _parse_date(end_value, end_field)
    if start_ts > end_ts:
        raise InvalidFilterError(f"{start_field} must not be after {end_field}")

    # Make end_ts inclusive of the whole day.
    end_ts = end_ts + timedelta(hours=23, minutes=59, seconds=59)
    return start_ts, end_ts


def get_fixed_window(bucket, now=None):
    """Returns (start_ts, end_ts) for a fixed bucket. start_ts is None for
    'All' (no lower bound)."""
    now = now or pd.Timestamp.now()
    end_ts = now
    if bucket == "7D":
        return end_ts - timedelta(days=7), end_ts
    if bucket == "30D":
        return end_ts - timedelta(days=30), end_ts
    if bucket == "1Y":
        return end_ts - timedelta(days=365), end_ts
    if bucket == "All":
        return None, end_ts
    raise ValueError(f"Unknown fixed bucket: {bucket}")


# ---------------------------------------------------------------------------
# Growth Trend
# ---------------------------------------------------------------------------

def fetch_growth_trend(df_orgs, window_start, window_end, granularity):
    """Returns {"total_organizations": [...], "collaborators": [...]}.

    - total_organizations: absolute, all-time running total as of each
      period's end, computed against the FULL dataset (never reset to
      zero at the start of the window).
    - collaborators: per-period count of is_collaborator=True orgs
      created within that period, scoped to the window (not cumulative).
    - A period only appears if at least one organization was created in
      it within the window; empty periods are omitted.
    """
    if df_orgs.empty or window_end is None:
        return {"total_organizations": [], "collaborators": []}

    mask = df_orgs["created_at"] <= window_end
    if window_start is not None:
        mask &= df_orgs["created_at"] >= window_start
    window_df = df_orgs.loc[mask].copy()

    if window_df.empty:
        return {"total_organizations": [], "collaborators": []}

    strftime_fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m"
    window_df["period"] = window_df["created_at"].dt.strftime(strftime_fmt)

    periods = sorted(window_df["period"].unique())

    total_organizations = []
    collaborators = []
    for period in periods:
        period_rows = window_df.loc[window_df["period"] == period]
        period_end = period_rows["created_at"].max()

        cumulative_count = int((df_orgs["created_at"] <= period_end).sum())
        total_organizations.append({"period": period, "count": cumulative_count})

        collaborator_count = int(period_rows["is_collaborator"].sum())
        collaborators.append({"period": period, "count": collaborator_count})

    return {"total_organizations": total_organizations, "collaborators": collaborators}


# ---------------------------------------------------------------------------
# Organizations by Location
# ---------------------------------------------------------------------------

def fetch_organizations_by_location(df_orgs, df_states, df_countries, window_start, window_end):
    """Top 4 countries by organization count, window-scoped. Organizations
    only carry a state_id, so this joins
    organizations.state_id -> states.country_id -> countries.country_code.
    """
    if df_orgs.empty or window_end is None:
        return []

    mask = df_orgs["created_at"] <= window_end
    if window_start is not None:
        mask &= df_orgs["created_at"] >= window_start
    window_df = df_orgs.loc[mask]

    if window_df.empty or df_states.empty or df_countries.empty:
        return []

    merged = window_df.merge(
        df_states[["state_id", "country_id"]], on="state_id", how="left"
    )
    merged = merged.merge(
        df_countries[["country_id", "country_code"]], on="country_id", how="left"
    )
    merged = merged.dropna(subset=["country_code"])

    if merged.empty:
        return []

    counts = (
        merged.groupby("country_code")
        .size()
        .reset_index(name="count")
        .sort_values(["count", "country_code"], ascending=[False, True])
        .head(TOP_LOCATIONS_LIMIT)
    )

    return [
        {"country": row["country_code"], "count": int(row["count"])}
        for _, row in counts.iterrows()
    ]


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def _run_bucket(label, response_body, df_orgs, df_states, df_countries, window_start, window_end):
    granularity = BUCKET_GRANULARITY[label]
    try:
        response_body[label]["growth_trend"] = fetch_growth_trend(
            df_orgs, window_start, window_end, granularity
        )
    except Exception as e:
        print(f"{label} growth_trend failed: {e}")

    try:
        response_body[label]["organizations_by_location"] = fetch_organizations_by_location(
            df_orgs, df_states, df_countries, window_start, window_end
        )
    except Exception as e:
        print(f"{label} organizations_by_location failed: {e}")


def lambda_handler(event, context):
    event = event or {}
    response_body = get_default_response()

    try:
        growth_start, growth_end = validate_date_pair(
            event.get("start_date"), event.get("end_date"), "start_date", "end_date"
        )
        location_start, location_end = validate_date_pair(
            event.get("location_start_date"),
            event.get("location_end_date"),
            "location_start_date",
            "location_end_date",
        )
    except InvalidFilterError as e:
        return build_response(400, {"error": str(e)})

    try:
        df_orgs, df_states, df_countries = load_data()
    except Exception as e:
        print(f"Failed to load mock data: {e}")
        return build_response(200, response_body)

    for bucket in ["7D", "30D", "1Y", "All"]:
        window_start, window_end = get_fixed_window(bucket)
        _run_bucket(bucket, response_body, df_orgs, df_states, df_countries, window_start, window_end)

    # Custom: growth_trend and organizations_by_location are driven by
    # independent parameter pairs and populate independently.
    try:
        response_body["Custom"]["growth_trend"] = fetch_growth_trend(
            df_orgs, growth_start, growth_end, BUCKET_GRANULARITY["Custom"]
        )
    except Exception as e:
        print(f"Custom growth_trend failed: {e}")

    try:
        response_body["Custom"]["organizations_by_location"] = fetch_organizations_by_location(
            df_orgs, df_states, df_countries, location_start, location_end
        )
    except Exception as e:
        print(f"Custom organizations_by_location failed: {e}")

    return build_response(200, response_body)


if __name__ == "__main__":
    scenarios = [
        ("No body", {}),
        ("Growth-range only (Custom.growth_trend populated)", {
            "start_date": "2026-01-01", "end_date": "2026-06-30",
        }),
        ("Location-range only (Custom.organizations_by_location populated)", {
            "location_start_date": "2025-01-01", "location_end_date": "2025-12-31",
        }),
        ("Both ranges (Custom fully populated)", {
            "start_date": "2026-01-01", "end_date": "2026-06-30",
            "location_start_date": "2025-01-01", "location_end_date": "2025-12-31",
        }),
        ("Invalid: start_date after end_date -> 400", {
            "start_date": "2026-06-30", "end_date": "2026-01-01",
        }),
    ]

    for title, event in scenarios:
        print(f"\n=== {title} ===")
        print(f"event: {json.dumps(event)}")
        result = lambda_handler(event, None)
        print(f"statusCode: {result['statusCode']}")
        print(result["body"])
