import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

# Configuration


DEFAULT_MOCK_DATA_DIR = Path(__file__).resolve().parent / "mock_data"

MOCK_DATA_DIR = Path(os.getenv("MOCK_DATA_DIR", str(DEFAULT_MOCK_DATA_DIR)))


# Required CSV columns

ORGANIZATION_COLUMNS = {
    "org_id",
    "state_id",
    "city_name",
    "is_collaborator",
    "created_at",
}

STATE_COLUMNS = {
    "state_id",
    "state_name",
    "country_id",
}

COUNTRY_COLUMNS = {
    "country_id",
    "country_code",
}


# Warm Lambda instance cache

_DATA_CACHE = None


# Data validation helpers


def validate_columns(df, required_columns, filename):
    """
    Make sure a CSV contains all columns required by this API.
    """

    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise ValueError(
            f"{filename} is missing required columns: {sorted(missing_columns)}"
        )


def normalize_organization_data(organizations):
    """
    Normalize fields that analytics calculations depend on.

    - created_at becomes a UTC datetime
    - is_collaborator becomes a real boolean
    """

    organizations = organizations.copy()

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"],
        utc=True,
        errors="coerce",
    )

    invalid_dates = organizations["created_at"].isna()

    if invalid_dates.any():
        raise ValueError("organizations.csv contains invalid created_at values")

    organizations["is_collaborator"] = (
        organizations["is_collaborator"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes", "y"})
    )

    return organizations


# Actual source loading


def _read_source_data():
    """
    Physically load the three source files.

    This function should only run once per warm Lambda instance.
    """

    organizations_path = MOCK_DATA_DIR / "organizations.csv"
    states_path = MOCK_DATA_DIR / "states.csv"
    countries_path = MOCK_DATA_DIR / "countries.csv"

    organizations = pd.read_csv(organizations_path)
    states = pd.read_csv(states_path)
    countries = pd.read_csv(countries_path)

    validate_columns(
        organizations,
        ORGANIZATION_COLUMNS,
        "organizations.csv",
    )

    validate_columns(
        states,
        STATE_COLUMNS,
        "states.csv",
    )

    validate_columns(
        countries,
        COUNTRY_COLUMNS,
        "countries.csv",
    )

    organizations = normalize_organization_data(organizations)

    return organizations, states, countries


def load_data():
    """
    Return source data.

    Data is physically loaded only once for each warm Lambda
    execution environment.
    """

    global _DATA_CACHE

    if _DATA_CACHE is None:
        _DATA_CACHE = _read_source_data()

    return _DATA_CACHE


# Request parsing


def parse_request_body(event):
    """
    Return the request body as a dictionary.

    Supports:
    - no event
    - no body
    - body already provided as a dict
    - body provided as a JSON string
    """

    if not event:
        return {}

    body = event.get("body")

    if body is None:
        return {}

    if isinstance(body, dict):
        return body

    if isinstance(body, str):
        if not body.strip():
            return {}

        try:
            parsed_body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be valid JSON") from exc

        if not isinstance(parsed_body, dict):
            raise ValueError("Request body must be a JSON object")

        return parsed_body

    raise ValueError("Request body must be a JSON object")


def parse_date(value, field_name):
    """
    Parse one YYYY-MM-DD value.
    Raises ValueError if the value is invalid.
    """

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must use YYYY-MM-DD format")

    try:
        return datetime.strptime(
            value,
            "%Y-%m-%d",
        ).date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def parse_date_pair(
    payload,
    start_key,
    end_key,
):
    """
    Parse and validate one optional date range.

    Returns:
        None
        if neither date was supplied.

        (start_date, end_date)
        if both dates are valid.

    Raises ValueError if:
    - only one side of the pair is provided
    - either date is invalid
    - start date is after end date
    """

    start_value = payload.get(start_key)
    end_value = payload.get(end_key)

    if start_value is None and end_value is None:
        return None

    if start_value is None:
        raise ValueError(f"{start_key} is required when {end_key} is provided")

    if end_value is None:
        raise ValueError(f"{end_key} is required when {start_key} is provided")

    start_date = parse_date(
        start_value,
        start_key,
    )

    end_date = parse_date(
        end_value,
        end_key,
    )

    if start_date > end_date:
        raise ValueError(f"{start_key} cannot be after {end_key}")

    return start_date, end_date


def parse_custom_ranges(payload):
    """
    Parse the two independent Custom chart ranges.
    """

    growth_range = parse_date_pair(
        payload,
        "start_date",
        "end_date",
    )

    location_range = parse_date_pair(
        payload,
        "location_start_date",
        "location_end_date",
    )

    return growth_range, location_range


# date filtering
# -------------------------------------------------------------------
# Date filtering
# -------------------------------------------------------------------


def filter_by_date(
    organizations,
    start_date,
    end_date,
):
    """
    Return organizations created between start_date and end_date,
    inclusive.

    The cached source dataframe is never modified.
    """

    if organizations.empty:
        return organizations.copy()

    start_timestamp = pd.Timestamp(
        start_date,
        tz="UTC",
    )

    end_exclusive = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)

    mask = (organizations["created_at"] >= start_timestamp) & (
        organizations["created_at"] < end_exclusive
    )

    return organizations.loc[mask].copy()


