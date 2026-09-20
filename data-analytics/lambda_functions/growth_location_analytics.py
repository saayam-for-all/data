
import json
import os
import re
from datetime import datetime, date, timedelta

import pandas as pd


# Path to the local mock CSV datasets
MOCK_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "mock-data-generation"
)


# Required CSV files
ORGANIZATIONS_CSV = os.path.join(
    MOCK_DATA_DIR, "organizations.csv"
)

STATES_CSV = os.path.join(
    MOCK_DATA_DIR, "states.csv"
)

COUNTRIES_CSV = os.path.join(
    MOCK_DATA_DIR, "countries.csv"
)


# Load the three local CSV datasets
def load_data():
    organizations = pd.read_csv(
        ORGANIZATIONS_CSV,
        encoding="utf-8-sig",
        dtype={"state_id": str}
    )

    states = pd.read_csv(
        STATES_CSV,
        encoding="utf-8-sig",
        dtype={"state_id": str, "country_id": str}
    )

    countries = pd.read_csv(
        COUNTRIES_CSV,
        encoding="utf-8-sig",
        dtype={"country_id": str}
    )

    # Convert organization creation dates to datetime
    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"],
        errors="coerce"
    )

    return organizations, states, countries


# Filter organizations by the selected time range
def filter_by_date(organizations, time_range,
                   start_date=None, end_date=None):

    today = pd.Timestamp.now().normalize()

    if time_range == "7D":
        cutoff = today - pd.Timedelta(days=6)
        return organizations[
            organizations["created_at"] >= cutoff
        ].copy()

    elif time_range == "30D":
        cutoff = today - pd.Timedelta(days=29)
        return organizations[
            organizations["created_at"] >= cutoff
        ].copy()

    elif time_range == "1Y":
        cutoff = today - pd.DateOffset(years=1)
        return organizations[
            organizations["created_at"] >= cutoff
        ].copy()

    elif time_range == "All":
        return organizations.copy()

    elif time_range == "Custom":
        if start_date is None or end_date is None:
            return organizations.iloc[0:0].copy()

        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date) + pd.Timedelta(days=1)

        return organizations[
            (organizations["created_at"] >= start) &
            (organizations["created_at"] < end)
        ].copy()

    else:
        raise ValueError("Invalid time range")

    
# Calculate organization growth over time
def calculate_growth_trend(organizations, time_range,
                           start_date=None, end_date=None):

    # Select organizations within the requested time window
    filtered = filter_by_date(
        organizations,
        time_range,
        start_date,
        end_date
    )

    # Return empty series if no organizations were created
    if filtered.empty:
        return {
            "total_organizations": [],
            "collaborators": []
        }

    # Group by day for 7D, 30D and Custom
    # Group by month for 1Y and All
    if time_range in ["7D", "30D", "Custom"]:
        period_format = "%Y-%m-%d"
    else:
        period_format = "%Y-%m"

    filtered = filtered.copy()

    filtered["period"] = (
        filtered["created_at"].dt.strftime(period_format)
    )

    # Count organizations created in each period
    period_counts = (
        filtered.groupby("period")
        .size()
        .sort_index()
    )

    # Count collaborators created in each period
    collaborator_counts = (
        filtered[
            filtered["is_collaborator"].astype(str).str.lower()
            == "true"
        ]
        .groupby("period")
        .size()
    )

    total_organizations = []
    collaborators = []

    for period in period_counts.index:

        # End of the current day or month
        if period_format == "%Y-%m-%d":
            period_end = (
                pd.Timestamp(period)
                + pd.Timedelta(days=1)
            )
        else:
            period_end = (
                pd.Timestamp(period)
                + pd.DateOffset(months=1)
            )

        # Absolute cumulative count across the entire dataset
        cumulative_count = int(
            (
                organizations["created_at"] < period_end
            ).sum()
        )

        total_organizations.append({
            "period": period,
            "count": cumulative_count
        })

        collaborators.append({
            "period": period,
            "count": int(
                collaborator_counts.get(period, 0)
            )
        })

    return {
        "total_organizations": total_organizations,
        "collaborators": collaborators
    }


