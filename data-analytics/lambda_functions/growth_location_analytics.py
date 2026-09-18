
import json
import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MOCK_DATA_DIR = BASE_DIR.parent / "mock-data-generation"

REQUIRED_COLUMNS = {
    "organizations.csv": [
        "org_id",
        "state_id",
        "city_name",
        "is_collaborator",
        "created_at",
    ],
    "states.csv": [
        "state_id",
        "state_name",
        "country_id",
    ],
    "countries.csv": [
        "country_id",
        "country_code",
    ],
}


class RequestValidationError(ValueError):
    pass


class DataValidationError(ValueError):
    pass


def get_mock_data_dir():
    return Path(os.environ.get("MOCK_DATA_DIR", str(DEFAULT_MOCK_DATA_DIR)))


def read_required_csv(data_dir, filename):
    path = data_dir / filename
    if not path.exists():
        raise DataValidationError(f"Missing required file: {path}")

    df = pd.read_csv(path, dtype=str)
    missing = [
        column
        for column in REQUIRED_COLUMNS[filename]
        if column not in df.columns
    ]

    if missing:
        raise DataValidationError(
            f"{filename} is missing required columns: {', '.join(missing)}"
        )

    return df[REQUIRED_COLUMNS[filename]].copy()


def load_data(data_dir=None):
    data_dir = Path(data_dir) if data_dir else get_mock_data_dir()

    organizations = read_required_csv(data_dir, "organizations.csv")
    states = read_required_csv(data_dir, "states.csv")
    countries = read_required_csv(data_dir, "countries.csv")

    # Normalize join keys.
    organizations["state_id"] = organizations["state_id"].astype("string").str.strip()
    states["state_id"] = states["state_id"].astype("string").str.strip()
    states["country_id"] = states["country_id"].astype("string").str.strip()
    countries["country_id"] = countries["country_id"].astype("string").str.strip()
    countries["country_code"] = countries["country_code"].astype("string").str.strip()

    if states["state_id"].duplicated().any():
        raise DataValidationError("states.csv contains duplicate state_id values")

    if countries["country_id"].duplicated().any():
        raise DataValidationError("countries.csv contains duplicate country_id values")

    # Validate and normalize created_at.
    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"],
        errors="coerce",
    )
    if organizations["created_at"].isna().any():
        raise DataValidationError(
            "organizations.csv contains invalid created_at values"
        )

    organizations["created_date"] = organizations["created_at"].dt.normalize()

    # Normalize collaborator flag.
    collaborator_values = (
        organizations["is_collaborator"]
        .astype("string")
        .str.strip()
        .str.lower()
    )

    invalid_collaborators = collaborator_values[
        ~collaborator_values.isin(["true", "false"])
    ]

    if not invalid_collaborators.empty:
        bad_values = sorted(invalid_collaborators.dropna().unique().tolist())
        raise DataValidationError(
            "organizations.csv contains invalid is_collaborator values: "
            + ", ".join(bad_values)
        )

    organizations["is_collaborator_bool"] = collaborator_values.eq("true")

    # states -> countries
    state_country = states.merge(
        countries[["country_id", "country_code"]],
        on="country_id",
        how="left",
    )

    missing_country = state_country[state_country["country_code"].isna()]
    if not missing_country.empty:
        bad_ids = sorted(missing_country["country_id"].dropna().unique().tolist())
        raise DataValidationError(
            "states.csv contains country_id values not found in countries.csv: "
            + ", ".join(bad_ids)
        )

    # organizations -> states -> countries
    organizations = organizations.merge(
        state_country[["state_id", "country_code"]],
        on="state_id",
        how="left",
    )

    missing_state = organizations[organizations["country_code"].isna()]
    if not missing_state.empty:
        bad_states = sorted(missing_state["state_id"].dropna().unique().tolist())
        raise DataValidationError(
            "organizations.csv contains state_id values not found in states.csv: "
            + ", ".join(bad_states)
        )

    return organizations, states, countries


def parse_event_body(event):
    if event is None:
        return {}

    if not isinstance(event, dict):
        raise RequestValidationError("Request event must be a JSON object")

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, dict):
        return body

    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RequestValidationError(
                "Request body must contain valid JSON"
            ) from exc

        if not isinstance(parsed, dict):
            raise RequestValidationError(
                "Request body must contain a JSON object"
            )

        return parsed

    raise RequestValidationError("Request body must contain a JSON object")


def parse_date(value, field_name):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise RequestValidationError(
            f"{field_name} must use YYYY-MM-DD format"
        )

    try:
        return pd.Timestamp(datetime.strptime(value, "%Y-%m-%d").date())
    except ValueError as exc:
        raise RequestValidationError(
            f"{field_name} must use a valid YYYY-MM-DD date"
        ) from exc


def parse_date_pair(request, start_key, end_key):
    start_value = request.get(start_key)
    end_value = request.get(end_key)

    if start_value is None and end_value is None:
        return None

    if start_value is None or end_value is None:
        raise RequestValidationError(
            f"{start_key} and {end_key} must be provided together"
        )

    start_date = parse_date(start_value, start_key)
    end_date = parse_date(end_value, end_key)

    if start_date > end_date:
        raise RequestValidationError(
            f"{start_key} cannot be after {end_key}"
        )

    return start_date, end_date


def get_today():
    return pd.Timestamp.today().normalize()


