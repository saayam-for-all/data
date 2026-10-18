"""

Organization Analytics: Rating & Type API

The function generates the datasets for the Rating & Type tab of the 
Organization Analytics dashboard. It computes two primary charts:
1. Rating Distribution: A categorical breakdown of organizations by star rating (1-5).
2. Profit vs Non-Profit (Mix Trend): A cumulative, all-time running total of 
   organizations over time, split by for_profit and non_profit types.

Key Behaviors:
- Response Routing: If no custom dates are provided, it returns 4 fixed time 
  windows (7D, 30D, 1Y, All) and an empty Custom bucket. If custom dates are 
  provided, it returns ONLY the Custom bucket.
- Independent Custom Filters: The `rating` date pair and `type` date pair evaluate 
  completely independently to populate their respective sub-charts in the Custom bucket.
- Sparse Data Handling: The time-series chart omits periods with no new organizations 
  rather than zero-filling. The rating distribution similarly omits unrepresented ratings.
- Cumulative Logic: Mix trend counts are all-time running totals up to the end 
  of the requested window, formatted daily (7D/30D/Custom) or monthly (1Y/All).

"""

import os
import json
from datetime import datetime, timedelta, timezone
import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None

def validate_date_pair(start_date, end_date, pair_name):
    if not start_date and not end_date:
        return False
    if bool(start_date) != bool(end_date):
        raise ValueError(f"Incomplete date range for {pair_name}. Both start and end dates must be provided.")
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid date format in {pair_name}. Expected YYYY-MM-DD.")
    if start_dt > end_dt:
        raise ValueError(f"Start date cannot be after end date for {pair_name}.")
    return True


