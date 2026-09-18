import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MOCK_DATA_DIR = BASE_DIR.parent / "mock-data-generation"
MOCK_DATA_DIR = Path(os.environ.get("MOCK_DATA_DIR", str(DEFAULT_MOCK_DATA_DIR)))

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


def _read_csv(data_dir: Path, filename: str, columns: list[str]) -> pd.DataFrame:
    path = data_dir / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing required mock data file: {path}")

    df = pd.read_csv(path, dtype=str)
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(
            f"{filename} is missing required columns: {', '.join(missing)}"
        )
    return df[columns].copy()


def load_data(data_dir: Path | str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    data_dir = Path(data_dir or os.environ.get("MOCK_DATA_DIR", MOCK_DATA_DIR))

    organizations = _read_csv(
        data_dir, "organizations.csv", REQUIRED_COLUMNS["organizations.csv"]
    )
    states = _read_csv(data_dir, "states.csv", REQUIRED_COLUMNS["states.csv"])
    countries = _read_csv(
        data_dir, "countries.csv", REQUIRED_COLUMNS["countries.csv"]
    )

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"], errors="raise"
    )
    states["state_id"] = states["state_id"].astype(str)
    states["country_id"] = states["country_id"].astype(str)
    countries["country_id"] = countries["country_id"].astype(str)

    normalized = organizations["is_collaborator"].astype(str).str.strip().str.lower()
    invalid_values = sorted(set(normalized.dropna()) - {"true", "false"})
    if invalid_values:
        raise ValueError(
            "organizations.csv contains invalid is_collaborator values: "
            + ", ".join(invalid_values)
        )
    organizations["is_collaborator_bool"] = normalized.eq("true")
    organizations["created_date"] = organizations["created_at"].dt.normalize()

    # Organizations -> state -> country. The city_name field is retained because
    # it is part of the required source schema, although country aggregation only
    # needs the state/country relationship.
    location_map = states.merge(
        countries,
        on="country_id",
        how="left",
        validate="many_to_one",
    )
    if location_map["country_code"].isna().any():
        raise ValueError("states.csv contains country_id values missing from countries.csv")

    organizations = organizations.merge(
        location_map[["state_id", "country_id", "country_code"]],
        on="state_id",
        how="left",
        validate="many_to_one",
    )
    if organizations["country_code"].isna().any():
        raise ValueError("organizations.csv contains state_id values missing from states.csv")

    return organizations, states, countries


def get_today() -> pd.Timestamp:
    """Return today's local calendar date, normalized to midnight."""
    return pd.Timestamp(date.today())


def parse_date(value: Any, field_name: str) -> pd.Timestamp:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must use YYYY-MM-DD format")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: expected YYYY-MM-DD") from exc
    return pd.Timestamp(parsed.date())


