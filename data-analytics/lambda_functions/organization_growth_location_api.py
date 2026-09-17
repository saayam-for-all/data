import os
import json
from datetime import datetime, timedelta
import pandas as pd

# Path for local testing with mock CSVs
MOCK_DATA_DIR = os.getenv("MOCK_DATA_DIR", "../mock-data-generation")
# ==========================================
# 1. HELPER FUNCTIONS & DATE VALIDATION
# ==========================================
def parse_date(date_str):
    """Safely parse YYYY-MM-DD date strings."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None

def validate_date_range(start_str, end_str):
    """Validate independent custom start and end dates."""
    if not start_str and not end_str:
        return None, None, None
    if bool(start_str) != bool(end_str):
        return None, None, "Both start_date and end_date must be provided together."
    
    start_d = parse_date(start_str)
    end_d = parse_date(end_str)
    
    if not start_d or not end_d:
        return None, None, "Invalid date format. Use YYYY-MM-DD."
    if start_d > end_d:
        return None, None, "start_date cannot be after end_date."
        
    return start_d, end_d, None

# ==========================================
# 2. DATA INGESTION & RELATIONAL JOIN
# ==========================================
def load_joined_data(mock_dir):
    """Load local CSVs and join organizations -> states -> countries."""
    orgs_df = pd.read_csv(os.path.join(mock_dir, "organizations.csv"))
    states_df = pd.read_csv(os.path.join(mock_dir, "states.csv"))
    countries_df = pd.read_csv(os.path.join(mock_dir, "countries.csv"))

    # Clean date strings
    orgs_df['created_at'] = pd.to_datetime(orgs_df['created_at'])
    orgs_df['created_date'] = orgs_df['created_at'].dt.date

    # Relational joins: orgs -> states -> countries
    merged = orgs_df.merge(states_df, on="state_id", how="left")
    merged = merged.merge(countries_df, on="country_id", how="left")
    
    # Standardize country code column name
    if 'country_code' not in merged.columns and 'code' in merged.columns:
        merged['country_code'] = merged['code']
    elif 'country_code' not in merged.columns:
        merged['country_code'] = 'USA'

    merged['country_code'] = merged['country_code'].fillna('USA')

    # Safely handle missing or differently named collaborator flag
    if 'is_collaborator' not in merged.columns:
        if 'collaborator' in merged.columns:
            merged['is_collaborator'] = merged['collaborator']
        else:
            # Default fallback if column does not exist in CSV
            merged['is_collaborator'] = False

    merged['is_collaborator'] = merged['is_collaborator'].astype(bool)
    
    return merged

# ==========================================
# 3. GROWTH TREND AGGREGATION ENGINE
# ==========================================
def calculate_growth_trend(df, start_date=None, end_date=None, granularity="month"):
    """
    Computes total_organizations (all-time running total) 
    and collaborators (window-scoped per-period count).
    """
    window_df = df.copy()
    if start_date and end_date:
        window_df = window_df[(window_df['created_date'] >= start_date) & (window_df['created_date'] <= end_date)]
    
    if window_df.empty:
        return {"total_organizations": [], "collaborators": []}

    # Assign period labels based on granularity
    if granularity == "day":
        window_df['period'] = window_df['created_at'].dt.strftime('%Y-%m-%d')
        df['period_ref'] = df['created_at'].dt.strftime('%Y-%m-%d')
    else:
        window_df['period'] = window_df['created_at'].dt.strftime('%Y-%m')
        df['period_ref'] = df['created_at'].dt.strftime('%Y-%m')

    periods = sorted(window_df['period'].unique())
    total_orgs_list = []
    collabs_list = []

    for p in periods:
        # All-time running total up to this period end (never resets per bucket)
        cum_count = len(df[df['period_ref'] <= p])
        
        # Window-scoped collaborators count for this specific period
        collab_count = len(window_df[(window_df['period'] == p) & (window_df['is_collaborator'] == True)])
        
        total_orgs_list.append({"period": p, "count": cum_count})
        collabs_list.append({"period": p, "count": collab_count})

    return {
        "total_organizations": total_orgs_list,
        "collaborators": collabs_list
    }

# ==========================================
# 4. LOCATION AGGREGATION ENGINE
# ==========================================
def calculate_location_breakdown(df, start_date=None, end_date=None):
    """Returns top 4 countries by count for the window."""
    window_df = df.copy()
    if start_date and end_date:
        window_df = window_df[(window_df['created_date'] >= start_date) & (window_df['created_date'] <= end_date)]

    if window_df.empty:
        return []

    loc_counts = window_df.groupby('country_code').size().reset_index(name='count')
    loc_counts = loc_counts.sort_values(by='count', ascending=False).head(4)

    result = []
    for _, row in loc_counts.iterrows():
        result.append({
            "country": row['country_code'],
            "count": int(row['count'])
        })
    return result

# ==========================================
# 5. MAIN LAMBDA HANDLER
# ==========================================
def lambda_handler(event, context=None):
    payload = event if isinstance(event, dict) else json.loads(event or "{}")

    # Validate custom date range parameters independently
    gt_start, gt_end, gt_err = validate_date_range(payload.get("start_date"), payload.get("end_date"))
    if gt_err:
        return {"statusCode": 400, "body": json.dumps({"error": gt_err})}

    loc_start, loc_end, loc_err = validate_date_range(payload.get("location_start_date"), payload.get("location_end_date"))
    if loc_err:
        return {"statusCode": 400, "body": json.dumps({"error": loc_err})}

    # Load and join relational tables
    df = load_joined_data(MOCK_DATA_DIR)
    
    # Use standard fixed dates or derive relative windows
    today = datetime.now().date()

    buckets_config = {
        "7D": {"start": today - timedelta(days=7), "end": today, "granularity": "day"},
        "30D": {"start": today - timedelta(days=30), "end": today, "granularity": "day"},
        "1Y": {"start": today - timedelta(days=365), "end": today, "granularity": "month"},
        "All": {"start": None, "end": None, "granularity": "month"}
    }

    response = {}

    # Compute standard time buckets
    for bucket_name, config in buckets_config.items():
        response[bucket_name] = {
            "growth_trend": calculate_growth_trend(df, config["start"], config["end"], config["granularity"]),
            "organizations_by_location": calculate_location_breakdown(df, config["start"], config["end"])
        }

    # Compute Custom time bucket independently
    response["Custom"] = {
        "growth_trend": calculate_growth_trend(df, gt_start, gt_end, "day") if (gt_start and gt_end) else {"total_organizations": [], "collaborators": []},
        "organizations_by_location": calculate_location_breakdown(df, loc_start, loc_end) if (loc_start and loc_end) else []
    }

    return {
        "statusCode": 200,
        "body": json.dumps(response, indent=2)
    }

# ==========================================
# 6. LOCAL TEST EXECUTION BLOCK
# ==========================================
if __name__ == "__main__":
    print("--- Running Local Verification ---")
    
    # Test 1: Empty event
    print("\n1. Standard Run (No Params):")
    res1 = lambda_handler({})
    print("Status Code:", res1["statusCode"])
    print("Payload Sample (Keys):", list(json.loads(res1["body"]).keys()))

    # Test 2: Custom dates test
    print("\n2. Custom Date Range Test:")
    res2 = lambda_handler({"start_date": "2026-01-01", "end_date": "2026-06-30"})
    print("Custom Bucket Growth Trend Output:")
    print(json.loads(res2["body"])["Custom"]["growth_trend"])

    # Test 3: Invalid Range Error Test
    print("\n3. Invalid Date Validation Test:")
    res3 = lambda_handler({"start_date": "2026-06-30", "end_date": "2026-01-01"})
    print("Status Code:", res3["statusCode"])
    print("Body:", res3["body"])