# Calculate organization counts by country
def calculate_organizations_by_location(
    organizations,
    states,
    countries,
    time_range,
    start_date=None,
    end_date=None
):

    # Select organizations within the requested time window
    filtered = filter_by_date(
        organizations,
        time_range,
        start_date,
        end_date
    )

    # Return an empty list when there are no organizations
    if filtered.empty:
        return []

    # Connect organizations to their states
    merged = filtered.merge(
        states[["state_id", "country_id"]],
        on="state_id",
        how="left"
    )

    # Connect states to their countries
    merged = merged.merge(
        countries[["country_id", "country_code"]],
        on="country_id",
        how="left"
    )

    # Count organizations belonging to each country
    location_counts = (
        merged.groupby("country_code")["org_id"]
        .nunique()
        .sort_values(ascending=False)
        .head(4)
    )

    # Format the response for the dashboard
    result = []

    for country, count in location_counts.items():
        result.append({
            "country": str(country),
            "count": int(count)
        })

    return result


def lambda_handler(event, context):
    """
    Return growth and location analytics for all five
    dashboard time ranges in a single API response.
    """

    try:
        # Step 1: Read the request
        event = event or {}

        if isinstance(event.get("body"), str):
            event = json.loads(event["body"])

        elif isinstance(event.get("body"), dict):
            event = event["body"]

        if not isinstance(event, dict):
            raise ValueError("Request body must be a JSON object")

        # Step 2: Read the independent Custom date ranges
        start_date = event.get("start_date")
        end_date = event.get("end_date")

        location_start_date = event.get("location_start_date")
        location_end_date = event.get("location_end_date")

        # Step 3: Validate each date pair independently
        def validate_date_pair(start, end):
            if start is None and end is None:
                return None, None

            if not isinstance(start, str) or not isinstance(end, str):
                raise ValueError(
                    "Both start and end dates must be provided"
                )

            for value in (start, end):
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError(
                        "Dates must use YYYY-MM-DD format"
                    )

                try:
                    parsed = datetime.strptime(value, "%Y-%m-%d")
                except ValueError:
                    raise ValueError("Invalid calendar date")

                if parsed.strftime("%Y-%m-%d") != value:
                    raise ValueError("Invalid calendar date")

            if start > end:
                raise ValueError(
                    "Start date cannot be after end date"
                )

            return start, end

        start_date, end_date = validate_date_pair(
            start_date, end_date
        )

        location_start_date, location_end_date = validate_date_pair(
            location_start_date, location_end_date
        )

        # Step 4: Load the local CSV datasets
        organizations, states, countries = load_data()

        # Step 5: Calculate all five time ranges
        response = {}

        for time_range in ["7D", "30D", "1Y", "All", "Custom"]:

            if time_range == "Custom":

                # Growth and location use independent dates
                if start_date is not None:
                    growth_trend = calculate_growth_trend(
                        organizations,
                        time_range,
                        start_date,
                        end_date
                    )
                else:
                    growth_trend = {
                        "total_organizations": [],
                        "collaborators": []
                    }

                if location_start_date is not None:
                    organizations_by_location = (
                        calculate_organizations_by_location(
                            organizations,
                            states,
                            countries,
                            time_range,
                            location_start_date,
                            location_end_date
                        )
                    )
                else:
                    organizations_by_location = []

            else:

                # Fixed time ranges use the same calendar window
                growth_trend = calculate_growth_trend(
                    organizations,
                    time_range
                )

                organizations_by_location = (
                    calculate_organizations_by_location(
                        organizations,
                        states,
                        countries,
                        time_range
                    )
                )

            response[time_range] = {
                "growth_trend": growth_trend,
                "organizations_by_location": organizations_by_location
            }

        # Step 6: Return the complete dashboard response
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps(response)
        }

    except (ValueError, TypeError) as e:

        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "error": str(e)
            })
        }

    except Exception as e:

        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "error": "Internal server error"
            })
        }