def get_fixed_ranges(organizations):
    today = get_today()

    ranges = {
        "7D": (
            today - pd.Timedelta(days=6),
            today,
            "day",
        ),
        "30D": (
            today - pd.Timedelta(days=29),
            today,
            "day",
        ),
        "1Y": (
            today - pd.DateOffset(years=1),
            today,
            "month",
        ),
    }

    if organizations.empty:
        ranges["All"] = (today, today, "month")
    else:
        ranges["All"] = (
            organizations["created_date"].min(),
            organizations["created_date"].max(),
            "month",
        )

    return ranges


def add_period_column(df, granularity):
    result = df.copy()

    if granularity == "day":
        result["period"] = result["created_date"].dt.strftime("%Y-%m-%d")
    elif granularity == "month":
        result["period"] = result["created_date"].dt.strftime("%Y-%m")
    else:
        raise ValueError(f"Unsupported granularity: {granularity}")

    return result


def filter_window(organizations, start_date, end_date):
    return organizations[
        (organizations["created_date"] >= start_date)
        & (organizations["created_date"] <= end_date)
    ].copy()


def build_growth_trend(
    organizations,
    start_date,
    end_date,
    granularity,
):
    window = filter_window(organizations, start_date, end_date)

    if window.empty:
        return {
            "total_organizations": [],
            "collaborators": [],
        }

    # Sparse periods: only periods containing at least one organization
    # in the selected window are returned.
    window = add_period_column(window, granularity)
    periods = sorted(window["period"].unique().tolist())

    # Build cumulative organization totals from the FULL dataset so the
    # total does not reset at the beginning of a selected time window.
    all_organizations = add_period_column(organizations, granularity)
    all_period_counts = (
        all_organizations.groupby("period")
        .size()
        .sort_index()
        .cumsum()
    )

    total_organizations = [
        {
            "period": period,
            "count": int(all_period_counts.loc[period]),
        }
        for period in periods
    ]

    # Collaborators are per-period and scoped only to the selected window.
    collaborator_counts = (
        window[window["is_collaborator_bool"]]
        .groupby("period")
        .size()
        .to_dict()
    )

    collaborators = [
        {
            "period": period,
            "count": int(collaborator_counts.get(period, 0)),
        }
        for period in periods
    ]

    return {
        "total_organizations": total_organizations,
        "collaborators": collaborators,
    }


def build_organizations_by_location(
    organizations,
    start_date,
    end_date,
):
    window = filter_window(organizations, start_date, end_date)

    if window.empty:
        return []

    counts = (
        window.groupby("country_code")
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
            "country": str(row["country_code"]),
            "count": int(row["count"]),
        }
        for _, row in counts.iterrows()
    ]


def empty_growth_trend():
    return {
        "total_organizations": [],
        "collaborators": [],
    }


def build_analytics_payload(
    organizations,
    growth_custom_range=None,
    location_custom_range=None,
):
    response = {}
    fixed_ranges = get_fixed_ranges(organizations)

    for bucket in ["7D", "30D", "1Y", "All"]:
        start_date, end_date, granularity = fixed_ranges[bucket]

        response[bucket] = {
            "growth_trend": build_growth_trend(
                organizations,
                start_date,
                end_date,
                granularity,
            ),
            "organizations_by_location": build_organizations_by_location(
                organizations,
                start_date,
                end_date,
            ),
        }

    custom_growth = empty_growth_trend()
    custom_location = []

    if growth_custom_range is not None:
        start_date, end_date = growth_custom_range
        custom_growth = build_growth_trend(
            organizations,
            start_date,
            end_date,
            "day",
        )

    if location_custom_range is not None:
        start_date, end_date = location_custom_range
        custom_location = build_organizations_by_location(
            organizations,
            start_date,
            end_date,
        )

    response["Custom"] = {
        "growth_trend": custom_growth,
        "organizations_by_location": custom_location,
    }

    return response


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": body,
    }


def lambda_handler(event, context=None):
    try:
        request = parse_event_body(event)

        growth_custom_range = parse_date_pair(
            request,
            "start_date",
            "end_date",
        )

        location_custom_range = parse_date_pair(
            request,
            "location_start_date",
            "location_end_date",
        )

        organizations, _, _ = load_data()

        response_body = build_analytics_payload(
            organizations,
            growth_custom_range=growth_custom_range,
            location_custom_range=location_custom_range,
        )

        return build_response(200, response_body)

    except RequestValidationError as exc:
        return build_response(
            400,
            {"error": str(exc)},
        )

    except (DataValidationError, OSError, pd.errors.ParserError) as exc:
        print(f"Data loading error: {exc}")
        return build_response(
            500,
            {"error": "Unable to load analytics data"},
        )

    except Exception as exc:
        print(f"Unexpected error: {exc}")
        return build_response(
            500,
            {"error": "Internal server error"},
        )


def print_sample(label, event):
    print(f"\n{'=' * 70}")
    print(label)
    print("=" * 70)
    print("Request:")
    print(json.dumps(event, indent=2))

    response = lambda_handler(event, None)

    print("\nResponse:")
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    sample_events = [
        (
            "No body",
            {},
        ),
        (
            "Growth custom range only",
            {
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
            },
        ),
        (
            "Location custom range only",
            {
                "location_start_date": "2025-01-01",
                "location_end_date": "2025-12-31",
            },
        ),
        (
            "Both custom ranges",
            {
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "location_start_date": "2025-01-01",
                "location_end_date": "2025-12-31",
            },
        ),
    ]

    for label, event in sample_events:
        print_sample(label, event)