def get_fixed_windows(today=None):
    """
    Return start/end dates for the fixed dashboard ranges.

    7D:
        today plus the previous 6 days.

    30D:
        today plus the previous 29 days.

    1Y:
        today going back one calendar year.

    All is not included here because it uses the complete dataset.
    """

    if today is None:
        today = pd.Timestamp.now(tz="UTC").normalize()
    else:
        today = pd.Timestamp(today)

        if today.tzinfo is None:
            today = today.tz_localize("UTC")
        else:
            today = today.tz_convert("UTC")

        today = today.normalize()

    windows = {
        "7D": {
            "start": (today - pd.Timedelta(days=6)).date(),
            "end": today.date(),
            "granularity": "day",
        },
        "30D": {
            "start": (today - pd.Timedelta(days=29)).date(),
            "end": today.date(),
            "granularity": "day",
        },
        "1Y": {
            "start": (today - pd.DateOffset(years=1)).date(),
            "end": today.date(),
            "granularity": "month",
        },
    }

    return windows


def add_period_column(
    organizations,
    granularity,
):
    """
    Return a copy with a period column.

    day:
        YYYY-MM-DD

    month:
        YYYY-MM
    """

    result = organizations.copy()

    if granularity == "day":
        result["period"] = result["created_at"].dt.strftime("%Y-%m-%d")

    elif granularity == "month":
        result["period"] = result["created_at"].dt.strftime("%Y-%m")

    else:
        raise ValueError(f"Unsupported granularity: {granularity}")

    return result


def build_growth_trend(
    all_organizations,
    window_organizations,
    granularity,
):
    """
    Build the Growth Trend chart data.

    total_organizations:
        Absolute all-time running total as of each active period.

    collaborators:
        Per-period collaborator count inside the selected window.

    Only periods with at least one organization created in the
    selected window are returned.
    """

    if window_organizations.empty:
        return {
            "total_organizations": [],
            "collaborators": [],
        }

    all_with_period = add_period_column(
        all_organizations,
        granularity,
    )

    window_with_period = add_period_column(
        window_organizations,
        granularity,
    )

    active_periods = sorted(window_with_period["period"].unique())

    cumulative_totals = all_with_period.groupby("period").size().sort_index().cumsum()

    collaborator_counts = (
        window_with_period[window_with_period["is_collaborator"]]
        .groupby("period")
        .size()
    )

    total_organizations = [
        {
            "period": period,
            "count": int(cumulative_totals.loc[period]),
        }
        for period in active_periods
    ]

    collaborators = [
        {
            "period": period,
            "count": int(collaborator_counts.get(period, 0)),
        }
        for period in active_periods
    ]

    return {
        "total_organizations": total_organizations,
        "collaborators": collaborators,
    }


def build_organizations_by_location(
    window_organizations,
    states,
    countries,
):
    """
    Build the Organizations by Location chart.

    Organizations are aggregated by country through:

        organizations.state_id
            -> states.country_id
            -> countries.country_code

    Returns at most 4 countries, sorted by count descending.
    """

    if window_organizations.empty:
        return []

    organizations_with_country = window_organizations.merge(
        states[
            [
                "state_id",
                "country_id",
            ]
        ],
        on="state_id",
        how="inner",
    ).merge(
        countries[
            [
                "country_id",
                "country_code",
            ]
        ],
        on="country_id",
        how="inner",
    )

    if organizations_with_country.empty:
        return []

    location_counts = (
        organizations_with_country.groupby("country_code")
        .size()
        .reset_index(name="count")
        .sort_values(
            by=["count", "country_code"],
            ascending=[False, True],
        )
        .head(4)
    )

    return [
        {
            "country": row.country_code,
            "count": int(row.count),
        }
        for row in location_counts.itertuples(index=False)
    ]


