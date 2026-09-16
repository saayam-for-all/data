

import json
import os

import pandas as pd


DEFAULT_MOCK_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sql"
)

BOOL_MAP = {"TRUE": True, "FALSE": False, True: True, False: False}

DATE_FORMAT = "%Y-%m-%d"


def get_mock_data_dir():
    return os.environ.get("MOCK_DATA_DIR", DEFAULT_MOCK_DATA_DIR)


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": body,
    }



# Data loading / joining


def load_data(mock_data_dir):
    orgs = pd.read_csv(os.path.join(mock_data_dir, "organizations.csv"))
    states = pd.read_csv(os.path.join(mock_data_dir, "states.csv"))
    countries = pd.read_csv(os.path.join(mock_data_dir, "countries.csv"))

    orgs["created_at"] = pd.to_datetime(orgs["created_at"], errors="coerce")
    orgs["is_collaborator"] = orgs["is_collaborator"].map(BOOL_MAP).fillna(False)

    return orgs, states, countries


def attach_country(orgs, states, countries):
    """organizations.state_id -> states.country_id -> countries.country_code"""
    merged = orgs.merge(
        states[["state_id", "country_id"]], on="state_id", how="left"
    )
    merged = merged.merge(
        countries[["country_id", "country_code"]], on="country_id", how="left"
    )
    return merged



# Date parsing / validation


def parse_date_pair(params, start_key, end_key):
    """Returns (start_inclusive, end_exclusive) as Timestamps, or None if
    neither param was supplied. Raises ValueError (-> 400) on bad input.
    """
    start_raw = params.get(start_key)
    end_raw = params.get(end_key)

    if start_raw is None and end_raw is None:
        return None
    if start_raw is None or end_raw is None:
        raise ValueError(f"Both {start_key} and {end_key} must be provided together")

    try:
        start = pd.to_datetime(start_raw, format=DATE_FORMAT)
        end = pd.to_datetime(end_raw, format=DATE_FORMAT)
    except (ValueError, TypeError):
        raise ValueError(
            f"Invalid date format for {start_key}/{end_key}; expected YYYY-MM-DD"
        )

    if start > end:
        raise ValueError(f"{start_key} must not be after {end_key}")

    # end is inclusive of the given calendar date -> exclusive upper bound
    return start, end + pd.Timedelta(days=1)



# Window / period helpers


def filter_window(df, start, end, col="created_at"):
    """start inclusive, end exclusive. Either may be None (unbounded)."""
    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= df[col] >= start
    if end is not None:
        mask &= df[col] < end
    return df[mask]


def period_key(series, granularity):
    if granularity == "day":
        return series.dt.strftime("%Y-%m-%d")
    return series.dt.strftime("%Y-%m")  # month


def period_upper_bound(period, granularity):
    """Exclusive upper-bound timestamp for a period label."""
    if granularity == "day":
        start_ts = pd.Timestamp(period)
        return start_ts + pd.Timedelta(days=1)
    start_ts = pd.Timestamp(period + "-01")
    return start_ts + pd.DateOffset(months=1)


def get_fixed_windows():
    """(start_inclusive, end_exclusive, granularity) for each fixed bucket.
    All = no window at all (entire dataset)."""
    now = pd.Timestamp.now()
    return {
        "7D": (now - pd.Timedelta(days=7), now, "day"),
        "30D": (now - pd.Timedelta(days=30), now, "day"),
        "1Y": (now - pd.DateOffset(years=1), now, "month"),
        "All": (None, None, "month"),
    }



# Chart computations


def compute_growth_trend(full_df, start, end, granularity):
    """total_organizations: cumulative, all-time, as of each period.
    collaborators: per-period count, scoped to this window only.
    Both series share the same (sparse) set of periods.
    """
    window_df = filter_window(full_df, start, end)
    if window_df.empty:
        return {"total_organizations": [], "collaborators": []}

    work = window_df.copy()
    work["period"] = period_key(work["created_at"], granularity)
    periods = sorted(work["period"].unique())

    total_series = []
    collaborators_series = []
    for period in periods:
        upper_bound = period_upper_bound(period, granularity)
        total_count = int((full_df["created_at"] < upper_bound).sum())
        total_series.append({"period": period, "count": total_count})

        collab_count = int(
            ((work["period"] == period) & work["is_collaborator"]).sum()
        )
        collaborators_series.append({"period": period, "count": collab_count})

    return {
        "total_organizations": total_series,
        "collaborators": collaborators_series,
    }


def compute_locations(df, start, end):
    """Top 4 countries by count, window-scoped. No 'Other', no percentage."""
    window_df = filter_window(df, start, end)
    if window_df.empty:
        return []

    counts = (
        window_df.groupby("country_code").size().sort_values(ascending=False)
    )
    top = counts.head(4)
    return [{"country": country, "count": int(count)} for country, count in top.items()]


def build_bucket(df, start, end, granularity):
    return {
        "growth_trend": compute_growth_trend(df, start, end, granularity),
        "organizations_by_location": compute_locations(df, start, end),
    }



# Handler


def build_analytics(df, params):
    try:
        growth_range = parse_date_pair(params, "start_date", "end_date")
        location_range = parse_date_pair(
            params, "location_start_date", "location_end_date"
        )
    except ValueError as e:
        return None, str(e)

    response = {}
    for bucket_name, (start, end, granularity) in get_fixed_windows().items():
        response[bucket_name] = build_bucket(df, start, end, granularity)

    if growth_range:
        custom_growth = compute_growth_trend(df, growth_range[0], growth_range[1], "day")
    else:
        custom_growth = {"total_organizations": [], "collaborators": []}

    if location_range:
        custom_locations = compute_locations(df, location_range[0], location_range[1])
    else:
        custom_locations = []

    response["Custom"] = {
        "growth_trend": custom_growth,
        "organizations_by_location": custom_locations,
    }

    return response, None


def lambda_handler(event, context):
    params = event
    if isinstance(event.get("body"), str):
        params = json.loads(event["body"])

    try:
        orgs, states, countries = load_data(get_mock_data_dir())
        df = attach_country(orgs, states, countries)
    except Exception as e:  # noqa: BLE001
        print(f"growth_location_analytics failed to load data: {e}")
        return build_response(500, {"error": "failed to load data"})

    response, error = build_analytics(df, params)
    if error:
        return build_response(400, {"error": error})

    return build_response(200, response)


if __name__ == "__main__":
    sample_events = {
        "no body": {},
        "growth range only": {
            "body": json.dumps({"start_date": "2026-01-01", "end_date": "2026-06-30"})
        },
        "location range only": {
            "body": json.dumps(
                {"location_start_date": "2025-06-01", "location_end_date": "2025-12-31"}
            )
        },
        "both ranges": {
            "body": json.dumps(
                {
                    "start_date": "2026-01-01",
                    "end_date": "2026-06-30",
                    "location_start_date": "2025-06-01",
                    "location_end_date": "2025-12-31",
                }
            )
        },
        "invalid date": {"body": json.dumps({"start_date": "not-a-date", "end_date": "2026-06-30"})},
        "start after end": {
            "body": json.dumps({"start_date": "2026-06-30", "end_date": "2026-01-01"})
        },
    }

    for label, event in sample_events.items():
        print(f"\n=== {label} ===")
        print(json.dumps(lambda_handler(event, None), indent=2, default=str))
