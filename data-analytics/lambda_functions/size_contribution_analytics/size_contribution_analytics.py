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

def apply_filters(df, country=None, organization_type=None):
    filtered = df

    if country is not None:
        filtered = filtered[filtered["country_code"] == country]

    if organization_type is not None:
        filtered = filtered[filtered["org_type"] == organization_type]

    return filtered

def compute_organizations_by_size(df, window_start, window_end):
    windowed = df[df["created_at"] <= window_end]
    if window_start is not None:
        windowed = windowed[windowed["created_at"] >= window_start]

    counts = windowed.groupby("org_size").size()

    size_order = ["small", "medium", "large"]
    return [{"size": s, "count": int(counts.get(s, 0))} for s in size_order]

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

def compute_collaborator_vs_contributor(df, window_start, window_end):
    windowed = df[df["created_at"] <= window_end]
    if window_start is not None:
        windowed = windowed[windowed["created_at"] >= window_start]

    total = len(windowed)

    collaborators = int((windowed["is_collaborator"] == True).sum())
    if "is_contributor" in windowed.columns:
        contributors = int((windowed["is_contributor"] == True).sum())
    else:
        contributors = 0

    collaborator_pct = round((collaborators / total) * 100, 1) if total > 0 else 0
    contributor_pct = round((contributors / total) * 100, 1) if total > 0 else 0

    return {
        "collaborators": {"count": collaborators, "percentage": collaborator_pct},
        "contributors": {"count": contributors, "percentage": contributor_pct},
    }

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
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body)
    }


def build_bucket(df, window_start, window_end):
    return {
        "organizations_by_size": compute_organizations_by_size(df, window_start, window_end),
        "collaborator_vs_contributor": compute_collaborator_vs_contributor(df, window_start, window_end),
    }


def lambda_handler(event, context):
    df = load_data()
    df = apply_filters(df, event.get("country"), event.get("organization_type"))

    size_start, size_end, size_err = validate_date_range(
        event.get("size_start_date"), event.get("size_end_date"),
        "size_start_date", "size_end_date"
    )
    if size_err:
        return build_response(400, {"error": size_err})

    contrib_start, contrib_end, contrib_err = validate_date_range(
        event.get("contribution_start_date"), event.get("contribution_end_date"),
        "contribution_start_date", "contribution_end_date"
    )
    if contrib_err:
        return build_response(400, {"error": contrib_err})

    custom_requested = size_start is not None or contrib_start is not None

    if custom_requested:
        custom_size = {"organizations_by_size": [{"size": "small", "count": 0}, {"size": "medium", "count": 0}, {"size": "large", "count": 0}]}
        if size_start is not None:
            custom_size = {"organizations_by_size": compute_organizations_by_size(df, size_start, size_end)}

        custom_contrib = {"collaborator_vs_contributor": {
            "collaborators": {"count": 0, "percentage": 0},
            "contributors": {"count": 0, "percentage": 0},
        }}
        if contrib_start is not None:
            custom_contrib = {"collaborator_vs_contributor": compute_collaborator_vs_contributor(df, contrib_start, contrib_end)}

        return build_response(200, {
            "Custom": {
                **custom_size,
                **custom_contrib,
            }
        })

    response_body = {}
    for bucket in ["7D", "30D", "1Y", "All"]:
        window_start, window_end = get_bucket_range(bucket)
        response_body[bucket] = build_bucket(df, window_start, window_end)

    return build_response(200, response_body)


if __name__ == "__main__":
    print("=== Test 1: Empty body ===")
    result = lambda_handler({}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))

    print("\n=== Test 2: Country filter only ===")
    result = lambda_handler({"country": "USA"}, None)
    body = json.loads(result["body"])
    print(json.dumps(body["All"], indent=2))

    print("\n=== Test 3: Organization type filter only ===")
    result = lambda_handler({"organization_type": "non_profit"}, None)
    body = json.loads(result["body"])
    print(json.dumps(body["All"], indent=2))

    print("\n=== Test 4: Size range only (Custom mode) ===")
    result = lambda_handler({"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))

    print("\n=== Test 5: Contribution range only (Custom mode) ===")
    result = lambda_handler({"contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))

    print("\n=== Test 6: Both ranges (Custom mode) ===")
    result = lambda_handler({
        "size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
        "contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"
    }, None)
    print(json.dumps(json.loads(result["body"]), indent=2))

    print("\n=== Test 7: Invalid date range (should be 400) ===")
    result = lambda_handler({"size_start_date": "2026-06-30", "size_end_date": "2026-01-01"}, None)
    print(result["statusCode"], result["body"])

    print("\n=== Test 8: Only one half of a pair provided (should be 400) ===")
    result = lambda_handler({"contribution_start_date": "2026-01-01"}, None)
    print(result["statusCode"], result["body"])