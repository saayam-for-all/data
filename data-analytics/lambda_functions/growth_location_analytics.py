"""Growth & Location Analytics API — issue #336."""

import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


def load_data():
    """Read local CSVs and attach a country to each organization."""

    default_folder = Path(__file__).resolve().parent.parent / "sql"
    data_folder = Path(os.environ.get("MOCK_DATA_DIR") or default_folder)

    organizations = pd.read_csv(
        data_folder / "organizations.csv",
        dtype={"org_id": str, "state_id": str},
    )

    states = pd.read_csv(
        data_folder / "state.csv",
        dtype={"state_id": str, "country_id": str},
    )

    countries = pd.read_csv(
        data_folder / "country.csv",
        dtype={"country_id": str},
    )

    organizations = organizations[
        ["org_id", "state_id", "is_collaborator", "created_at"]
    ].copy()

    states = states[["state_id", "country_id"]].copy()
    countries = countries[["country_id", "country_code"]].copy()

    organizations["state_id"] = organizations["state_id"].str.strip()
    states["state_id"] = states["state_id"].str.strip()
    states["country_id"] = states["country_id"].str.strip()
    countries["country_id"] = countries["country_id"].str.strip()

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"],
        errors="raise",
    )

    organizations["is_collaborator"] = (
        organizations["is_collaborator"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(["true", "t", "1", "yes"])
    )

    state_countries = states.merge(
        countries,
        on="country_id",
        how="left",
        validate="many_to_one",
    )

    result = organizations.merge(
        state_countries[["state_id", "country_code"]],
        on="state_id",
        how="left",
        validate="many_to_one",
    )

    return result


def build_growth_trend(data, start_date=None, end_date=None, frequency="D"):
    """Build all-time totals and window-scoped collaborator counts."""

    empty_result = {
        "total_organizations": [],
        "collaborators": [],
    }

    if data.empty:
        return empty_result

    # Running totals use the COMPLETE organization history.
        # Keep all earlier history, up to the selected end date.
    history = data

    if end_date is not None:
        history = data.loc[
            data["created_at"].dt.normalize() <= pd.Timestamp(end_date)
        ]

    all_periods = history["created_at"].dt.to_period(frequency)

    running_totals = (
        all_periods.value_counts()
        .sort_index()
        .cumsum()
    )

    # The window determines which periods appear in the response.
    creation_days = data["created_at"].dt.normalize()
    mask = pd.Series(True, index=data.index)

    if start_date is not None:
        mask &= creation_days >= pd.Timestamp(start_date)

    if end_date is not None:
        mask &= creation_days <= pd.Timestamp(end_date)

    window = data.loc[mask]

    if window.empty:
        return empty_result

    window_periods = window["created_at"].dt.to_period(frequency)
    periods = sorted(window_periods.unique())

    # Collaborators are counted within each selected period.
    collaborator_counts = window_periods[
        window["is_collaborator"]
    ].value_counts()

    return {
        "total_organizations": [
            {
                "period": str(period),
                "count": int(running_totals[period]),
            }
            for period in periods
        ],
        "collaborators": [
            {
                "period": str(period),
                "count": int(collaborator_counts.get(period, 0)),
            }
            for period in periods
        ],
    }
def build_organizations_by_location(data, start_date=None, end_date=None):
    """Return the top four countries within the selected date window."""

    if data.empty:
        return []

    creation_days = data["created_at"].dt.normalize()
    mask = pd.Series(True, index=data.index)

    if start_date is not None:
        mask &= creation_days >= pd.Timestamp(start_date)

    if end_date is not None:
        mask &= creation_days <= pd.Timestamp(end_date)

    window = data.loc[mask]

    if window.empty:
        return []

    country_counts = window["country_code"].dropna().value_counts()

    # Highest count first; alphabetical country order breaks ties.
    top_countries = sorted(
        country_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )[:4]

    return [
        {
            "country": str(country),
            "count": int(count),
        }
        for country, count in top_countries
    ]
def parse_custom_range(params, start_key, end_key):
    """Validate one chart's Custom dates independently."""

    has_start = start_key in params
    has_end = end_key in params

    # No dates supplied: this chart's Custom section stays empty.
    if not has_start and not has_end:
        return None

    # A Custom range needs both boundaries.
    if not has_start or not has_end:
        raise ValueError(
            "{} and {} must be supplied together".format(start_key, end_key)
        )

    parsed_dates = []

    for key in (start_key, end_key):
        value = params[key]

        # Require the exact YYYY-MM-DD format.
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", value
        ):
            raise ValueError("{} must use YYYY-MM-DD format".format(key))

        try:
            parsed_dates.append(date.fromisoformat(value))
        except ValueError:
            raise ValueError("{} is not a valid calendar date".format(key))

    start_date, end_date = parsed_dates

    if start_date > end_date:
        raise ValueError(
            "{} must be on or before {}".format(start_key, end_key)
        )

    return start_date, end_date

