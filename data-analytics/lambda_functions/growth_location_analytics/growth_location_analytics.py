"""CSV-backed analytics for issue #336.

Set MOCK_DATA_DIR to a directory containing organizations.csv, states.csv,
and countries.csv (defaults to mock_data beside this file, as in PR #350).
Keep these CSVs local-only. Deployment requires a pandas Lambda layer configured
by the team; local development uses data-engineering/requirements.txt.

Windows use UTC calendar dates, inclusive of both endpoints. 7D and 30D
include today and the preceding 6/29 days. 1Y covers the current month
through today and the previous 11 calendar months, starting on the first
day of the earliest month. All includes the entire dataset. Custom dates are
independent and must be supplied in complete pairs. Monthly totals stop
at the window's end, even when that end falls in the middle of a month.
"""

import json
import logging
import os
import re
from datetime import date
from pathlib import Path

import pandas as pd

LOGGER = logging.getLogger(__name__)
DateRange = tuple[pd.Timestamp, pd.Timestamp]
BUCKET_GRANULARITY = {
    "7D": "day",
    "30D": "day",
    "1Y": "month",
    "All": "month",
    "Custom": "day",
}


def parse_body(event: dict | None) -> dict:
    """Accept direct invocations and API Gateway JSON object bodies."""
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise ValueError("Event must be an object")
    body = event.get("body", event)
    if body is None or body == "":
        return {}
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("Body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object")
    return body


def parse_range(body: dict, prefix: str = "") -> DateRange | None:
    """Validate one independent date pair, returning inclusive UTC dates."""
    keys = (f"{prefix}start_date", f"{prefix}end_date")
    if not any(key in body for key in keys):
        return None
    parsed = []
    for key in keys:
        value = body.get(key)
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", value
        ):
            raise ValueError(f"{key} is required and must use YYYY-MM-DD")
        try:
            parsed.append(pd.Timestamp(date.fromisoformat(value), tz="UTC"))
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"{key} must be a valid YYYY-MM-DD date") from exc
    if parsed[0] > parsed[1]:
        raise ValueError(f"{keys[0]} must be on or before {keys[1]}")
    return parsed[0], parsed[1]


def load_organizations() -> pd.DataFrame:
    """Join CSVs using their IDs without losing or multiplying rows.

    Local test CSVs must have consistent state-to-country references.
    Country IDs are taken from the data, never mapped to a hardcoded USA ID.
    """
    root = Path(os.environ.get(
        "MOCK_DATA_DIR", str(Path(__file__).parent / "mock_data")
    ))
    organization_columns = {
        "org_id", "state_id", "city_name", "is_collaborator", "created_at"
    }
    try:
        organizations = pd.read_csv(
            root / "organizations.csv", dtype={"state_id": "string"}
        )
    except pd.errors.EmptyDataError:
        organizations = pd.DataFrame(columns=sorted(organization_columns))
    states = pd.read_csv(
        root / "states.csv", dtype={"state_id": "string", "country_id": "string"}
    )
    countries = pd.read_csv(
        root / "countries.csv", dtype={"country_id": "string"}
    )
    for frame, columns in (
        (organizations, organization_columns),
        (states, {"state_id", "state_name", "country_id"}),
        (countries, {"country_id", "country_code"}),
    ):
        if not columns.issubset(frame.columns):
            raise ValueError("CSV is missing required columns")
    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"], format="mixed", utc=True, errors="raise"
    )
    if organizations["created_at"].isna().any():
        raise ValueError("Organizations must have creation dates")
    flags = (
        organizations["is_collaborator"]
        .astype("string").str.strip().str.lower()
    )
    if not flags.isin(["true", "false", "1", "0"]).all():
        raise ValueError("is_collaborator must contain booleans or 0/1")
    organizations["is_collaborator"] = flags.isin(["true", "1"])
    joined = organizations.merge(
        states[["state_id", "country_id"]],
        on="state_id", how="left", validate="many_to_one",
    ).merge(
        countries[["country_id", "country_code"]],
        on="country_id", how="left", validate="many_to_one",
    )
    if joined[["state_id", "country_id", "country_code"]].isna().any().any():
        raise ValueError("Every organization must resolve to a country")
    joined["day"] = joined["created_at"].dt.normalize()
    return joined


