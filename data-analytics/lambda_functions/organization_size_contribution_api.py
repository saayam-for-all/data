import os
import json
from datetime import datetime, date, timedelta
import pandas as pd

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "true").lower() == "true"
# Mock data path relative to repo structure or fallback local paths
MOCK_DATA_DIR = os.environ.get(
    "MOCK_DATA_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../mock-data-generation"))
)
if not os.path.exists(MOCK_DATA_DIR):
    MOCK_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))


def parse_date(date_str):
    """Parses standard YYYY-MM-DD date strings."""
    if not date_str:
        return None
    try:
        return datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Expected YYYY-MM-DD.")


def validate_date_pair(start_key, end_key, params):
    """Validates presence and ordering of a date range pair."""
    has_start = start_key in params and params[start_key] is not None and str(params[start_key]).strip() != ""
    has_end = end_key in params and params[end_key] is not None and str(params[end_key]).strip() != ""

    if has_start != has_end:
        raise ValueError(f"Both '{start_key}' and '{end_key}' must be provided together.")

    if not has_start and not has_end:
        return None, None

    start_d = parse_date(params[start_key])
    end_d = parse_date(params[end_key])

    if start_d > end_d:
        raise ValueError(f"'{start_key}' cannot be after '{end_key}'.")

    return start_d, end_d


def load_joined_data(mock_dir):
    """Load local CSV datasets and join organizations -> states -> countries."""
    orgs_path = os.path.join(mock_dir, "organizations.csv")
    states_path = os.path.join(mock_dir, "states.csv")
    countries_path = os.path.join(mock_dir, "countries.csv")

    if not os.path.exists(orgs_path):
        # Return empty structure matching columns if CSV missing or empty
        return pd.DataFrame(columns=[
            'org_id', 'org_size', 'is_collaborator', 'is_contributor', 
            'org_type', 'state_id', 'created_at', 'created_date', 
            'country_id', 'country_code', 'country_name'
        ])

    orgs_df = pd.read_csv(orgs_path)
    if orgs_df.empty:
        return pd.DataFrame(columns=[
            'org_id', 'org_size', 'is_collaborator', 'is_contributor', 
            'org_type', 'state_id', 'created_at', 'created_date', 
            'country_id', 'country_code', 'country_name'
        ])

    # Clean dates
    orgs_df['created_at'] = pd.to_datetime(orgs_df['created_at'])
    orgs_df['created_date'] = orgs_df['created_at'].dt.date

    # Ensure required columns exist with safe fallbacks
    if 'is_collaborator' not in orgs_df.columns:
        orgs_df['is_collaborator'] = False
    else:
        orgs_df['is_collaborator'] = orgs_df['is_collaborator'].fillna(False).astype(bool)

    if 'is_contributor' not in orgs_df.columns:
        orgs_df['is_contributor'] = False
    else:
        orgs_df['is_contributor'] = orgs_df['is_contributor'].fillna(False).astype(bool)

    if 'org_size' not in orgs_df.columns:
        orgs_df['org_size'] = 'small'
        
    if 'org_type' not in orgs_df.columns:
        orgs_df['org_type'] = 'non_profit'

    # Join states & countries if available
    states_df = pd.read_csv(states_path) if os.path.exists(states_path) else pd.DataFrame()
    countries_df = pd.read_csv(countries_path) if os.path.exists(countries_path) else pd.DataFrame()

    merged = orgs_df
    if not states_df.empty and 'state_id' in merged.columns and 'state_id' in states_df.columns:
        merged = merged.merge(states_df, on="state_id", how="left")

    if not countries_df.empty and 'country_id' in merged.columns and 'country_id' in countries_df.columns:
        merged = merged.merge(countries_df, on="country_id", how="left")

    if 'country_code' not in merged.columns:
        if 'code' in merged.columns:
            merged['country_code'] = merged['code']
        else:
            merged['country_code'] = 'USA'

    if 'country_name' not in merged.columns:
        merged['country_name'] = merged['country_code']

    merged['country_code'] = merged['country_code'].fillna('USA')
    merged['country_name'] = merged['country_name'].fillna('USA')

    return merged


def apply_global_filters(df, country_filter, org_type_filter):
    """Filters dataframe by country code/name and organization type."""
    filtered = df.copy()

    if country_filter and str(country_filter).upper() != 'ALL':
        val = str(country_filter).strip().lower()
        c_code_match = filtered['country_code'].astype(str).str.lower() == val
        c_name_match = filtered['country_name'].astype(str).str.lower() == val
        filtered = filtered[c_code_match | c_name_match]

    if org_type_filter and str(org_type_filter).upper() != 'ALL':
        val = str(org_type_filter).strip().lower()
        filtered = filtered[filtered['org_type'].astype(str).str.lower() == val]

    return filtered


def compute_organizations_by_size(df):
    """Computes org count grouped by size enum present in the filtered dataset."""
    if df.empty or 'org_size' not in df.columns:
        return []

    counts = df['org_size'].value_counts()
    result = []
    # Emit categories as they appear in data
    for size_cat, count in counts.items():
        result.append({
            "size": str(size_cat),
            "count": int(count)
        })
    return result


