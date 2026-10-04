import json
import os
from datetime import datetime, timedelta
import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None

MOCK_DATA_DIR = os.path.join(os.path.dirname(__file__), "mock_data")


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
        return now - timedelta(days=6), now
    elif bucket == "30D":
        return now - timedelta(days=29), now
    elif bucket == "1Y":
        return now.replace(year=now.year - 1) + timedelta(days=1), now
    elif bucket == "All":
        return None, now
    else:
        raise ValueError(f"get_bucket_range doesn't handle bucket: {bucket}")


def apply_filters(df, country=None):
    filtered = df
    if country is not None and country != "ALL":
        filtered = filtered[filtered["country_code"] == country]
    return filtered

def compute_rating_distribution(df, window_start, window_end):
    windowed = df[df["created_at"] <= window_end]
    if window_start is not None:
        windowed = windowed[windowed["created_at"] >= window_start]

    counts = windowed.groupby("org_rating").size().sort_index()
    return [{"rating": int(r), "count": int(c)} for r, c in counts.items()]

def compute_organization_mix_trend(df, window_start, window_end, granularity):
    period_format = "%Y-%m-%d" if granularity == "day" else "%Y-%m"

    all_time = df[df["created_at"] <= window_end].copy()
    all_time["period"] = all_time["created_at"].dt.strftime(period_format)
    all_time_sorted = all_time.sort_values("created_at")

    windowed = all_time
    if window_start is not None:
        windowed = all_time[all_time["created_at"] >= window_start]

    result = {}
    for org_type in ["non_profit", "for_profit"]:
        periods_in_window = sorted(
            windowed[windowed["org_type"] == org_type]["period"].unique()
        )
        type_all_time = all_time_sorted[all_time_sorted["org_type"] == org_type]
        series = []
        for period in periods_in_window:
            running_total = (type_all_time["period"] <= period).sum()
            series.append({"period": period, "count": int(running_total)})
        result[org_type] = series

    return result

def parse_date_or_error(date_str, field_name):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d"), None
    except (ValueError, TypeError):
        return None, f"Invalid date format for {field_name}: {date_str}"


def validate_date_range(start_str, end_str, start_field, end_field):
    if start_str is None and end_str is None:
        return None, None, None
    if start_str is None:
        return None, None, f"{start_field} is required when {end_field} is provided"
    if end_str is None:
        return None, None, f"{end_field} is required when {start_field} is provided"

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
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(body)
    }


def build_bucket(df, window_start, window_end, granularity):
    return {
        "rating_distribution": compute_rating_distribution(df, window_start, window_end),
        "organization_mix_trend": compute_organization_mix_trend(df, window_start, window_end, granularity),
    }


BUCKET_GRANULARITY = {"7D": "day", "30D": "day", "1Y": "month", "All": "month", "Custom": "day"}


def lambda_handler(event, context):
    df = load_data()
    df = apply_filters(df, event.get("country"))

    rating_start, rating_end, rating_err = validate_date_range(
        event.get("rating_start_date"), event.get("rating_end_date"),
        "rating_start_date", "rating_end_date"
    )
    if rating_err:
        return build_response(400, {"error": rating_err})

    type_start, type_end, type_err = validate_date_range(
        event.get("type_start_date"), event.get("type_end_date"),
        "type_start_date", "type_end_date"
    )
    if type_err:
        return build_response(400, {"error": type_err})

    custom_requested = rating_start is not None or type_start is not None

    if custom_requested:
        rating_dist = []
        if rating_start is not None:
            rating_dist = compute_rating_distribution(df, rating_start, rating_end)

        mix_trend = {"non_profit": [], "for_profit": []}
        if type_start is not None:
            mix_trend = compute_organization_mix_trend(df, type_start, type_end, "day")

        return build_response(200, {
            "Custom": {
                "rating_distribution": rating_dist,
                "organization_mix_trend": mix_trend,
            }
        })

    response_body = {}
    for bucket in ["7D", "30D", "1Y", "All"]:
        window_start, window_end = get_bucket_range(bucket)
        response_body[bucket] = build_bucket(df, window_start, window_end, BUCKET_GRANULARITY[bucket])

    response_body["Custom"] = {
        "rating_distribution": [],
        "organization_mix_trend": {"non_profit": [], "for_profit": []},
    }

    return build_response(200, response_body)


if __name__ == "__main__":
    print("=== Test 1: Empty body ===")
    result = lambda_handler({}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))

    print("\n=== Test 2: Country filter only ===")
    result = lambda_handler({"country": "USA"}, None)
    body = json.loads(result["body"])
    print(json.dumps(body["All"], indent=2))

    print("\n=== Test 3: Rating range only (Custom mode) ===")
    result = lambda_handler({"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))

    print("\n=== Test 4: Type range only (Custom mode) ===")
    result = lambda_handler({"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))

    print("\n=== Test 5: Both ranges (Custom mode) ===")
    result = lambda_handler({
        "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30",
        "type_start_date": "2025-01-01", "type_end_date": "2025-12-31"
    }, None)
    print(json.dumps(json.loads(result["body"]), indent=2))

    print("\n=== Test 6: Invalid date range (should be 400) ===")
    result = lambda_handler({"rating_start_date": "2026-06-30", "rating_end_date": "2026-01-01"}, None)
    print(result["statusCode"], result["body"])

    print("\n=== Test 7: Only one half of a pair provided (should be 400) ===")
    result = lambda_handler({"type_start_date": "2026-01-01"}, None)
    print(result["statusCode"], result["body"])