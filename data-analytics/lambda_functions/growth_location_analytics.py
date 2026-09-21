"""Growth & Location Analytics API for the Organization Dashboard (issue #336).

Standalone Lambda that returns both Growth Trend and Organizations by Location
charts for all five time buckets (7D / 30D / 1Y / All / Custom) in one response
so the frontend can switch either chart's range without another API call.

Data is loaded with pandas from organizations.csv / states.csv / countries.csv
under MOCK_DATA_DIR (default: a mock_data/ folder next to this file). Do not
commit those CSVs. Do not deploy this function directly to AWS as part of #336.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

REQUIRED_ORG_COLUMNS = ["org_id", "state_id", "city_name", "is_collaborator", "created_at"]
REQUIRED_STATE_COLUMNS = ["state_id", "state_name", "country_id"]
REQUIRED_COUNTRY_COLUMNS = ["country_id", "country_code"]

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
BUCKET_GRANULARITY = {
    "7D": "day",
    "30D": "day",
    "1Y": "month",
    "All": "month",
    "Custom": "day",
}
TOP_N_LOCATIONS = 4


class InvalidDateRangeError(ValueError):
    """Raised when a Custom date pair is malformed or inverted."""


def mock_data_dir() -> str:
    return os.environ.get(
        "MOCK_DATA_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data"),
    )


def parse_event_body(event: Any) -> Dict[str, Any]:
    if not event:
        return {}
    if not isinstance(event, dict):
        return {}

    body = event.get("body", None)
    if body is None:
        # Direct/local invocation may pass the payload at the top level.
        if any(
            key in event
            for key in ("start_date", "end_date", "location_start_date", "location_end_date")
        ):
            return event
        return {}

    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        if not body.strip():
            return {}
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise InvalidDateRangeError("Request body must be valid JSON") from exc
        return parsed if isinstance(parsed, dict) else {}
    return {}


def build_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(body),
    }


def _read_required_csv(data_dir: str, filename: str, required_columns: List[str]) -> pd.DataFrame:
    path = os.path.join(data_dir, filename)
    frame = pd.read_csv(path, dtype=str)
    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{filename} is missing required column(s): {', '.join(missing)}")
    return frame


def load_organizations(data_dir: Optional[str] = None) -> pd.DataFrame:
    """Load and join organizations → states → countries; return typed rows."""
    data_dir = data_dir or mock_data_dir()

    organizations = _read_required_csv(data_dir, "organizations.csv", REQUIRED_ORG_COLUMNS)
    states = _read_required_csv(data_dir, "states.csv", REQUIRED_STATE_COLUMNS)
    countries = _read_required_csv(data_dir, "countries.csv", REQUIRED_COUNTRY_COLUMNS)

    states = states[["state_id", "country_id"]].drop_duplicates(subset="state_id")
    countries = countries[["country_id", "country_code"]].drop_duplicates(subset="country_id")

    merged = organizations.merge(states, on="state_id", how="left")
    merged = merged.merge(countries, on="country_id", how="left")
    merged["country_code"] = merged["country_code"].fillna("Unknown")

    merged["is_collaborator"] = (
        merged["is_collaborator"].astype(str).str.strip().str.upper().isin({"TRUE", "1", "YES"})
    )

    created_at = pd.to_datetime(merged["created_at"], errors="coerce")
    for org_id in merged.loc[created_at.isna(), "org_id"]:
        print(f"Skipping organization {org_id}: unparseable created_at")
    merged = merged.loc[created_at.notna()].copy()
    merged["created_at"] = created_at.loc[created_at.notna()]
    return merged.reset_index(drop=True)


def _window_mask(organizations: pd.DataFrame, window_start, window_end) -> pd.Series:
    mask = pd.Series(True, index=organizations.index)
    if window_start is not None:
        mask &= organizations["created_at"] >= window_start
    if window_end is not None:
        mask &= organizations["created_at"] <= window_end
    return mask


def fixed_window(bucket: str, reference_date: pd.Timestamp) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    if bucket == "7D":
        return reference_date - pd.Timedelta(days=7), reference_date
    if bucket == "30D":
        return reference_date - pd.Timedelta(days=30), reference_date
    if bucket == "1Y":
        return reference_date - pd.DateOffset(years=1), reference_date
    return None, None  # All


def parse_custom_range(
    start_value: Any,
    end_value: Any,
    start_field: str,
    end_field: str,
) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    if start_value in (None, "") and end_value in (None, ""):
        return None, None
    if start_value in (None, "") or end_value in (None, ""):
        raise InvalidDateRangeError(f"Both {start_field} and {end_field} are required together")

    start = pd.to_datetime(start_value, errors="coerce")
    end = pd.to_datetime(end_value, errors="coerce")
    if pd.isna(start) or pd.isna(end):
        raise InvalidDateRangeError(
            f"{start_field} and {end_field} must be valid dates (e.g. YYYY-MM-DD)"
        )
    if start > end:
        raise InvalidDateRangeError(f"{start_field} must not be after {end_field}")

    # Inclusive end-of-day so a same-day Custom range still captures that day.
    end = end + pd.Timedelta(hours=23, minutes=59, seconds=59)
    return start, end


def _period_labels(created_at: pd.Series, granularity: str) -> pd.Series:
    fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m"
    return created_at.dt.strftime(fmt)


def _period_end(period: str, granularity: str) -> pd.Timestamp:
    freq = "D" if granularity == "day" else "M"
    return pd.Period(period, freq=freq).end_time


def build_growth_trend(
    organizations: pd.DataFrame,
    window_start,
    window_end,
    granularity: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """Growth Trend for one bucket.

    total_organizations: absolute all-time running total as of each period
    (never reset at the bucket window start).

    collaborators: per-period count inside the window only (not cumulative).

    Periods are shared and sparse: only periods with at least one organization
    created inside the window appear.
    """
    windowed = organizations.loc[_window_mask(organizations, window_start, window_end)]
    if windowed.empty:
        return {"total_organizations": [], "collaborators": []}

    period_key = _period_labels(windowed["created_at"], granularity)
    periods = sorted(period_key.unique())

    all_created_at = organizations["created_at"]
    total_organizations = [
        {
            "period": period,
            "count": int((all_created_at <= _period_end(period, granularity)).sum()),
        }
        for period in periods
    ]

    collaborator_counts = period_key[windowed["is_collaborator"]].value_counts()
    collaborators = [
        {"period": period, "count": int(collaborator_counts.get(period, 0))}
        for period in periods
    ]
    return {"total_organizations": total_organizations, "collaborators": collaborators}


def build_organizations_by_location(
    organizations: pd.DataFrame,
    window_start,
    window_end,
) -> List[Dict[str, Any]]:
    """Top 4 countries by in-window organization count (no Other, no percentage)."""
    windowed = organizations.loc[_window_mask(organizations, window_start, window_end)]
    if windowed.empty:
        return []

    counts = (
        windowed.groupby("country_code", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(["count", "country_code"], ascending=[False, True])
        .head(TOP_N_LOCATIONS)
    )
    return [
        {"country": str(row["country_code"]), "count": int(row["count"])}
        for _, row in counts.iterrows()
    ]


def _build_bucket(
    organizations: pd.DataFrame,
    window_start,
    window_end,
    granularity: str,
) -> Dict[str, Any]:
    return {
        "growth_trend": build_growth_trend(organizations, window_start, window_end, granularity),
        "organizations_by_location": build_organizations_by_location(
            organizations, window_start, window_end
        ),
    }


def build_growth_location_response(
    organizations: pd.DataFrame,
    request_body: Dict[str, Any],
    reference_date: Optional[pd.Timestamp] = None,
) -> Dict[str, Any]:
    reference_date = (
        reference_date if reference_date is not None else pd.Timestamp.now().normalize()
    )

    response: Dict[str, Any] = {}
    for bucket in FIXED_BUCKETS:
        window_start, window_end = fixed_window(bucket, reference_date)
        response[bucket] = _build_bucket(
            organizations, window_start, window_end, BUCKET_GRANULARITY[bucket]
        )

    growth_start, growth_end = parse_custom_range(
        request_body.get("start_date"),
        request_body.get("end_date"),
        "start_date",
        "end_date",
    )
    location_start, location_end = parse_custom_range(
        request_body.get("location_start_date"),
        request_body.get("location_end_date"),
        "location_start_date",
        "location_end_date",
    )

    custom_growth = (
        build_growth_trend(organizations, growth_start, growth_end, BUCKET_GRANULARITY["Custom"])
        if growth_start is not None
        else {"total_organizations": [], "collaborators": []}
    )
    custom_location = (
        build_organizations_by_location(organizations, location_start, location_end)
        if location_start is not None
        else []
    )
    response["Custom"] = {
        "growth_trend": custom_growth,
        "organizations_by_location": custom_location,
    }
    return response


def lambda_handler(event, context=None):
    try:
        request_body = parse_event_body(event)
    except InvalidDateRangeError as error:
        return build_response(400, {"error": str(error)})

    try:
        organizations = load_organizations()
    except (OSError, ValueError) as error:
        print(f"Failed to load organizations data: {error}")
        return build_response(500, {"error": "Failed to load organizations data"})

    try:
        body = build_growth_location_response(organizations, request_body)
    except InvalidDateRangeError as error:
        return build_response(400, {"error": str(error)})

    return build_response(200, body)


if __name__ == "__main__":
    sample_events = [
        {},
        {"start_date": "2026-01-01", "end_date": "2026-06-30"},
        {"location_start_date": "2025-01-01", "location_end_date": "2025-12-31"},
        {
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "location_start_date": "2025-01-01",
            "location_end_date": "2025-12-31",
        },
        {"start_date": "2026-06-30", "end_date": "2026-01-01"},
    ]

    for sample in sample_events:
        print(f"\n=== payload: {json.dumps(sample)} ===")
        result = lambda_handler(sample, None)
        print(f"statusCode: {result['statusCode']}")
        print(json.dumps(json.loads(result["body"]), indent=2))
