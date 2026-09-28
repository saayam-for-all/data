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
BUCKET_PERIOD_FORMAT = {
    "7D": "%Y-%m-%d",
    "30D": "%Y-%m-%d",
    "1Y": "%Y-%m",
    "All": "%Y-%m",
}
CUSTOM_PERIOD_FORMAT = "%Y-%m-%d"
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
    prepared["org_type_normalized"] = prepared["org_type"].map(_normalize_enum)

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
            "SELECT org_id, org_rating, org_type, state_id, created_at FROM organizations",
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
    """Apply the country filter shared by both charts."""
    country_value = str(country or "ALL").strip()
    if country_value.upper() == "ALL":
        return data.copy()

    match = data["country_code"].fillna("").astype(str).str.casefold().eq(
        country_value.casefold()
    )
    if "country_name" in data.columns:
        normalized_country = _normalize_enum(country_value)
        match |= data["country_name"].fillna("").map(_normalize_enum).eq(normalized_country)

    return data[match]


def filter_by_date_range(
    data: pd.DataFrame, start_date: Optional[date], end_date: Optional[date]
) -> pd.DataFrame:
    """Return rows created within an inclusive date window."""
    if start_date is None or end_date is None:
        return data.copy()
    created_dates = data["created_at"].dt.date
    return data[created_dates.between(start_date, end_date)]


def build_rating_distribution(data: pd.DataFrame) -> list[dict[str, Any]]:
    """Count organizations for every rating value actually present in the window."""
    if data.empty:
        return []

    counts = data.dropna(subset=["org_rating"]).groupby("org_rating", sort=True).size()
    return [{"rating": int(rating), "count": int(count)} for rating, count in counts.items()]


def _period_end(period: str, period_format: str) -> pd.Timestamp:
    """First timestamp after the given period, used as a cumulative cutoff."""
    period_start = pd.Timestamp(period)
    if period_format == "%Y-%m-%d":
        return period_start + pd.Timedelta(days=1)
    return period_start + pd.DateOffset(months=1)


def build_organization_mix_trend(
    country_filtered_data: pd.DataFrame,
    start_date: Optional[date],
    end_date: Optional[date],
    period_format: str,
) -> dict[str, list[dict[str, Any]]]:
    """Build cumulative, sparse non_profit/for_profit series for the window.

    Periods are the ones with new organizations inside [start_date, end_date];
    each period's count is the all-time running total for that type as of the
    end of that period, mirroring Growth & Location's growth_trend semantics.
    """
    result: dict[str, list[dict[str, Any]]] = {org_type: [] for org_type in ORGANIZATION_TYPES}

    for org_type in ORGANIZATION_TYPES:
        type_all = country_filtered_data[
            country_filtered_data["org_type_normalized"] == org_type
        ]
        type_windowed = filter_by_date_range(type_all, start_date, end_date)
        if type_windowed.empty:
            continue

        periods = sorted(type_windowed["created_at"].dt.strftime(period_format).unique())
        series = []
        for period in periods:
            period_end = _period_end(period, period_format)
            cumulative = int((type_all["created_at"] < period_end).sum())
            series.append({"period": period, "count": cumulative})
        result[org_type] = series

    return result


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
            custom["rating_distribution"] = build_rating_distribution(
                filter_by_date_range(data, *rating_range)
            )
        if type_range:
            custom["organization_mix_trend"] = build_organization_mix_trend(
                data, *type_range, period_format=CUSTOM_PERIOD_FORMAT
            )
        return {"Custom": custom}

    current_date = today or datetime.now().date()
    bucket_windows: dict[str, tuple[Optional[date], Optional[date]]] = {
        "7D": (current_date - timedelta(days=7), current_date),
        "30D": (current_date - timedelta(days=30), current_date),
        "1Y": (current_date - timedelta(days=365), current_date),
        "All": (None, None),
    }

    response: dict[str, Any] = {}
    for bucket in FIXED_BUCKETS:
        start, end = bucket_windows[bucket]
        response[bucket] = {
            "rating_distribution": build_rating_distribution(
                filter_by_date_range(data, start, end)
            ),
            "organization_mix_trend": build_organization_mix_trend(
                data, start, end, BUCKET_PERIOD_FORMAT[bucket]
            ),
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
        "Country filter": {"country": "USA"},
        "Rating Custom alone": {
            "rating_start_date": "2025-01-01",
            "rating_end_date": "2026-12-31",
        },
        "Type Custom alone": {
            "type_start_date": "2025-01-01",
            "type_end_date": "2026-12-31",
        },
        "Both Custom ranges": {
            "rating_start_date": "2025-01-01",
            "rating_end_date": "2026-12-31",
            "type_start_date": "2025-01-01",
            "type_end_date": "2026-12-31",
        },
    }
    for label, sample_event in sample_events.items():
        print(f"\n=== {label} ===")
        print(json.dumps(lambda_handler(sample_event), indent=2))
