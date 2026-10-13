import pandas as pd
import json
import os
from datetime import datetime, timedelta

# psycopg2 is only needed for the real Postgres path — optional so this file
# still runs standalone with mock CSV data when it isn't installed.
try:
    import psycopg2
except ImportError:
    psycopg2 = None

USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "true").lower() == "true"
MOCK_DATA_DIR = os.environ.get("MOCK_DATA_DIR", ".")


# ---------------- Data loading ----------------
def load_data():
    df_countries = pd.read_csv(os.path.join(MOCK_DATA_DIR, "countries.csv"))
    df_organizations = pd.read_csv(os.path.join(MOCK_DATA_DIR, "organizations.csv"))
    df_states = pd.read_csv(os.path.join(MOCK_DATA_DIR, "states.csv"))

    merged = df_organizations.merge(df_states, on="state_id", how="left")
    merged = merged.merge(df_countries, on="country_id", how="left")
    merged["created_at"] = pd.to_datetime(merged["created_at"])
    return merged


# ---------------- Chart builders ----------------
def organizations_by_size(df):
    counts = df["org_size"].value_counts()
    return [{"size": size, "count": int(count)} for size, count in counts.items()]


def collaborator_vs_contributor(df):
    total = len(df)
    collaborators = int((df["is_collaborator"] == True).sum()) if "is_collaborator" in df.columns else 0
    contributors = int((df["is_contributor"] == True).sum()) if "is_contributor" in df.columns else 0
    collaborators_pct = round((collaborators / total) * 100, 1) if total > 0 else 0
    contributors_pct = round((contributors / total) * 100, 1) if total > 0 else 0
    return [
        {"type": "Collaborator", "count": collaborators, "percentage": float(collaborators_pct)},
        {"type": "Contributor", "count": contributors, "percentage": float(contributors_pct)},
    ]


# ---------------- Filters ----------------
def filter_by_country(df, country):
    if not country or str(country).upper() == "ALL":
        return df
    country = str(country).lower()
    return df[
        (df["country_name"].str.lower() == country) |
        (df["country_code"].str.lower() == country)
    ]


def filter_by_org_type(df, org_type):
    if not org_type or str(org_type).upper() == "ALL":
        return df
    return df[df["org_type"].str.lower() == str(org_type).lower()]


def filter_by_date_range(df, start_date, end_date):
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    return df[(df["created_at"] >= start) & (df["created_at"] <= end)]


# ---------------- Date validation ----------------
def validate_date_pair(start_date, end_date):
    if start_date is None and end_date is None:
        return None
    if start_date is None or end_date is None:
        return "Both start and end date must be provided together."
    try:
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
    except Exception:
        return "Invalid date format. Use YYYY-MM-DD."
    if start > end:
        return "start_date must be before or equal to end_date."
    return None


# ---------------- Fixed bucket ranges ----------------
def get_bucket_range(bucket, df):
    now = datetime.now()
    if bucket == "7D":
        return now - timedelta(days=7), now
    elif bucket == "30D":
        return now - timedelta(days=30), now
    elif bucket == "1Y":
        return now - timedelta(days=365), now
    elif bucket == "All":
        start = df["created_at"].min() if len(df) > 0 else now
        return start, now


def build_bucket(df, bucket_name):
    start, end = get_bucket_range(bucket_name, df)
    window = df[(df["created_at"] >= start) & (df["created_at"] <= end)]
    return {
        "organizations_by_size": organizations_by_size(window),
        "collaborator_vs_contributor": collaborator_vs_contributor(window),
    }


# ---------------- Main handler ----------------
def handler(event):
    merged = load_data()

    country = event.get("country", "ALL")
    org_type = event.get("organization_type", "ALL")
    size_start = event.get("size_start_date")
    size_end = event.get("size_end_date")
    contrib_start = event.get("contribution_start_date")
    contrib_end = event.get("contribution_end_date")

    size_error = validate_date_pair(size_start, size_end)
    if size_error:
        return {"error": size_error}

    contrib_error = validate_date_pair(contrib_start, contrib_end)
    if contrib_error:
        return {"error": contrib_error}

    filtered = filter_by_country(merged, country)
    filtered = filter_by_org_type(filtered, org_type)

    custom_mode = bool(size_start and size_end) or bool(contrib_start and contrib_end)

    if custom_mode:
        custom_result = {"organizations_by_size": [], "collaborator_vs_contributor": []}
        if size_start and size_end:
            size_window = filter_by_date_range(filtered, size_start, size_end)
            custom_result["organizations_by_size"] = organizations_by_size(size_window)
        if contrib_start and contrib_end:
            contrib_window = filter_by_date_range(filtered, contrib_start, contrib_end)
            custom_result["collaborator_vs_contributor"] = collaborator_vs_contributor(contrib_window)
        return {"Custom": custom_result}

    response = {}
    for bucket in ["7D", "30D", "1Y", "All"]:
        response[bucket] = build_bucket(filtered, bucket)
    response["Custom"] = {"organizations_by_size": [], "collaborator_vs_contributor": []}
    return response


# ---------------- Local test block ----------------
if __name__ == "__main__":
    test_cases = [
        ("No params", {}),
        ("Country filter", {"country": "India"}),
        ("Org type filter", {"organization_type": "non_profit"}),
        ("Size custom range only", {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"}),
        ("Contribution custom range only", {"contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"}),
        ("Both custom ranges together", {
            "size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
            "contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31",
        }),
        ("Malformed: missing end date", {"size_start_date": "2026-01-01"}),
        ("Malformed: start after end", {"size_start_date": "2026-06-30", "size_end_date": "2026-01-01"}),
    ]

    for label, event in test_cases:
        print(f"\n--- {label} ---")
        print(json.dumps(handler(event), indent=2, default=str))