def parse_request(event):
    """Accept a plain dictionary or an API Gateway request body."""

    if event is None:
        return {}

    if not isinstance(event, dict):
        raise ValueError("Request must be a JSON object")

    body = event.get("body", event)

    if body is None:
        return {}

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("Request body must contain valid JSON")

    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")

    return body


def make_response(status_code, payload):
    """Create the Lambda response with a JSON body."""

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(payload),
    }


def lambda_handler(event, context):
    """Return both charts for every required time bucket."""

    # Validate each Custom pair before loading data.
    try:
        params = parse_request(event)

        growth_range = parse_custom_range(
            params, "start_date", "end_date"
        )

        location_range = parse_custom_range(
            params, "location_start_date", "location_end_date"
        )

    except ValueError as error:
        return make_response(400, {"error": str(error)})

    try:
        data = load_data()
        today = date.today()

        # Inclusive windows: today plus the preceding 6/29/364 days.
        fixed_windows = {
            "7D": (today - timedelta(days=6), today, "D"),
            "30D": (today - timedelta(days=29), today, "D"),
            "1Y": (today - timedelta(days=364), today, "M"),
            "All": (None, None, "M"),
        }

        result = {}

        for bucket, window in fixed_windows.items():
            start_date, end_date, frequency = window

            result[bucket] = {
                "growth_trend": build_growth_trend(
                    data,
                    start_date=start_date,
                    end_date=end_date,
                    frequency=frequency,
                ),
                "organizations_by_location": (
                    build_organizations_by_location(
                        data,
                        start_date=start_date,
                        end_date=end_date,
                    )
                ),
            }

        # Custom starts empty for both charts.
        result["Custom"] = {
            "growth_trend": {
                "total_organizations": [],
                "collaborators": [],
            },
            "organizations_by_location": [],
        }

        # Populate growth only when its own range was supplied.
        if growth_range is not None:
            growth_start, growth_end = growth_range

            result["Custom"]["growth_trend"] = build_growth_trend(
                data,
                start_date=growth_start,
                end_date=growth_end,
                frequency="D",
            )

        # Populate location only when its own range was supplied.
        if location_range is not None:
            location_start, location_end = location_range

            result["Custom"]["organizations_by_location"] = (
                build_organizations_by_location(
                    data,
                    start_date=location_start,
                    end_date=location_end,
                )
            )

        return make_response(200, result)

    except Exception as error:
        print("Could not build analytics:", str(error))

        return make_response(
            500,
            {"error": "Could not load organization analytics"},
        )

if __name__ == "__main__":
    sample_requests = [
        ("No body", {}),
        (
            "Growth only",
            {
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
            },
        ),
        (
            "Location only",
            {
                "location_start_date": "2025-01-01",
                "location_end_date": "2025-12-31",
            },
        ),
        (
            "Both charts",
            {
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "location_start_date": "2025-01-01",
                "location_end_date": "2025-12-31",
            },
        ),
        (
            "Invalid growth date",
            {
                "start_date": "2026-02-30",
                "end_date": "2026-03-31",
            },
        ),
        (
            "Reversed location dates",
            {
                "location_start_date": "2026-12-31",
                "location_end_date": "2026-01-01",
            },
        ),
    ]

    for label, params in sample_requests:
        event = {} if label == "No body" else {
            "body": json.dumps(params)
        }

        response = lambda_handler(event, None)
        payload = json.loads(response["body"])

        print("\nCASE:", label)
        print("STATUS:", response["statusCode"])
        print(json.dumps(payload, indent=2))

        if response["statusCode"] == 200:
            print("BUCKETS:", list(payload.keys()))
            print("CUSTOM:", json.dumps(payload["Custom"]))