"""CSV-backed analytics for issue #380 (Organization Analytics: Rating & Type tab).

Set MOCK_DATA_DIR to a directory containing organizations.csv, states.csv,
and countries.csv (defaults to mock_data beside this file). Keep these CSVs
local-only. Deployment requires a pandas Lambda layer configured by the
team; local development uses data-engineering/requirements.txt.

Two independent charts are served:
  - rating_distribution: organization counts grouped by org_rating (1-5).
    Categorical, so ratings with zero organizations are simply absent
    (no zero-filling).
  - organization_mix_trend: cumulative organization counts by org_type
    over time, grouped daily for 7D/30D/Custom and monthly for 1Y/All.

Windows use UTC calendar dates, inclusive of both endpoints. 7D and 30D
include today and the preceding 6/29 days. 1Y covers the current month
through today and the previous 11 calendar months, starting on the first
day of the earliest month. All includes the entire dataset.

Calling with no rating_/type_ date params returns all four fixed buckets
(7D/30D/1Y/All) plus an empty Custom entry. Supplying rating_start_date/
rating_end_date and/or type_start_date/type_end_date instead returns only
Custom, with each chart populated independently of the other -- a request
can supply one pair without the other. Custom's organization_mix_trend is
always grouped daily, matching 7D/30D.

An optional country_code (ISO alpha-3, as stored in countries.csv) filters
organizations via organizations.state_id -> states.country_id ->
countries.country_code before either chart is computed. There is no
organization_type filter: it would be redundant with organization_mix_trend.
"""

import json
import logging
import os
import re
from datetime import date
from pathlib import Path

import pandas as pd

try:
    import psycopg2  # noqa: F401  (reserved for future Postgres support)
except ImportError:
    psycopg2 = None

LOGGER = logging.getLogger(__name__)
DateRange = tuple[pd.Timestamp, pd.Timestamp]
BUCKET_GRANULARITY = {
    "7D": "day",
    "30D": "day",
    "1Y": "month",
    "All": "month",
}
MIN_RATING = 1
MAX_RATING = 5
WINDOW_DAYS = {"7D": 7, "30D": 30}
TRAILING_MONTHS = 12  # "1Y": the current month plus this many preceding it


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


def parse_range(body: dict, prefix: str) -> DateRange | None:
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


def parse_country_code(body: dict) -> str | None:
    """Validate the optional country_code filter."""
    if "country_code" not in body:
        return None
    value = body.get("country_code")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("country_code must be a non-empty string")
    return value.strip().upper()


def load_organizations() -> pd.DataFrame:
    """Join CSVs using their IDs without losing or multiplying rows.

    Local test CSVs must have consistent state-to-country references.
    Country codes are taken from the data, never mapped to a hardcoded ID.
    """
    root = Path(os.environ.get(
        "MOCK_DATA_DIR", str(Path(__file__).parent / "mock_data")
    ))
    organization_columns = {"org_id", "org_rating", "org_type", "state_id", "created_at"}
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
        (states, {"state_id", "country_id"}),
        (countries, {"country_id", "country_code"}),
    ):
        if not columns.issubset(frame.columns):
            raise ValueError("CSV is missing required columns")

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"], format="mixed", utc=True, errors="raise"
    )
    if organizations["created_at"].isna().any():
        raise ValueError("Organizations must have creation dates")

    ratings = pd.to_numeric(organizations["org_rating"], errors="coerce")
    if ratings.isna().any() or not ratings.between(MIN_RATING, MAX_RATING).all():
        raise ValueError(
            f"org_rating must be an integer between {MIN_RATING} and {MAX_RATING}"
        )
    organizations["org_rating"] = ratings.astype("int64")

    org_types = organizations["org_type"].astype("string").str.strip()
    if org_types.eq("").any() or org_types.isna().any():
        raise ValueError("org_type must not be blank")
    organizations["org_type"] = org_types

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


def filter_country(frame: pd.DataFrame, country_code: str | None) -> pd.DataFrame:
    """Restrict to one country, or return every row when none is given."""
    if country_code is None:
        return frame
    return frame.loc[frame["country_code"] == country_code]


def in_window(frame: pd.DataFrame, window: DateRange | None) -> pd.DataFrame:
    """Select inclusive calendar dates, or all rows for an unbounded window."""
    if window is None:
        return frame
    return frame.loc[frame["day"].between(*window)]


def rating_distribution(frame: pd.DataFrame, window: DateRange | None) -> list[dict]:
    """Return organization counts per star rating present in the window."""
    counts = in_window(frame, window).groupby("org_rating").size().sort_index()
    return [
        {"rating": int(rating), "count": int(count)}
        for rating, count in counts.items()
    ]


