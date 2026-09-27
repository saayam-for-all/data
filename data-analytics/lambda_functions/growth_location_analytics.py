import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "sql"
MOCK_DATA_DIR = Path(os.getenv("MOCK_DATA_DIR", DEFAULT_DATA_DIR))

BUCKET_ORDER = ("7D", "30D", "1Y", "All", "Custom")


def parse_event_body(event):
    """Parse the Lambda request body."""
    if not event:
        return {}

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, dict):
        return body

    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON body") from exc

    raise ValueError("Invalid request body")


def build_response(status_code, body):
    """Build a Lambda-compatible response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def find_csv(*filenames):
    """Return the first matching CSV path from the local data directory."""
    for filename in filenames:
        path = MOCK_DATA_DIR / filename
        if path.exists():
            return path

    raise FileNotFoundError(
        f"Could not find any of: {', '.join(filenames)}"
    )


def load_data():
    """Load and prepare organization, state, and country CSV data."""
    organizations_path = find_csv("organizations.csv")
    states_path = find_csv("state.csv", "states.csv")
    countries_path = find_csv("country.csv", "countries.csv")

    organizations = pd.read_csv(organizations_path)
    states = pd.read_csv(states_path)
    countries = pd.read_csv(countries_path)

    required_org_columns = {
        "org_id",
        "state_id",
        "city_name",
        "is_collaborator",
        "created_at",
    }
    required_state_columns = {
        "state_id",
        "state_name",
        "country_id",
    }
    required_country_columns = {
        "country_id",
        "country_code",
    }

    missing_org = required_org_columns - set(organizations.columns)
    missing_state = required_state_columns - set(states.columns)
    missing_country = required_country_columns - set(countries.columns)

    if missing_org:
        raise ValueError(
            f"organizations.csv missing columns: {sorted(missing_org)}"
        )

    if missing_state:
        raise ValueError(
            f"state CSV missing columns: {sorted(missing_state)}"
        )

    if missing_country:
        raise ValueError(
            f"country CSV missing columns: {sorted(missing_country)}"
        )

    organizations = organizations.copy()
    states = states.copy()
    countries = countries.copy()

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"],
        errors="coerce",
    )

    organizations["is_collaborator"] = (
        organizations["is_collaborator"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes", "y", "t"})
    )

    return organizations, states, countries


def validate_date_pair(body, start_key, end_key, label):
    """Validate one optional Custom date range independently."""
    start_value = body.get(start_key)
    end_value = body.get(end_key)

    if start_value is None and end_value is None:
        return None

    if start_value is None or end_value is None:
        raise ValueError(
            f"{label} requires both {start_key} and {end_key}"
        )

    try:
        start_date = pd.Timestamp(
            datetime.strptime(start_value, "%Y-%m-%d")
        )
        end_date = pd.Timestamp(
            datetime.strptime(end_value, "%Y-%m-%d")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{label} dates must use YYYY-MM-DD format"
        ) from exc

    if start_date > end_date:
        raise ValueError(
            f"{start_key} cannot be after {end_key}"
        )

    return start_date, end_date


def current_date():
    """Return today's normalized local date."""
    return pd.Timestamp.now().normalize()


def get_fixed_window(bucket):
    """Return the inclusive date window for a fixed bucket."""
    today = current_date()

    if bucket == "7D":
        return today - pd.Timedelta(days=6), today

    if bucket == "30D":
        return today - pd.Timedelta(days=29), today

    if bucket == "1Y":
        return today - pd.DateOffset(years=1), today

    if bucket == "All":
        return None

    raise ValueError(f"Unsupported bucket: {bucket}")


def filter_by_window(organizations, date_range):
    """Filter organizations to an inclusive date range."""
    if date_range is None:
        return organizations[
            organizations["created_at"].notna()
        ].copy()

    start_date, end_date = date_range
    end_exclusive = end_date + pd.Timedelta(days=1)

    return organizations[
        organizations["created_at"].notna()
        & (organizations["created_at"] >= start_date)
        & (organizations["created_at"] < end_exclusive)
    ].copy()


def period_series(frame, granularity):
    """Return period labels for a dataframe."""
    if granularity == "day":
        return frame["created_at"].dt.strftime("%Y-%m-%d")

    if granularity == "month":
        return frame["created_at"].dt.strftime("%Y-%m")

    raise ValueError(f"Unsupported granularity: {granularity}")


def period_end(period, granularity):
    """Return the exclusive end timestamp for a period."""
    if granularity == "day":
        return pd.Timestamp(period) + pd.Timedelta(days=1)

    if granularity == "month":
        return pd.Timestamp(f"{period}-01") + pd.DateOffset(months=1)

    raise ValueError(f"Unsupported granularity: {granularity}")