def parse_custom_range(event: dict[str, Any], start_key: str, end_key: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    start_value = event.get(start_key)
    end_value = event.get(end_key)

    if start_value is None and end_value is None:
        return None
    if start_value is None or end_value is None:
        raise ValueError(f"{start_key} and {end_key} must be provided together")

    start = parse_date(start_value, start_key)
    end = parse_date(end_value, end_key)
    if start > end:
        raise ValueError(f"{start_key} cannot be after {end_key}")
    return start, end


def period_key(series: pd.Series, granularity: str) -> pd.Series:
    if granularity == "day":
        return series.dt.strftime("%Y-%m-%d")
    if granularity == "month":
        return series.dt.to_period("M").astype(str)
    raise ValueError(f"Unsupported granularity: {granularity}")


def period_end(period: str, granularity: str) -> pd.Timestamp:
    if granularity == "day":
        return pd.Timestamp(period)
    return pd.Period(period, freq="M").end_time.normalize()


def build_growth_trend(
    organizations: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    granularity: str,
) -> dict[str, list[dict[str, int | str]]]:
    in_window = organizations[
        (organizations["created_date"] >= start)
        & (organizations["created_date"] <= end)
    ].copy()

    if in_window.empty:
        return {"total_organizations": [], "collaborators": []}

    in_window["period"] = period_key(in_window["created_date"], granularity)
    periods = sorted(in_window["period"].unique())

    collaborator_counts = (
        in_window[in_window["is_collaborator_bool"]]
        .groupby("period")
        .size()
        .to_dict()
    )

    total_series: list[dict[str, int | str]] = []
    collaborator_series: list[dict[str, int | str]] = []

    for period in periods:
        as_of = period_end(period, granularity)
        all_time_total = int((organizations["created_date"] <= as_of).sum())
        total_series.append({"period": period, "count": all_time_total})
        collaborator_series.append({
            "period": period,
            "count": int(collaborator_counts.get(period, 0)),
        })

    return {
        "total_organizations": total_series,
        "collaborators": collaborator_series,
    }


def organizations_by_location(
    organizations: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[dict[str, int | str]]:
    in_window = organizations[
        (organizations["created_date"] >= start)
        & (organizations["created_date"] <= end)
    ]

    if in_window.empty:
        return []

    counts = (
        in_window.groupby("country_code")
        .size()
        .reset_index(name="count")
        .sort_values(["count", "country_code"], ascending=[False, True])
        .head(4)
    )

    return [
        {"country": str(row.country_code), "count": int(row.count)}
        for row in counts.itertuples(index=False)
    ]


def fixed_ranges(organizations: pd.DataFrame) -> dict[str, tuple[pd.Timestamp, pd.Timestamp, str]]:
    today = get_today()
    ranges: dict[str, tuple[pd.Timestamp, pd.Timestamp, str]] = {
        "7D": (today - timedelta(days=6), today, "day"),
        "30D": (today - timedelta(days=29), today, "day"),
    }

    current_month = today.to_period("M")
    one_year_start = (current_month - 11).start_time.normalize()
    ranges["1Y"] = (one_year_start, today, "month")

    if organizations.empty:
        ranges["All"] = (today, today, "month")
    else:
        ranges["All"] = (
            organizations["created_date"].min(),
            organizations["created_date"].max(),
            "month",
        )

    return ranges


def _build_success_response(
    organizations: pd.DataFrame,
    growth_custom: tuple[pd.Timestamp, pd.Timestamp] | None,
    location_custom: tuple[pd.Timestamp, pd.Timestamp] | None,
) -> dict[str, Any]:
    ranges = fixed_ranges(organizations)
    response: dict[str, Any] = {}

    for bucket in ("7D", "30D", "1Y", "All"):
        start, end, granularity = ranges[bucket]
        response[bucket] = {
            "growth_trend": build_growth_trend(
                organizations, start, end, granularity
            ),
            "organizations_by_location": organizations_by_location(
                organizations, start, end
            ),
        }

    if growth_custom is None:
        custom_growth = {"total_organizations": [], "collaborators": []}
    else:
        custom_growth = build_growth_trend(
            organizations, growth_custom[0], growth_custom[1], "day"
        )

    custom_location = (
        []
        if location_custom is None
        else organizations_by_location(
            organizations, location_custom[0], location_custom[1]
        )
    )

    response["Custom"] = {
        "growth_trend": custom_growth,
        "organizations_by_location": custom_location,
    }
    return response


def parse_event(event: Any) -> dict[str, Any]:
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise ValueError("Event must be a JSON object")

    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must contain valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Request body must contain a JSON object")
        return parsed
    raise ValueError("Request body must contain a JSON object")


def lambda_handler(event: Any, context: Any = None) -> dict[str, Any]:
    try:
        request = parse_event(event)
        growth_custom = parse_custom_range(request, "start_date", "end_date")
        location_custom = parse_custom_range(
            request, "location_start_date", "location_end_date"
        )
        organizations, _, _ = load_data()

        body = _build_success_response(
            organizations,
            growth_custom,
            location_custom,
        )
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body, separators=(",", ":")),
        }
    except (ValueError, FileNotFoundError) as exc:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(exc)}),
        }


def _print_sample(label: str, event: dict[str, Any]) -> None:
    response = lambda_handler(event)
    print(f"\n=== {label} (status {response['statusCode']}) ===")
    print(json.dumps(json.loads(response["body"]), indent=2))


if __name__ == "__main__":
    _print_sample("No body", {})
    _print_sample(
        "Growth range only",
        {"start_date": "2025-01-01", "end_date": "2025-09-22"},
    )
    _print_sample(
        "Location range only",
        {
            "location_start_date": "2025-01-01",
            "location_end_date": "2025-09-22",
        },
    )
    _print_sample(
        "Both range pairs",
        {
            "start_date": "2025-01-01",
            "end_date": "2025-09-22",
            "location_start_date": "2025-01-01",
            "location_end_date": "2025-09-22",
        },
    )