def empty_bucket():
    """
    Return the required empty bucket shape.
    """

    return {
        "growth_trend": {
            "total_organizations": [],
            "collaborators": [],
        },
        "organizations_by_location": [],
    }


def build_analytics_response(
    organizations,
    states,
    countries,
    growth_range=None,
    location_range=None,
    today=None,
):
    """
    Build the complete Growth & Location analytics response.

    Fixed buckets:
        7D
        30D
        1Y
        All

    Custom:
        growth_range controls only growth_trend
        location_range controls only organizations_by_location
    """

    result = {
        "7D": empty_bucket(),
        "30D": empty_bucket(),
        "1Y": empty_bucket(),
        "All": empty_bucket(),
        "Custom": empty_bucket(),
    }

    fixed_windows = get_fixed_windows(today=today)

    # Fixed buckets: 7D, 30D, 1Y
    for bucket_name, config in fixed_windows.items():
        window_organizations = filter_by_date(
            organizations,
            config["start"],
            config["end"],
        )

        result[bucket_name]["growth_trend"] = build_growth_trend(
            all_organizations=organizations,
            window_organizations=window_organizations,
            granularity=config["granularity"],
        )

        result[bucket_name]["organizations_by_location"] = (
            build_organizations_by_location(
                window_organizations=window_organizations,
                states=states,
                countries=countries,
            )
        )

    # All

    all_window = organizations.copy()

    result["All"]["growth_trend"] = build_growth_trend(
        all_organizations=organizations,
        window_organizations=all_window,
        granularity="month",
    )

    result["All"]["organizations_by_location"] = build_organizations_by_location(
        window_organizations=all_window,
        states=states,
        countries=countries,
    )

    # Custom Growth Trend

    if growth_range is not None:
        growth_start, growth_end = growth_range

        custom_growth_window = filter_by_date(
            organizations,
            growth_start,
            growth_end,
        )

        result["Custom"]["growth_trend"] = build_growth_trend(
            all_organizations=organizations,
            window_organizations=custom_growth_window,
            granularity="day",
        )

    # Custom Organizations by Location

    if location_range is not None:
        location_start, location_end = location_range

        custom_location_window = filter_by_date(
            organizations,
            location_start,
            location_end,
        )

        result["Custom"]["organizations_by_location"] = build_organizations_by_location(
            window_organizations=custom_location_window,
            states=states,
            countries=countries,
        )

    return result


def lambda_handler(event, context):
    """
    AWS Lambda entry point.
    """

    try:
        payload = parse_request_body(event)

        growth_range, location_range = parse_custom_ranges(payload)

        organizations, states, countries = load_data()

        result = build_analytics_response(
            organizations=organizations,
            states=states,
            countries=countries,
            growth_range=growth_range,
            location_range=location_range,
        )

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
            },
            "body": json.dumps(result),
        }

    except ValueError as exc:
        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json",
            },
            "body": json.dumps(
                {
                    "error": str(exc),
                }
            ),
        }

    except Exception as exc:
        print(f"Unexpected error in growth_location_analytics: {exc}")

        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
            },
            "body": json.dumps(
                {
                    "error": "Internal server error",
                }
            ),
        }


if __name__ == "__main__":
    test_events = [
        {
            "name": "No custom ranges",
            "event": {
                "body": "{}",
            },
        },
        {
            "name": "Growth custom only",
            "event": {
                "body": json.dumps(
                    {
                        "start_date": "2026-01-01",
                        "end_date": "2026-06-30",
                    }
                ),
            },
        },
        {
            "name": "Location custom only",
            "event": {
                "body": json.dumps(
                    {
                        "location_start_date": "2025-01-01",
                        "location_end_date": "2025-12-31",
                    }
                ),
            },
        },
        {
            "name": "Both custom ranges",
            "event": {
                "body": json.dumps(
                    {
                        "start_date": "2026-01-01",
                        "end_date": "2026-06-30",
                        "location_start_date": "2025-01-01",
                        "location_end_date": "2025-12-31",
                    }
                ),
            },
        },
    ]

    for test in test_events:
        print()
        print("=" * 70)
        print(test["name"])
        print("=" * 70)

        response = lambda_handler(
            test["event"],
            None,
        )

        print(
            json.dumps(
                response,
                indent=2,
            )
        )