def build_growth_trend(
    organizations,
    date_range,
    granularity,
):
    """
    Build growth trend data.

    total_organizations is the absolute all-time running total as of each
    period. collaborators is the non-cumulative count within each period.
    """
    valid_organizations = organizations[
        organizations["created_at"].notna()
    ].copy()

    window_data = filter_by_window(
        valid_organizations,
        date_range,
    )

    if window_data.empty:
        return {
            "total_organizations": [],
            "collaborators": [],
        }

    window_data["period"] = period_series(
        window_data,
        granularity,
    )

    periods = sorted(window_data["period"].unique())

    collaborator_counts = (
        window_data[
            window_data["is_collaborator"]
        ]
        .groupby("period")
        .size()
        .to_dict()
    )

    total_series = []
    collaborator_series = []

    for period in periods:
        cutoff = period_end(period, granularity)

        total_count = int(
            (
                valid_organizations["created_at"]
                < cutoff
            ).sum()
        )

        collaborator_count = int(
            collaborator_counts.get(period, 0)
        )

        total_series.append(
            {
                "period": period,
                "count": total_count,
            }
        )

        collaborator_series.append(
            {
                "period": period,
                "count": collaborator_count,
            }
        )

    return {
        "total_organizations": total_series,
        "collaborators": collaborator_series,
    }


def build_location_data(
    organizations,
    states,
    countries,
    date_range,
):
    """Build the top-four country organization distribution."""
    window_data = filter_by_window(
        organizations,
        date_range,
    )

    if window_data.empty:
        return []

    state_lookup = states[
        ["state_id", "country_id"]
    ].drop_duplicates()

    country_lookup = countries[
        ["country_id", "country_code"]
    ].drop_duplicates()

    merged = window_data.merge(
        state_lookup,
        on="state_id",
        how="inner",
    )

    merged = merged.merge(
        country_lookup,
        on="country_id",
        how="inner",
    )

    if merged.empty:
        return []

    grouped = (
        merged.groupby("country_code")
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
            "country": str(row.country_code),
            "count": int(row.count),
        }
        for row in grouped.itertuples(index=False)
    ]


def build_bucket(
    organizations,
    states,
    countries,
    date_range,
    granularity,
):
    """Build one complete fixed response bucket."""
    return {
        "growth_trend": build_growth_trend(
            organizations,
            date_range,
            granularity,
        ),
        "organizations_by_location": build_location_data(
            organizations,
            states,
            countries,
            date_range,
        ),
    }


def empty_custom_bucket():
    """Return the empty Custom bucket structure."""
    return {
        "growth_trend": {
            "total_organizations": [],
            "collaborators": [],
        },
        "organizations_by_location": [],
    }


def build_payload(body):
    """Build all five Growth & Location response buckets."""
    organizations, states, countries = load_data()

    growth_custom_range = validate_date_pair(
        body,
        "start_date",
        "end_date",
        "Growth Trend Custom range",
    )

    location_custom_range = validate_date_pair(
        body,
        "location_start_date",
        "location_end_date",
        "Location Custom range",
    )

    response = {}

    response["7D"] = build_bucket(
        organizations,
        states,
        countries,
        get_fixed_window("7D"),
        "day",
    )

    response["30D"] = build_bucket(
        organizations,
        states,
        countries,
        get_fixed_window("30D"),
        "day",
    )

    response["1Y"] = build_bucket(
        organizations,
        states,
        countries,
        get_fixed_window("1Y"),
        "month",
    )

    response["All"] = build_bucket(
        organizations,
        states,
        countries,
        get_fixed_window("All"),
        "month",
    )

    custom_bucket = empty_custom_bucket()

    if growth_custom_range is not None:
        custom_bucket["growth_trend"] = build_growth_trend(
            organizations,
            growth_custom_range,
            "day",
        )

    if location_custom_range is not None:
        custom_bucket["organizations_by_location"] = (
            build_location_data(
                organizations,
                states,
                countries,
                location_custom_range,
            )
        )

    response["Custom"] = custom_bucket

    return response


def lambda_handler(event, context):
    """AWS Lambda entry point for Growth & Location analytics."""
    try:
        body = parse_event_body(event)
        payload = build_payload(body)
        return build_response(200, payload)

    except ValueError as exc:
        return build_response(
            400,
            {"error": str(exc)},
        )

    except Exception as exc:
        print(f"ERROR: {exc}")
        return build_response(
            500,
            {"error": "Unable to generate Growth & Location analytics"},
        )


def print_sample(label, event):
    """Run and print one local Lambda sample event."""
    response = lambda_handler(event, None)

    printable = {
        "statusCode": response["statusCode"],
        "body": json.loads(response["body"]),
    }

    print(f"\n===== {label} =====")
    print(json.dumps(printable, indent=2))


if __name__ == "__main__":
    print_sample(
        "No body",
        {},
    )

    print_sample(
        "Growth Custom only",
        {
            "body": json.dumps(
                {
                    "start_date": "2025-01-01",
                    "end_date": "2026-01-31",
                }
            )
        },
    )

    print_sample(
        "Location Custom only",
        {
            "body": json.dumps(
                {
                    "location_start_date": "2025-01-01",
                    "location_end_date": "2026-01-31",
                }
            )
        },
    )

    print_sample(
        "Both Custom ranges",
        {
            "body": json.dumps(
                {
                    "start_date": "2025-01-01",
                    "end_date": "2026-01-31",
                    "location_start_date": "2025-01-01",
                    "location_end_date": "2026-01-31",
                }
            )
        },
    )