def compute_collaborator_vs_contributor(df):
    """
    Computes independent counts for Collaborator and Contributor.
    Does not partition; an org can be both or neither.
    """
    total_orgs = len(df)
    if total_orgs == 0:
        return [
            {"type": "Collaborator", "count": 0, "percentage": 0.0},
            {"type": "Contributor", "count": 0, "percentage": 0.0}
        ]

    collab_count = int(df['is_collaborator'].sum()) if 'is_collaborator' in df.columns else 0
    contrib_count = int(df['is_contributor'].sum()) if 'is_contributor' in df.columns else 0

    collab_pct = round((collab_count / total_orgs) * 100, 1)
    contrib_pct = round((contrib_count / total_orgs) * 100, 1)

    return [
        {"type": "Collaborator", "count": collab_count, "percentage": collab_pct},
        {"type": "Contributor", "count": contrib_count, "percentage": contrib_pct}
    ]


def build_bucket_metrics(df_window):
    """Builds the exact 2 sub-charts for a specific window dataframe."""
    return {
        "organizations_by_size": compute_organizations_by_size(df_window),
        "collaborator_vs_contributor": compute_collaborator_vs_contributor(df_window)
    }


def lambda_handler(event, context=None):
    """Lambda entry point for Size & Contribution Analytics API."""
    params = event or {}
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except Exception:
            params = {}

    # Extract filters
    country_filter = params.get("country", "ALL")
    org_type_filter = params.get("organization_type", "ALL")

    # Validate date ranges
    try:
        size_start, size_end = validate_date_pair("size_start_date", "size_end_date", params)
        contrib_start, contrib_end = validate_date_pair("contribution_start_date", "contribution_end_date", params)
    except ValueError as e:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": str(e)})
        }

    # Load data
    df = load_joined_data(MOCK_DATA_DIR)

    # Apply global filters (country & org_type)
    df_filtered = apply_global_filters(df, country_filter, org_type_filter)

    has_size_custom = size_start is not None and size_end is not None
    has_contrib_custom = contrib_start is not None and contrib_end is not None

    # CUSTOM-ONLY RESPONSE SHAPE
    if has_size_custom or has_contrib_custom:
        custom_size_data = []
        custom_contrib_data = []

        if has_size_custom:
            df_size_win = df_filtered[
                (df_filtered['created_date'] >= size_start) & 
                (df_filtered['created_date'] <= size_end)
            ]
            custom_size_data = compute_organizations_by_size(df_size_win)

        if has_contrib_custom:
            df_contrib_win = df_filtered[
                (df_filtered['created_date'] >= contrib_start) & 
                (df_filtered['created_date'] <= contrib_end)
            ]
            custom_contrib_data = compute_collaborator_vs_contributor(df_contrib_win)

        response_payload = {
            "Custom": {
                "organizations_by_size": custom_size_data,
                "collaborator_vs_contributor": custom_contrib_data
            }
        }
        return {
            "statusCode": 200,
            "body": json.dumps(response_payload)
        }

    # FIXED BUCKETS + EMPTY CUSTOM RESPONSE SHAPE
    today = date.today()
    
    # 7D Window
    d7_start = today - timedelta(days=7)
    df_7d = df_filtered[df_filtered['created_date'] >= d7_start]

    # 30D Window
    d30_start = today - timedelta(days=30)
    df_30d = df_filtered[df_filtered['created_date'] >= d30_start]

    # 1Y Window
    d1y_start = today - timedelta(days=365)
    df_1y = df_filtered[df_filtered['created_date'] >= d1y_start]

    # All Window
    df_all = df_filtered

    response_payload = {
        "7D": build_bucket_metrics(df_7d),
        "30D": build_bucket_metrics(df_30d),
        "1Y": build_bucket_metrics(df_1y),
        "All": build_bucket_metrics(df_all),
        "Custom": {
            "organizations_by_size": [],
            "collaborator_vs_contributor": []
        }
    }

    return {
        "statusCode": 200,
        "body": json.dumps(response_payload)
    }


# Local Verification Harness
if __name__ == "__main__":
    print("--- Local Verification: Size & Contribution Analytics API ---\n")

    # Test 1: No body ({})
    res1 = lambda_handler({})
    body1 = json.loads(res1["body"])
    print("1. Standard Run (No Params):")
    print("   Status Code:", res1["statusCode"])
    print("   Top-level Keys:", list(body1.keys()))

    # Test 2: Only size_start_date / size_end_date
    res2 = lambda_handler({"size_start_date": "2025-01-01", "size_end_date": "2026-12-31"})
    body2 = json.loads(res2["body"])
    print("\n2. Size Custom Range Only:")
    print("   Top-level Keys:", list(body2.keys()))
    print("   Custom Content:", body2.get("Custom"))

    # Test 3: Only contribution_start_date / contribution_end_date
    res3 = lambda_handler({"contribution_start_date": "2025-01-01", "contribution_end_date": "2026-12-31"})
    body3 = json.loads(res3["body"])
    print("\n3. Contribution Custom Range Only:")
    print("   Top-level Keys:", list(body3.keys()))
    print("   Custom Content:", body3.get("Custom"))

    # Test 4: Both Custom Ranges Together
    res4 = lambda_handler({
        "size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
        "contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"
    })
    body4 = json.loads(res4["body"])
    print("\n4. Both Custom Ranges Together:")
    print("   Top-level Keys:", list(body4.keys()))
    print("   Custom Content:", body4.get("Custom"))

    # Test 5: Validation Error (start > end)
    res5 = lambda_handler({"size_start_date": "2026-06-30", "size_end_date": "2026-01-01"})
    print("\n5. Invalid Date Validation Test:")
    print("   Status Code:", res5["statusCode"])
    print("   Body:", res5["body"])