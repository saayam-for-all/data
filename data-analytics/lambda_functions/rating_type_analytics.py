"""Rating & Type Analytics API for the Organization Dashboard (issue #380).

Standalone Lambda for the Rating & Type tab:

  - rating_distribution: window-scoped counts by org_rating (1–5), sparse
  - organization_mix_trend: cumulative non_profit / for_profit time series

No Custom date params → 7D / 30D / 1Y / All plus empty Custom.
Any Custom date pair → Custom-only response (rating and/or type populated).

Mock path: pandas CSVs under MOCK_DATA_DIR (USE_MOCK_DATA=true, default).
Real path: optional psycopg2. Do not commit mock CSVs. Do not deploy for #380.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

try:
    import psycopg2
except ImportError:  # Local mock-data runs must work without Postgres drivers.
    psycopg2 = None


ORGANIZATION_TYPES = ("non_profit", "for_profit")
REQUIRED_ORG_COLUMNS = {"org_id", "org_rating", "org_type", "state_id", "created_at"}


class RequestValidationError(ValueError):
    """Raised for malformed filters or Custom date pairs."""


def _normalize_enum(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def parse_event_body(event: Any) -> Dict[str, Any]:
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise RequestValidationError("Request must be a JSON object.")

    body = event.get("body", None)
    if body is None:
        return event
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        if not body.strip():
            return {}
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RequestValidationError("Request body must contain valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise RequestValidationError("Request body must be a JSON object.")
        return parsed
    raise RequestValidationError("Request body must be a JSON object.")


def build_http_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
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


def validate_date_pair(
    payload: Dict[str, Any], start_key: str, end_key: str
) -> Optional[Tuple[date, date]]:
    start_value = payload.get(start_key)
    end_value = payload.get(end_key)

    if bool(start_value) != bool(end_value):
        raise RequestValidationError(f"{start_key} and {end_key} must be provided together.")
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
    missing = sorted(REQUIRED_ORG_COLUMNS.difference(organizations.columns))
    if missing:
        raise ValueError(f"organizations data is missing columns: {', '.join(missing)}")

    prepared = organizations.copy()
    prepared["created_at"] = pd.to_datetime(prepared["created_at"], errors="coerce")
    prepared = prepared.dropna(subset=["created_at"]).copy()
    prepared["org_rating"] = pd.to_numeric(prepared["org_rating"], errors="coerce")
    prepared["org_type"] = prepared["org_type"].map(_normalize_enum)
    return prepared.reset_index(drop=True)


def load_mock_data(mock_data_dir: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    organizations = pd.read_csv(os.path.join(mock_data_dir, "organizations.csv"))
    states = pd.read_csv(os.path.join(mock_data_dir, "states.csv"))
    countries = pd.read_csv(os.path.join(mock_data_dir, "countries.csv"))
    return _prepare_organizations(organizations), states, countries


def load_postgres_data() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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
        states = pd.read_sql_query("SELECT state_id, country_id FROM states", connection)
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
    if not {"state_id", "country_id"}.issubset(states.columns):
        raise ValueError("states data must include state_id and country_id.")
    if not {"country_id", "country_code"}.issubset(countries.columns):
        raise ValueError("countries data must include country_id and country_code.")

    country_columns = ["country_id", "country_code"]
    if "country_name" in countries.columns:
        country_columns.append("country_name")

    return organizations.merge(
        states[["state_id", "country_id"]].drop_duplicates(subset="state_id"),
        on="state_id",
        how="left",
    ).merge(
        countries[country_columns].drop_duplicates(subset="country_id"),
        on="country_id",
        how="left",
    )


def apply_country_filter(data: pd.DataFrame, country: Any = "ALL") -> pd.DataFrame:
    country_value = str(country or "ALL").strip()
    if country_value.upper() == "ALL":
        return data.copy()

    match = data["country_code"].fillna("").astype(str).str.casefold().eq(country_value.casefold())
    if "country_name" in data.columns:
        normalized = _normalize_enum(country_value)
        match |= data["country_name"].fillna("").map(_normalize_enum).eq(normalized)
    return data.loc[match].copy()


def filter_by_date_range(
    data: pd.DataFrame,
    start_date: Optional[date],
    end_date: Optional[date],
) -> pd.DataFrame:
    if start_date is None and end_date is None:
        return data.copy()
    created_dates = data["created_at"].dt.date
    mask = pd.Series(True, index=data.index)
    if start_date is not None:
        mask &= created_dates >= start_date
    if end_date is not None:
        mask &= created_dates <= end_date
    return data.loc[mask].copy()


def build_rating_distribution(
    data: pd.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    windowed = filter_by_date_range(data, start_date, end_date)
    ratings = windowed.dropna(subset=["org_rating"]).copy()
    if ratings.empty:
        return []

    ratings["org_rating"] = ratings["org_rating"].astype(int)
    ratings = ratings[ratings["org_rating"].between(1, 5)]
    if ratings.empty:
        return []

    counts = ratings.groupby("org_rating", sort=True).size()
    return [{"rating": int(rating), "count": int(count)} for rating, count in counts.items()]


def _period_label(timestamp: pd.Timestamp, monthly: bool) -> str:
    return timestamp.strftime("%Y-%m" if monthly else "%Y-%m-%d")


def _period_end(period_label: str, monthly: bool) -> pd.Timestamp:
    freq = "M" if monthly else "D"
    return pd.Period(period_label, freq=freq).end_time


def _build_type_trend(
    type_data: pd.DataFrame,
    start_date: Optional[date],
    end_date: Optional[date],
    monthly: bool,
) -> List[Dict[str, Any]]:
    """Cumulative all-time counts per type; sparse periods from in-window activity."""
    windowed = filter_by_date_range(type_data, start_date, end_date)
    if windowed.empty:
        return []

    periods = sorted(
        {_period_label(ts, monthly) for ts in windowed["created_at"]}
    )
    all_created = type_data["created_at"]
    return [
        {
            "period": period,
            "count": int((all_created <= _period_end(period, monthly)).sum()),
        }
        for period in periods
    ]


def build_organization_mix_trend(
    data: pd.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    monthly: bool = False,
) -> Dict[str, List[Dict[str, Any]]]:
    return {
        org_type: _build_type_trend(
            data[data["org_type"] == org_type], start_date, end_date, monthly
        )
        for org_type in ORGANIZATION_TYPES
    }


def empty_charts() -> Dict[str, Any]:
    return {
        "rating_distribution": [],
        "organization_mix_trend": {org_type: [] for org_type in ORGANIZATION_TYPES},
    }


def _load_joined_data() -> pd.DataFrame:
    use_mock = os.environ.get("USE_MOCK_DATA", "true").lower() == "true"
    if use_mock:
        mock_data_dir = os.environ.get(
            "MOCK_DATA_DIR",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data"),
        )
        organizations, states, countries = load_mock_data(mock_data_dir)
    else:
        organizations, states, countries = load_postgres_data()
    return join_location_data(organizations, states, countries)


def build_rating_type_response(
    payload: Dict[str, Any],
    data: Optional[pd.DataFrame] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    rating_range = validate_date_pair(payload, "rating_start_date", "rating_end_date")
    type_range = validate_date_pair(payload, "type_start_date", "type_end_date")

    frame = data if data is not None else _load_joined_data()
    frame = apply_country_filter(frame, country=payload.get("country", "ALL"))

    if rating_range or type_range:
        custom = empty_charts()
        if rating_range:
            custom["rating_distribution"] = build_rating_distribution(frame, *rating_range)
        if type_range:
            custom["organization_mix_trend"] = build_organization_mix_trend(
                frame, *type_range, monthly=False
            )
        return {"Custom": custom}

    current = today or datetime.now().date()
    # Inclusive calendar windows: end date is the full reference day.
    bucket_ranges = {
        "7D": (current - timedelta(days=7), current, False),
        "30D": (current - timedelta(days=30), current, False),
        "1Y": (current - timedelta(days=365), current, True),
        "All": (None, None, True),
    }

    response: Dict[str, Any] = {}
    for bucket, (start, end, monthly) in bucket_ranges.items():
        response[bucket] = {
            "rating_distribution": build_rating_distribution(frame, start, end),
            "organization_mix_trend": build_organization_mix_trend(
                frame, start, end, monthly=monthly
            ),
        }
    response["Custom"] = empty_charts()
    return response


def lambda_handler(event: Any, context: Any = None) -> Dict[str, Any]:
    del context
    try:
        payload = parse_event_body(event)
        body = build_rating_type_response(payload)
        return build_http_response(200, body)
    except RequestValidationError as exc:
        return build_http_response(400, {"error": str(exc)})
    except (FileNotFoundError, OSError, KeyError, ValueError, RuntimeError) as exc:
        print(f"Rating & Type analytics failed: {exc}")
        return build_http_response(500, {"error": str(exc)})


if __name__ == "__main__":
    samples = {
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
        "Invalid range": {
            "rating_start_date": "2026-06-30",
            "rating_end_date": "2026-01-01",
        },
    }
    for label, sample in samples.items():
        print(f"\n=== {label}: {json.dumps(sample)} ===")
        print(json.dumps(lambda_handler(sample), indent=2))