def in_window(frame: pd.DataFrame, window: DateRange | None) -> pd.DataFrame:
    """Select inclusive calendar dates, or all rows for an unbounded window."""
    if window is None:
        return frame
    return frame.loc[frame["day"].between(*window)]


def growth_trend(
    frame: pd.DataFrame, window: DateRange | None, monthly: bool
) -> dict:
    """Return aligned periods with all-time totals and period collaborators."""
    selected = in_window(frame, window)
    fmt = "%Y-%m" if monthly else "%Y-%m-%d"
    periods = selected["created_at"].dt.strftime(fmt)
    collaborators = selected.groupby(periods)["is_collaborator"].sum().sort_index()
    # Include history before the window but never later dates in its last month.
    history = frame if window is None else frame.loc[frame["day"] <= window[1]]
    totals = (
        history.groupby(history["created_at"].dt.strftime(fmt))
        .size().sort_index().cumsum()
    )
    return {
        "total_organizations": [
            {"period": period, "count": int(totals.loc[period])}
            for period in collaborators.index
        ],
        "collaborators": [
            {"period": period, "count": int(count)}
            for period, count in collaborators.items()
        ],
    }


def locations(frame: pd.DataFrame, window: DateRange | None) -> list[dict]:
    """Return at most four countries, breaking count ties alphabetically."""
    counts = in_window(frame, window).groupby("country_code").size()
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:4]
    return [{"country": country, "count": int(count)} for country, count in ranked]


def build_analytics(
    frame: pd.DataFrame,
    growth_range: DateRange | None = None,
    location_range: DateRange | None = None,
    today: str | pd.Timestamp | None = None,
) -> dict:
    """Build all five buckets using one reference day for fixed windows."""
    today = (
        pd.Timestamp.now(tz="UTC") if today is None else pd.Timestamp(today)
    )
    today = (
        today.tz_localize("UTC") if today.tzinfo is None
        else today.tz_convert("UTC")
    )
    today = today.normalize()
    windows = {
        "7D": (today - pd.Timedelta(days=6), today),
        "30D": (today - pd.Timedelta(days=29), today),
        "1Y": (
            today.replace(day=1) - pd.DateOffset(months=11), today
        ),
        "All": None,
    }
    result = {
        name: {
            "growth_trend": growth_trend(
                frame, window, BUCKET_GRANULARITY[name] == "month"
            ),
            "organizations_by_location": locations(frame, window),
        }
        for name, window in windows.items()
    }
    result["Custom"] = {
        "growth_trend": (
            growth_trend(frame, growth_range, False) if growth_range else {
                "total_organizations": [], "collaborators": [],
            }
        ),
        "organizations_by_location": (
            locations(frame, location_range) if location_range else []
        ),
    }
    return result


def response(status: int, payload: dict) -> dict:
    """Create a JSON Lambda proxy response."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(payload),
    }


def lambda_handler(event: dict | None, context: object) -> dict:
    """Validate chart ranges and compute analytics from local CSV data."""
    try:
        body = parse_body(event)
        growth_range = parse_range(body)
        location_range = parse_range(body, "location_")
    except ValueError as exc:
        return response(400, {"error": str(exc)})
    try:
        result = build_analytics(
            load_organizations(), growth_range, location_range
        )
        return response(200, result)
    except (
        OSError, ValueError, KeyError,
        pd.errors.ParserError, pd.errors.MergeError,
    ):
        LOGGER.exception("Unable to compute growth and location analytics")
        return response(500, {"error": "Unable to load analytics data"})


if __name__ == "__main__":
    for label, sample in (
        ("Test 1: Empty body", {}),
        ("Test 2: Growth range only", {
            "start_date": "2026-01-01", "end_date": "2026-06-30",
        }),
        ("Test 3: Location range only", {
            "location_start_date": "2025-01-01",
            "location_end_date": "2025-12-31",
        }),
        ("Test 4: Both ranges", {
            "start_date": "2026-01-01", "end_date": "2026-06-30",
            "location_start_date": "2025-01-01",
            "location_end_date": "2025-12-31",
        }),
        ("Test 5: Invalid date range (should be 400)", {
            "start_date": "2026-06-30", "end_date": "2026-01-01",
        }),
    ):
        result = lambda_handler(sample, None)
        print(f"=== {label} ===")
        print(f"Status: {result['statusCode']}")
        print(json.dumps(json.loads(result["body"]), indent=2))
