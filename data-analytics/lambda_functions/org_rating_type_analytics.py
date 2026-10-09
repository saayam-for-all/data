"""Rating & Type analytics for the organization dashboard.

The Lambda supports local CSV-backed development and a PostgreSQL-backed
runtime. Local CSV files are intentionally kept outside version control and
located through ``MOCK_DATA_DIR``.
"""

import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd

try:
    import psycopg2
except ImportError:  # Local mock-data use must work without psycopg2.
    psycopg2 = None


FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
ORGANIZATION_TYPES = ("non_profit", "for_profit")


class RequestValidationError(ValueError):
    """Raised when an analytics request contains invalid filters or dates."""


def _normalize_enum(value: Any) -> str:
    """Normalize enum-like values for comparison without changing output."""
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _parse_event(event: Any) -> dict[str, Any]:
    """Return a request dictionary from direct or API Gateway-style input."""
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise RequestValidationError("Request must be a JSON object.")

    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            parsed = json.loads(body or "{}")
        except json.JSONDecodeError as exc:
            raise RequestValidationError("Request body must contain valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise RequestValidationError("Request body must be a JSON object.")
        return parsed
    raise RequestValidationError("Request body must be a JSON object.")


def _validate_date_pair(
    payload: dict[str, Any], start_key: str, end_key: str
) -> Optional[tuple[date, date]]:
    """Validate one optional, inclusive YYYY-MM-DD date pair."""
    start_value = payload.get(start_key)
    end_value = payload.get(end_key)

    if bool(start_value) != bool(end_value):
        raise RequestValidationError(
            f"{start_key} and {end_key} must be provided together."
        )
    if not start_value:
        return None

    try:
        start_date = datetime.strptime(str(start_value), "%Y-%m-%d").date()
        end_date = datetime.strptime(str(end_value), "%Y-%m-%d").date()
    except ValueError as exc:
        raise RequestValidationError(
            f"{start_key} and {end_key} must use YYYY-MM-DD format."
        ) from exc

    if start_date > end_date:
        raise RequestValidationError(f"{start_key} cannot be after {end_key}.")
    return start_date, end_date


def _prepare_organizations(organizations: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize organization fields used by the analytics."""
    required = {"org_id", "org_rating", "org_type", "state_id", "created_at"}
    missing = sorted(required.difference(organizations.columns))
    if missing:
        raise ValueError(f"organizations data is missing columns: {', '.join(missing)}")

    prepared = organizations.copy()
    prepared["created_at"] = pd.to_datetime(prepared["created_at"], errors="coerce")
    prepared = prepared.dropna(subset=["created_at"])
    prepared["org_rating"] = pd.to_numeric(prepared["org_rating"], errors="coerce")
    prepared["org_type"] = prepared["org_type"].map(_normalize_enum)

    return prepared


def load_mock_data(mock_data_dir: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load the three local CSV tables required by this API."""
    organizations = pd.read_csv(os.path.join(mock_data_dir, "organizations.csv"))
    states = pd.read_csv(os.path.join(mock_data_dir, "states.csv"))
    countries = pd.read_csv(os.path.join(mock_data_dir, "countries.csv"))
    return _prepare_organizations(organizations), states, countries


def load_postgres_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load required columns from PostgreSQL using environment configuration."""
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required when USE_MOCK_DATA is false.")

    connection = psycopg2.connect(
        host=os.environ.get("DB_HOST"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
    )
    try:
        organizations = pd.read_sql_query(
            """
            SELECT org_id, org_rating, org_type, state_id, created_at
            FROM organizations
            """,
            connection,
        )
        states = pd.read_sql_query(
            "SELECT state_id, country_id FROM states", connection
        )
        countries = pd.read_sql_query(
            "SELECT country_id, country_code, country_name FROM countries",
            connection,
        )
    finally:
        connection.close()

    return _prepare_organizations(organizations), states, countries


def join_location_data(
    organizations: pd.DataFrame,
    states: pd.DataFrame,
    countries: pd.DataFrame,
) -> pd.DataFrame:
    """Join organizations to their country through the states table."""
    state_required = {"state_id", "country_id"}
    country_required = {"country_id", "country_code"}
    if not state_required.issubset(states.columns):
        raise ValueError("states data must include state_id and country_id.")
    if not country_required.issubset(countries.columns):
        raise ValueError("countries data must include country_id and country_code.")

    country_columns = ["country_id", "country_code"]
    if "country_name" in countries.columns:
        country_columns.append("country_name")

    return organizations.merge(
        states[["state_id", "country_id"]], on="state_id", how="left"
    ).merge(countries[country_columns], on="country_id", how="left")


def apply_country_filter(data: pd.DataFrame, country: Any = "ALL") -> pd.DataFrame:
    """Apply the country filter shared by both charts on this tab."""
    country_value = str(country or "ALL").strip()
    if country_value.upper() == "ALL":
        return data.copy()

    filtered = data.copy()
    country_match = filtered["country_code"].fillna("").astype(str).str.casefold().eq(
        country_value.casefold()
    )
    if "country_name" in filtered.columns:
        normalized_country = _normalize_enum(country_value)
        country_match |= (
            filtered["country_name"]
            .fillna("")
            .map(_normalize_enum)
            .eq(normalized_country)
        )
    return filtered[country_match]


def filter_by_date_range(
    data: pd.DataFrame, start_date: Optional[date], end_date: Optional[date]
) -> pd.DataFrame:
    """Return rows created within an inclusive date window."""
    if start_date is None or end_date is None:
        return data.copy()
    created_dates = data["created_at"].dt.date
    return data[created_dates.between(start_date, end_date)]


def build_rating_distribution(
    data: pd.DataFrame, start_date: Optional[date] = None, end_date: Optional[date] = None
) -> list[dict[str, Any]]:
    """Count organizations for every rating value actually present in the window."""
    windowed = filter_by_date_range(data, start_date, end_date)
    ratings = windowed.dropna(subset=["org_rating"])
    if ratings.empty:
        return []

    counts = ratings.groupby(ratings["org_rating"].astype(int), sort=True).size()
    return [{"rating": int(rating), "count": int(count)} for rating, count in counts.items()]


def _period_label(timestamp: pd.Timestamp, monthly: bool) -> str:
    return timestamp.strftime("%Y-%m" if monthly else "%Y-%m-%d")


def _period_boundary(period_label: str, monthly: bool) -> pd.Timestamp:
    boundary = pd.Timestamp(period_label)
    return boundary + (pd.DateOffset(months=1) if monthly else pd.Timedelta(days=1))


def _build_type_trend(
    type_data: pd.DataFrame,
    start_date: Optional[date],
    end_date: Optional[date],
    monthly: bool,
) -> list[dict[str, Any]]:
    """Cumulative, sparse counts of one organization type across periods.

    Each period's count is the all-time running total up to that period's
    boundary (capped to the window end for fixed/Custom buckets), matching
    growth_trend's total_organizations semantics. Periods absent from the
    window are omitted rather than zero-filled.
    """
    if start_date is not None and end_date is not None:
        window_end_boundary = pd.Timestamp(end_date) + pd.Timedelta(days=1)
        selected = filter_by_date_range(type_data, start_date, end_date)
    else:
        window_end_boundary = None
        selected = type_data

    if selected.empty:
        return []

    labels = selected["created_at"].apply(lambda ts: _period_label(ts, monthly))
    timestamps = type_data["created_at"].sort_values()

    result = []
    for period in sorted(labels.unique()):
        boundary = _period_boundary(period, monthly)
        if window_end_boundary is not None:
            boundary = min(boundary, window_end_boundary)
        result.append({"period": period, "count": int(timestamps.searchsorted(boundary))})
    return result


def build_organization_mix_trend(
    data: pd.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    monthly: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Per-type cumulative time series, grouped like growth_trend."""
    return {
        org_type: _build_type_trend(
            data[data["org_type"] == org_type], start_date, end_date, monthly
        )
        for org_type in ORGANIZATION_TYPES
    }


def _empty_charts() -> dict[str, Any]:
    return {
        "rating_distribution": [],
        "organization_mix_trend": {org_type: [] for org_type in ORGANIZATION_TYPES},
    }


def build_response(payload: dict[str, Any], today: Optional[date] = None) -> dict[str, Any]:
    """Build either the fixed-bucket response or the Custom-only response."""
    rating_range = _validate_date_pair(payload, "rating_start_date", "rating_end_date")
    type_range = _validate_date_pair(payload, "type_start_date", "type_end_date")

    use_mock_data = os.environ.get("USE_MOCK_DATA", "true").lower() == "true"
    if use_mock_data:
        mock_data_dir = os.environ.get("MOCK_DATA_DIR")
        if not mock_data_dir:
            raise RuntimeError("MOCK_DATA_DIR must be set when USE_MOCK_DATA is true.")
        organizations, states, countries = load_mock_data(mock_data_dir)
    else:
        organizations, states, countries = load_postgres_data()

    data = join_location_data(organizations, states, countries)
    data = apply_country_filter(data, country=payload.get("country", "ALL"))

    if rating_range or type_range:
        custom = _empty_charts()
        if rating_range:
            custom["rating_distribution"] = build_rating_distribution(data, *rating_range)
        if type_range:
            custom["organization_mix_trend"] = build_organization_mix_trend(
                data, *type_range, monthly=False
            )
        return {"Custom": custom}

    current_date = today or datetime.now().date()
    bucket_ranges = {
        "7D": (current_date - timedelta(days=7), current_date, False),
        "30D": (current_date - timedelta(days=30), current_date, False),
        "1Y": (current_date - timedelta(days=365), current_date, True),
        "All": (None, None, True),
    }

    response = {}
    for bucket, (start, end, monthly) in bucket_ranges.items():
        response[bucket] = {
            "rating_distribution": build_rating_distribution(data, start, end),
            "organization_mix_trend": build_organization_mix_trend(data, start, end, monthly),
        }
    response["Custom"] = _empty_charts()
    return response


def lambda_handler(event: Any, context: Any = None) -> dict[str, Any]:
    """AWS Lambda entry point for Rating & Type analytics."""
    del context
    try:
        payload = _parse_event(event)
        response = build_response(payload)
        return {"statusCode": 200, "body": json.dumps(response)}
    except RequestValidationError as exc:
        return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
        return {"statusCode": 500, "body": json.dumps({"error": str(exc)})}


if __name__ == "__main__":
    sample_events = {
        "No filters": {},
        "Country": {"country": "USA"},
        "Rating Custom": {
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-06-30",
        },
        "Type Custom": {
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-12-31",
        },
        "Both Custom ranges": {
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-06-30",
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-12-31",
        },
    }
    for label, sample_event in sample_events.items():
        print(f"\n=== {label} ===")
        print(json.dumps(lambda_handler(sample_event), indent=2))