def get_aware_datetime(date_str, is_end_of_day=False):
    """Converts a YYYY-MM-DD string into a timezone-aware UTC datetime."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if is_end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt


def load_and_filter_mock_data(country_filter):
    mock_dir = os.environ.get("MOCK_DATA_DIR", "./mock_data")
    orgs_df = pd.read_csv(os.path.join(mock_dir, "organizations.csv"))
    states_df = pd.read_csv(os.path.join(mock_dir, "states.csv"))
    countries_df = pd.read_csv(os.path.join(mock_dir, "countries.csv"))
    orgs_df['created_at'] = pd.to_datetime(orgs_df['created_at'])
    
    merged_df = orgs_df.merge(states_df, on='state_id', how='inner')
    merged_df = merged_df.merge(countries_df, on='country_id', how='inner')
    
    if country_filter and country_filter.upper() != "ALL":
        merged_df = merged_df[merged_df['country_code'].str.upper() == country_filter.upper()]
    return merged_df


def build_rating_distribution(df, start_dt, end_dt):
    mask = (df['created_at'] >= start_dt) & (df['created_at'] <= end_dt)
    window_df = df.loc[mask]
    
    if window_df.empty:
        return []
        
    rating_counts = window_df['org_rating'].value_counts().reset_index()
    rating_counts.columns = ['rating', 'count']
    rating_counts = rating_counts.sort_values('rating')
    
    result = []
    for _, row in rating_counts.iterrows():
        result.append({"rating": int(row['rating']), "count": int(row['count'])})
    return result


def build_mix_trend(df, start_dt, end_dt, period_format):
    result = {"non_profit": [], "for_profit": []}
    
    temp_df = df[df['created_at'] <= end_dt].copy()
    if temp_df.empty:
        return result
        
    temp_df['period'] = temp_df['created_at'].dt.strftime(period_format)
    start_str = start_dt.strftime(period_format)
    
    for org_type in ["non_profit", "for_profit"]:
        type_df = temp_df[temp_df['org_type'] == org_type]
        if type_df.empty:
            continue
            
        counts = type_df.groupby('period').size().reset_index(name='new_count')
        counts = counts.sort_values('period')
        counts['cumulative_count'] = counts['new_count'].cumsum()
        
        series = []
        for _, row in counts.iterrows():
            if row['period'] >= start_str:
                series.append({
                    "period": row['period'],
                    "count": int(row['cumulative_count'])
                })
        result[org_type] = series
        
    return result


def lambda_handler(event, context):
    body = {}
    if "body" in event and event["body"]:
        try:
            body = isinstance(event["body"], dict) and event["body"] or json.loads(event["body"])
        except json.JSONDecodeError:
            return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON body"})}

    country = body.get("country", "ALL")
    rating_start = body.get("rating_start_date")
    rating_end = body.get("rating_end_date")
    type_start = body.get("type_start_date")
    type_end = body.get("type_end_date")

    try:
        has_rating_custom = validate_date_pair(rating_start, rating_end, "rating")
        has_type_custom = validate_date_pair(type_start, type_end, "type")
    except ValueError as e:
        return {"statusCode": 400, "body": json.dumps({"error": str(e)})}

    try:
        df = load_and_filter_mock_data(country)
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": f"Failed to load mock data: {str(e)}"})}

    response_payload = {}

    # BRANCH 1: Custom Dates Supplied -> Return ONLY "Custom" bucket
    if has_rating_custom or has_type_custom:
        custom_data = {
            "rating_distribution": [],
            "organization_mix_trend": {"non_profit": [], "for_profit": []}
        }
        
        if has_rating_custom:
            r_start_dt = get_aware_datetime(rating_start)
            r_end_dt = get_aware_datetime(rating_end, is_end_of_day=True)
            custom_data["rating_distribution"] = build_rating_distribution(df, r_start_dt, r_end_dt)
            
        if has_type_custom:
            t_start_dt = get_aware_datetime(type_start)
            t_end_dt = get_aware_datetime(type_end, is_end_of_day=True)
            custom_data["organization_mix_trend"] = build_mix_trend(df, t_start_dt, t_end_dt, "%Y-%m-%d")
            
        response_payload["Custom"] = custom_data

    # BRANCH 2: No Custom Dates Supplied -> Return all 4 fixed buckets + empty Custom bucket
    else:
        now = datetime.now(timezone.utc)
        all_time_start = datetime.min.replace(tzinfo=timezone.utc)
        
        windows = {
            "7D": (now - timedelta(days=7), now, "%Y-%m-%d"),
            "30D": (now - timedelta(days=30), now, "%Y-%m-%d"),
            "1Y": (now - timedelta(days=365), now, "%Y-%m"),
            "All": (all_time_start, now, "%Y-%m")
        }
        
        for bucket, (start_dt, end_dt, period_format) in windows.items():
            response_payload[bucket] = {
                "rating_distribution": build_rating_distribution(df, start_dt, end_dt),
                "organization_mix_trend": build_mix_trend(df, start_dt, end_dt, period_format)
            }
            
        response_payload["Custom"] = {
            "rating_distribution": [],
            "organization_mix_trend": {"non_profit": [], "for_profit": []}
        }

    return {
        "statusCode": 200,
        "body": json.dumps(response_payload)
    }


if __name__ == "__main__":
    os.environ["USE_MOCK_DATA"] = "true"
    os.environ["MOCK_DATA_DIR"] = "./mock_data"

    test_events = [
        {"name": "No Body - All Buckets", "body": "{}"},
        {"name": "Country USA Only", "body": json.dumps({"country": "USA"})},
        {"name": "Only Rating Custom", "body": json.dumps({"rating_start_date": "2026-01-01", "rating_end_date": "2026-12-31"})},
        {"name": "Only Type Custom", "body": json.dumps({"type_start_date": "2024-01-01", "type_end_date": "2025-12-31"})},
        {"name": "Both Custom Together", "body": json.dumps({
            "rating_start_date": "2026-01-01", "rating_end_date": "2026-12-31",
            "type_start_date": "2024-01-01", "type_end_date": "2025-12-31"
        })},
        {"name": "Error - Bad Date Logic", "body": json.dumps({"type_start_date": "2025-01-01", "type_end_date": "2024-01-01"})}
    ]

    for test in test_events:
        print(f"\n--- Testing: {test['name']} ---")
        result = lambda_handler(test, None)
        print(json.dumps(result, indent=2))
