import json
import os
from datetime import datetime, timedelta
import pandas as pd

MOCK_DATA_DIR = os.path.join(os.path.dirname(__file__), "mock_data")
BUCKET_GRANULARITY = {
    "7D": "day",
    "30D": "day",
    "1Y": "month",
    "All": "month",
    "Custom": "day",
}


def load_data():
    organizations = pd.read_csv(os.path.join(MOCK_DATA_DIR, "organizations.csv"))
    states = pd.read_csv(os.path.join(MOCK_DATA_DIR, "states.csv"))
    countries = pd.read_csv(os.path.join(MOCK_DATA_DIR, "countries.csv"))

    organizations["created_at"] = pd.to_datetime(organizations["created_at"])

    merged = organizations.merge(states, on="state_id", how="left")
    merged = merged.merge(countries, on="country_id", how="left")

    return merged

def get_bucket_range(bucket, now=None):
    if now is None:
        now = datetime.now()

    if bucket == "7D":
        return now - timedelta(days=7), now
    elif bucket == "30D":
        return now - timedelta(days=30), now
    elif bucket == "1Y":
        return now - timedelta(days=365), now
    elif bucket == "All":
        return None, now
    else:
        raise ValueError(f"get_bucket_range doesn't handle bucket: {bucket}")

def compute_growth_trend(df, window_start, window_end, granularity):
    if granularity == "day":
        period_format = "%Y-%m-%d"
    else:
        period_format = "%Y-%m"

    windowed = df[df["created_at"] <= window_end]
    if window_start is not None:
        windowed_for_collab = windowed[windowed["created_at"] >= window_start]
    else:
        windowed_for_collab = windowed

    all_time = df[df["created_at"] <= window_end].copy()
    all_time["period"] = all_time["created_at"].dt.strftime(period_format)
    periods_in_window = sorted(windowed_for_collab["created_at"].dt.strftime(period_format).unique())

    cumulative_counts = []
    running_total = 0
    all_time_sorted = all_time.sort_values("created_at")
    for period in periods_in_window:
        running_total = (all_time_sorted["period"] <= period).sum()
        cumulative_counts.append({"period": period, "count": int(running_total)})

    collab_df = windowed_for_collab[windowed_for_collab["is_collaborator"] == True].copy()
    collab_df["period"] = collab_df["created_at"].dt.strftime(period_format)
    collab_counts = collab_df.groupby("period").size()
    collaborators = [{"period": p, "count": int(collab_counts.get(p, 0))} for p in periods_in_window]
    return {
        "total_organizations": cumulative_counts,
        "collaborators": collaborators,
    }

def compute_organizations_by_location(df, window_start, window_end):
    windowed = df[df["created_at"] <= window_end]
    if window_start is not None:
        windowed = windowed[windowed["created_at"] >= window_start]

    counts = windowed.groupby("country_code").size().sort_values(ascending=False)
    top4 = counts.head(4)

    return [{"country": country, "count": int(count)} for country, count in top4.items()]

def parse_date_or_error(date_str, field_name):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d"), None
    except (ValueError, TypeError):
        return None, f"Invalid date format for {field_name}: {date_str}"


def validate_date_range(start_str, end_str, start_field, end_field):
    if start_str is None or end_str is None:
        return None, None, None

    start_dt, err = parse_date_or_error(start_str, start_field)
    if err:
        return None, None, err

    end_dt, err = parse_date_or_error(end_str, end_field)
    if err:
        return None, None, err

    if start_dt > end_dt:
        return None, None, f"{start_field} must be before {end_field}"

    return start_dt, end_dt, None

def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body)
    }


def build_bucket(df, bucket, window_start, window_end):
    granularity = BUCKET_GRANULARITY[bucket]
    growth_trend = compute_growth_trend(df, window_start, window_end, granularity)
    organizations_by_location = compute_organizations_by_location(df, window_start, window_end)
    return {
        "growth_trend": growth_trend,
        "organizations_by_location": organizations_by_location,
    }


def lambda_handler(event, context):
    df = load_data()

    response_body = {}

    for bucket in ["7D", "30D", "1Y", "All"]:
        window_start, window_end = get_bucket_range(bucket)
        response_body[bucket] = build_bucket(df, bucket, window_start, window_end)

    growth_start, growth_end, growth_err = validate_date_range(
        event.get("start_date"), event.get("end_date"), "start_date", "end_date"
    )
    if growth_err:
        return build_response(400, {"error": growth_err})

    loc_start, loc_end, loc_err = validate_date_range(
        event.get("location_start_date"), event.get("location_end_date"),
        "location_start_date", "location_end_date"
    )
    if loc_err:
        return build_response(400, {"error": loc_err})

    custom_growth_trend = {"total_organizations": [], "collaborators": []}
    if growth_start is not None:
        custom_growth_trend = compute_growth_trend(df, growth_start, growth_end, "day")

    custom_locations = []
    if loc_start is not None:
        custom_locations = compute_organizations_by_location(df, loc_start, loc_end)

    response_body["Custom"] = {
        "growth_trend": custom_growth_trend,
        "organizations_by_location": custom_locations,
    }

    return build_response(200, response_body)


if __name__ == "__main__":
    print("=== Test 1: Empty body ===")
    result = lambda_handler({}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))

    print("\n=== Test 2: Growth range only ===")
    result = lambda_handler({"start_date": "2026-01-01", "end_date": "2026-06-30"}, None)
    body = json.loads(result["body"])
    print(json.dumps(body["Custom"], indent=2))

    print("\n=== Test 3: Location range only ===")
    result = lambda_handler({"location_start_date": "2025-01-01", "location_end_date": "2025-12-31"}, None)
    body = json.loads(result["body"])
    print(json.dumps(body["Custom"], indent=2))

    print("\n=== Test 4: Both ranges ===")
    result = lambda_handler({
        "start_date": "2026-01-01", "end_date": "2026-06-30",
        "location_start_date": "2025-01-01", "location_end_date": "2025-12-31"
    }, None)
    body = json.loads(result["body"])
    print(json.dumps(body["Custom"], indent=2))

    print("\n=== Test 5: Invalid date range (should be 400) ===")
    result = lambda_handler({"start_date": "2026-06-30", "end_date": "2026-01-01"}, None)
    print(result["statusCode"], result["body"])