def organization_mix_trend(
    frame: pd.DataFrame, window: DateRange | None, monthly: bool
) -> list[dict]:
    """Return cumulative per-type counts for each period touched by the window."""
    history = frame if window is None else frame.loc[frame["day"] <= window[1]]
    if history.empty:
        return []
    fmt = "%Y-%m" if monthly else "%Y-%m-%d"
    history_periods = history["created_at"].dt.strftime(fmt)
    cumulative = (
        history.groupby([history_periods, "org_type"])
        .size().unstack(fill_value=0).sort_index().cumsum()
    )
    selected = in_window(frame, window)
    window_periods = sorted(selected["created_at"].dt.strftime(fmt).unique())
    return [
        {"period": period, "org_type": org_type, "count": int(count)}
        for period in window_periods
        for org_type, count in cumulative.loc[period].items()
    ]


def build_default(frame: pd.DataFrame, today: str | pd.Timestamp | None = None) -> dict:
    """Build the four fixed buckets plus an empty Custom entry."""
    today = pd.Timestamp.now(tz="UTC") if today is None else pd.Timestamp(today)
    today = today.tz_localize("UTC") if today.tzinfo is None else today.tz_convert("UTC")
    today = today.normalize()
    windows = {
        "7D": (today - pd.Timedelta(days=WINDOW_DAYS["7D"] - 1), today),
        "30D": (today - pd.Timedelta(days=WINDOW_DAYS["30D"] - 1), today),
        "1Y": (
            today.replace(day=1) - pd.DateOffset(months=TRAILING_MONTHS - 1), today
        ),
        "All": None,
    }
    result = {
        name: {
            "rating_distribution": rating_distribution(frame, window),
            "organization_mix_trend": organization_mix_trend(
                frame, window, BUCKET_GRANULARITY[name] == "month"
            ),
        }
        for name, window in windows.items()
    }
    result["Custom"] = {"rating_distribution": [], "organization_mix_trend": []}
    return result


def build_custom(
    frame: pd.DataFrame,
    rating_range: DateRange | None,
    type_range: DateRange | None,
) -> dict:
    """Build Custom with each chart populated independently of the other."""
    return {
        "rating_distribution": (
            rating_distribution(frame, rating_range) if rating_range else []
        ),
        "organization_mix_trend": (
            organization_mix_trend(frame, type_range, monthly=False)
            if type_range else []
        ),
    }


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
        rating_range = parse_range(body, "rating_")
        type_range = parse_range(body, "type_")
        country_code = parse_country_code(body)
    except ValueError as exc:
        return response(400, {"error": str(exc)})

    try:
        frame = filter_country(load_organizations(), country_code)
        if rating_range or type_range:
            result = {"Custom": build_custom(frame, rating_range, type_range)}
        else:
            result = build_default(frame)
        return response(200, result)
    except (
        OSError, ValueError, KeyError,
        pd.errors.ParserError, pd.errors.MergeError,
    ):
        LOGGER.exception("Unable to compute rating and type analytics")
        return response(500, {"error": "Unable to load analytics data"})


if __name__ == "__main__":
    for label, sample in (
        ("Test 1: Empty body", {}),
        ("Test 2: Rating range only", {
            "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30",
        }),
        ("Test 3: Type range only", {
            "type_start_date": "2025-01-01", "type_end_date": "2025-12-31",
        }),
        ("Test 4: Both ranges", {
            "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30",
            "type_start_date": "2025-01-01", "type_end_date": "2025-12-31",
        }),
        ("Test 5: Country filter", {"country_code": "USA"}),
        ("Test 6: Inverted date range (should be 400)", {
            "rating_start_date": "2026-06-30", "rating_end_date": "2026-01-01",
        }),
        ("Test 7: Malformed date string (should be 400)", {
            "type_start_date": "06/30/2026", "type_end_date": "2026-12-31",
        }),
        ("Test 8: One-sided date pair (should be 400)", {
            "rating_start_date": "2026-01-01",
        }),
        ("Test 9: Blank country_code (should be 400)", {"country_code": "  "}),
        ("Test 10: Country filter combined with both ranges", {
            "country_code": "USA",
            "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30",
            "type_start_date": "2025-01-01", "type_end_date": "2025-12-31",
        }),
    ):
        result = lambda_handler(sample, None)
        print(f"=== {label} ===")
        print(f"Status: {result['statusCode']}")
        print(json.dumps(json.loads(result["body"]), indent=2))
