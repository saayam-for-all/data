"""
Growth & Location Analytics API for Organization Dashboard.

This Lambda function returns analytics data for two charts:
1. Growth Trend Chart — organizations and collaborators over time
2. Organization By Location — top locations by organization count

Each chart has independent time-range controls (7D / 30D / 1Y / All / Custom).
The API returns all time buckets in a single response for instant frontend switching.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd


class GrowthLocationAnalytics:
    """Handles growth and location analytics calculations."""
    
    def __init__(self, mock_data_dir: Optional[str] = None):
        """
        Initialize with optional mock data directory for local testing.
        
        Args:
            mock_data_dir: Path to directory containing organizations.csv, states.csv, countries.csv
        """
        self.mock_data_dir = mock_data_dir or os.getenv("MOCK_DATA_DIR", "./mock_data")
        self.organizations_df = None
        self.states_df = None
        self.countries_df = None
        
    def load_data(self) -> bool:
        """Load CSV files. Returns True if successful, False otherwise."""
        try:
            self.organizations_df = pd.read_csv(
                os.path.join(self.mock_data_dir, "organizations.csv")
            )
            self.states_df = pd.read_csv(
                os.path.join(self.mock_data_dir, "states.csv")
            )
            self.countries_df = pd.read_csv(
                os.path.join(self.mock_data_dir, "countries.csv")
            )
            
            # Convert created_at to datetime
            self.organizations_df["created_at"] = pd.to_datetime(
                self.organizations_df["created_at"]
            )
            
            # Convert is_collaborator to boolean
            self.organizations_df["is_collaborator"] = self.organizations_df["is_collaborator"].astype(bool)
            
            # Merge organizations with states and countries to get country codes
            self.organizations_df = self.organizations_df.merge(
                self.states_df[["state_id", "country_id"]],
                on="state_id",
                how="left"
            )
            self.organizations_df = self.organizations_df.merge(
                self.countries_df[["country_id", "country_code"]],
                on="country_id",
                how="left"
            )
            
            return True
        except Exception as e:
            print(f"Error loading data: {e}")
            return False
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string in YYYY-MM-DD format."""
        try:
            return pd.to_datetime(date_str)
        except Exception:
            return None
    
    def _validate_date_range(
        self, start_str: Optional[str], end_str: Optional[str]
    ) -> Tuple[bool, Optional[str], Optional[datetime], Optional[datetime]]:
        """
        Validate date range. Returns (is_valid, error_message, start_date, end_date).
        """
        if not start_str and not end_str:
            return True, None, None, None
        
        start_date = None
        end_date = None
        
        if start_str:
            start_date = self._parse_date(start_str)
            if not start_date:
                return False, f"Invalid start_date format: {start_str}", None, None
        
        if end_str:
            end_date = self._parse_date(end_str)
            if not end_date:
                return False, f"Invalid end_date format: {end_str}", None, None
        
        if start_date and end_date and start_date > end_date:
            return False, "start_date must be <= end_date", None, None
        
        return True, None, start_date, end_date
    
    def _get_bucket_window(self, bucket: str, reference_date: Optional[datetime] = None) -> Tuple[datetime, datetime]:
        """Get the time window for a given bucket."""
        if reference_date is None:
            reference_date = datetime.now()
        
        if bucket == "7D":
            end = reference_date.replace(hour=23, minute=59, second=59)
            start = (end - timedelta(days=6)).replace(hour=0, minute=0, second=0)
        elif bucket == "30D":
            end = reference_date.replace(hour=23, minute=59, second=59)
            start = (end - timedelta(days=29)).replace(hour=0, minute=0, second=0)
        elif bucket == "1Y":
            # Calendar year (Jan 1 to Dec 31 of current year)
            end = datetime(reference_date.year, 12, 31, 23, 59, 59)
            start = datetime(reference_date.year, 1, 1, 0, 0, 0)
        elif bucket == "All":
            # All time
            start = datetime(2000, 1, 1, 0, 0, 0)
            end = datetime(2099, 12, 31, 23, 59, 59)
        else:
            raise ValueError(f"Invalid bucket: {bucket}")
        
        return start, end
    
    def _get_growth_trend(
        self, bucket: str, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Calculate growth trend for a bucket.
        
        Returns:
            {
                "total_organizations": [{"period": "...", "count": ...}, ...],
                "collaborators": [{"period": "...", "count": ...}, ...]
            }
        """
        if bucket == "Custom":
            if not start_date or not end_date:
                return {"total_organizations": [], "collaborators": []}
            window_start, window_end = start_date, end_date
            granularity = "day"
        else:
            window_start, window_end = self._get_bucket_window(bucket)
            granularity = "month" if bucket in ["1Y", "All"] else "day"
        
        # Filter organizations by window
        org_in_window = self.organizations_df[
            (self.organizations_df["created_at"] >= window_start) &
            (self.organizations_df["created_at"] <= window_end)
        ].copy()
        
        # Calculate total_organizations (cumulative, all-time)
        all_orgs = self.organizations_df[
            self.organizations_df["created_at"] <= window_end
        ].copy()
        
        if granularity == "day":
            all_orgs["period"] = all_orgs["created_at"].dt.strftime("%Y-%m-%d")
            org_in_window["period"] = org_in_window["created_at"].dt.strftime("%Y-%m-%d")
        else:  # month
            all_orgs["period"] = all_orgs["created_at"].dt.strftime("%Y-%m")
            org_in_window["period"] = org_in_window["created_at"].dt.strftime("%Y-%m")
        
        # Total organizations: cumulative count (all-time running total)
        total_orgs_by_period = all_orgs.groupby("period").size().reset_index(name="count")
        total_orgs_by_period = total_orgs_by_period.sort_values("period")
        total_orgs_by_period["count"] = total_orgs_by_period["count"].cumsum()
        total_count_by_period = dict(zip(
            total_orgs_by_period["period"], total_orgs_by_period["count"]
        ))
        
        # Collaborators: per-period count within the bucket window, not cumulative
        collab_by_period = org_in_window[org_in_window["is_collaborator"]].groupby("period").size().reset_index(name="count")
        collab_by_period = collab_by_period.sort_values("period")
        collaborator_count_by_period = dict(zip(
            collab_by_period["period"], collab_by_period["count"]
        ))
        active_periods = sorted(org_in_window["period"].unique())
        total_orgs_list = [
            {"period": period, "count": total_count_by_period[period]}
            for period in active_periods
        ]
        collab_list = [
            {"period": period, "count": collaborator_count_by_period.get(period, 0)}
            for period in active_periods
        ]
        
        return {
            "total_organizations": total_orgs_list,
            "collaborators": collab_list
        }
    
    def _get_organizations_by_location(
        self, bucket: str, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Calculate top 4 countries by organization count for a bucket.
        
        Returns list of {"country": "...", "count": ...}
        """
        if bucket == "Custom":
            if not start_date or not end_date:
                return []
            window_start, window_end = start_date, end_date
        else:
            window_start, window_end = self._get_bucket_window(bucket)
        
        # Filter organizations by window
        org_in_window = self.organizations_df[
            (self.organizations_df["created_at"] >= window_start) &
            (self.organizations_df["created_at"] <= window_end)
        ].copy()
        
        # Group by country and count
        country_counts = org_in_window.groupby("country_code").size().reset_index(name="count")
        country_counts = country_counts.sort_values("count", ascending=False)
        
        # Return top 4 (or all if fewer than 4)
        top_countries = country_counts.head(4).to_dict("records")
        top_countries = [{"country": row["country_code"], "count": row["count"]} for row in top_countries]
        
        return top_countries
    
    def analyze(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main analysis function. Entry point for Lambda.
        
        Args:
            event: API Gateway event with optional body containing date ranges
                {
                    "start_date": "2026-01-01",
                    "end_date": "2026-06-30",
                    "location_start_date": "2025-01-01",
                    "location_end_date": "2025-12-31"
                }
        
        Returns:
            {
                "7D": {...},
                "30D": {...},
                "1Y": {...},
                "All": {...},
                "Custom": {...}
            }
        """
        # Load data
        if not self.load_data():
            return {"error": "Failed to load CSV data", "status_code": 500}
        
        # Parse request body
        body = {}
        if isinstance(event, dict) and "body" in event:
            try:
                if isinstance(event["body"], str):
                    body = json.loads(event["body"]) if event["body"] else {}
                else:
                    body = event["body"] or {}
            except json.JSONDecodeError:
                return {"error": "Invalid JSON in request body", "status_code": 400}
        elif isinstance(event, dict):
            body = event
        
        # Validate and extract date ranges
        growth_start = body.get("start_date")
        growth_end = body.get("end_date")
        location_start = body.get("location_start_date")
        location_end = body.get("location_end_date")
        
        # Validate growth trend dates
        is_valid, error_msg, growth_start_date, growth_end_date = self._validate_date_range(
            growth_start, growth_end
        )
        if not is_valid:
            return {"error": error_msg, "status_code": 400}
        
        # Validate location dates
        is_valid, error_msg, location_start_date, location_end_date = self._validate_date_range(
            location_start, location_end
        )
        if not is_valid:
            return {"error": error_msg, "status_code": 400}
        
        # Calculate analytics for each bucket
        response = {}
        for bucket in ["7D", "30D", "1Y", "All", "Custom"]:
            if bucket == "Custom":
                growth_trend = self._get_growth_trend(bucket, growth_start_date, growth_end_date)
                org_by_location = self._get_organizations_by_location(bucket, location_start_date, location_end_date)
            else:
                growth_trend = self._get_growth_trend(bucket)
                org_by_location = self._get_organizations_by_location(bucket)
            
            response[bucket] = {
                "growth_trend": growth_trend,
                "organizations_by_location": org_by_location
            }
        
        return response


def lambda_handler(event, context):
    """AWS Lambda handler entry point."""
    analytics = GrowthLocationAnalytics()
    result = analytics.analyze(event)
    
    if "error" in result:
        return {
            "statusCode": result.get("status_code", 500),
            "body": json.dumps({"error": result["error"]})
        }
    
    return {
        "statusCode": 200,
        "body": json.dumps(result),
        "headers": {"Content-Type": "application/json"}
    }


if __name__ == "__main__":
    # Local testing with sample events
    print("=" * 80)
    print("Testing Growth & Location Analytics API")
    print("=" * 80)
    
    # Test 1: No body (all buckets, Custom empty)
    print("\n[Test 1] No body - all buckets should have data, Custom empty:")
    analytics = GrowthLocationAnalytics()
    result = analytics.analyze({})
    print(json.dumps(result, indent=2))
    
    # Test 2: Only growth trend dates
    print("\n[Test 2] Only growth trend dates (start_date/end_date):")
    result = analytics.analyze({
        "start_date": "2026-04-01",
        "end_date": "2026-05-31"
    })
    print(json.dumps(result, indent=2))
    
    # Test 3: Only location dates
    print("\n[Test 3] Only location dates (location_start_date/location_end_date):")
    result = analytics.analyze({
        "location_start_date": "2026-02-01",
        "location_end_date": "2026-03-31"
    })
    print(json.dumps(result, indent=2))
    
    # Test 4: Both date ranges
    print("\n[Test 4] Both date ranges:")
    result = analytics.analyze({
        "start_date": "2026-01-01",
        "end_date": "2026-06-30",
        "location_start_date": "2025-01-01",
        "location_end_date": "2025-12-31"
    })
    print(json.dumps(result, indent=2))
    
    # Test 5: Invalid date format
    print("\n[Test 5] Invalid date format:")
    result = analytics.analyze({
        "start_date": "2026-13-45"
    })
    print(json.dumps(result, indent=2))
    
    # Test 6: Start date after end date
    print("\n[Test 6] Start date after end date:")
    result = analytics.analyze({
        "start_date": "2026-12-31",
        "end_date": "2026-01-01"
    })
    print(json.dumps(result, indent=2))
    
    print("\n" + "=" * 80)
    print("Testing complete!")
    print("=" * 80)
