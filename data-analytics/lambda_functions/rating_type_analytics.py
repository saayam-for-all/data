"""Rating and Type analytics Lambda for organization dashboards.

The function supports two data sources:

* Mock CSVs when ``USE_MOCK_DATA=true``. ``MOCK_DATA_DIR`` must contain
  organizations.csv, states.csv (or state.csv), and countries.csv (or
  country.csv).
* PostgreSQL when ``USE_MOCK_DATA=false``. Connection and column names are
  configurable through environment variables because the repository's local
  seed schema and the issue's analytics schema use different names.

The handler returns an API Gateway-compatible response whose body is a JSON
string. Fixed buckets are returned only when neither custom date pair is
present. Rating and type custom ranges are independent.
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import pandas as pd
except ImportError:  # pragma: no cover - only the PostgreSQL path may run without pandas.
    pd = None

try:
    import psycopg2
except ImportError:  # pragma: no cover - local mock testing does not require psycopg2.
    psycopg2 = None


LOGGER = logging.getLogger(__name__)
UTC = timezone.utc
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")
ORG_TYPES = ("non_profit", "for_profit")


class RequestValidationError(ValueError):
    """Raised for malformed request input that should return HTTP 400."""


DateRange = Tuple[datetime, datetime]


def _env_true(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _require_pandas() -> Any:
    if pd is None:
        raise RuntimeError("pandas is required for analytics processing")
    return pd


def _normalize_token(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().casefold()
    text = re.sub(r"[\s-]+", "_", text)
    return text


def _normalize_org_type(value: Any) -> Optional[str]:
    token = _normalize_token(value)
    if token in {"non_profit", "nonprofit", "not_for_profit"}:
        return "non_profit"
    if token in {"for_profit", "forprofit"}:
        return "for_profit"
    if token in {"", "nan", "none", "null"}:
        return None
    return None


def _find_csv(root: Path, names: Iterable[str]) -> Path:
    for name in names:
        candidate = root / name
        if candidate.is_file():
            return candidate
    expected = ", ".join(names)
    raise FileNotFoundError(f"Could not find any of: {expected} in {root}")


def _validate_csv_columns(frame: Any, required: Iterable[str], filename: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{filename} is missing required columns: {', '.join(missing)}")


def _prepare_mock_data() -> Any:
    pandas = _require_pandas()
    configured_root = os.environ.get("MOCK_DATA_DIR")
    if configured_root:
        root = Path(configured_root)
    else:
        lambda_dir = Path(__file__).resolve().parent
        candidates = (
            lambda_dir / "mock_data",
            lambda_dir.parent / "mock-data-generation",
            lambda_dir.parent / "sql",
        )
        root = next(
            (candidate for candidate in candidates if (candidate / "organizations.csv").is_file()),
            candidates[0],
        )

    organizations_path = _find_csv(root, ("organizations.csv",))
    states_path = _find_csv(root, ("states.csv", "state.csv"))
    countries_path = _find_csv(root, ("countries.csv", "country.csv"))

    organizations = pandas.read_csv(organizations_path)
    states = pandas.read_csv(states_path)
    countries = pandas.read_csv(countries_path)

    _validate_csv_columns(
        organizations,
        ("org_id", "org_rating", "org_type", "state_id", "created_at"),
        organizations_path.name,
    )
    _validate_csv_columns(states, ("state_id", "country_id"), states_path.name)
    _validate_csv_columns(countries, ("country_id",), countries_path.name)
    if "country_code" not in countries.columns and "country_name" not in countries.columns:
        raise ValueError("countries.csv must contain country_code or country_name")

    organizations = organizations.copy()
    states = states.copy()
    countries = countries.copy()

    organizations["state_id"] = organizations["state_id"].astype("string").str.strip()
    states["state_id"] = states["state_id"].astype("string").str.strip()
    states["country_id"] = states["country_id"].astype("string").str.strip()
    countries["country_id"] = countries["country_id"].astype("string").str.strip()

    organizations["org_rating"] = pandas.to_numeric(
        organizations["org_rating"], errors="coerce"
    )
    invalid_ratings = organizations["org_rating"].notna() & ~organizations[
        "org_rating"
    ].between(1, 5)
    if invalid_ratings.any():
        raise ValueError("org_rating must contain integer values from 1 through 5")

    organizations["created_at"] = pandas.to_datetime(
        organizations["created_at"], errors="coerce", utc=True
    )
    if organizations["created_at"].isna().any():
        raise ValueError("created_at must contain valid dates")

    normalized_types = organizations["org_type"].map(_normalize_org_type)
    invalid_types = organizations.loc[
        organizations["org_type"].notna() & normalized_types.isna(), "org_type"
    ].drop_duplicates()
    if not invalid_types.empty:
        values = ", ".join(str(value) for value in invalid_types.tolist())
        raise ValueError(f"Unsupported org_type value(s): {values}")
    organizations["org_type"] = normalized_types

    states_lookup = states[["state_id", "country_id"]]
    countries_lookup = countries[[
        column for column in ("country_id", "country_code", "country_name")
        if column in countries.columns
    ]]
    merged = organizations.merge(
        states_lookup,
        on="state_id",
        how="left",
        validate="many_to_one",
    ).merge(
        countries_lookup,
        on="country_id",
        how="left",
        validate="many_to_one",
    )
    if "country_code" not in merged.columns:
        merged["country_code"] = pandas.NA
    if "country_name" not in merged.columns:
        merged["country_name"] = pandas.NA
    return merged


def _validate_identifier(value: str, name: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid SQL identifier for {name}")
    return value


def _optional_identifier(name: str, default: Optional[str]) -> Optional[str]:
    value = os.environ.get(name, default)
    if value is None or value.strip().lower() in {"", "none", "null"}:
        return None
    return _validate_identifier(value.strip(), name)


def _load_postgres_data() -> Any:
    pandas = _require_pandas()
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required when USE_MOCK_DATA=false")

    schema = _validate_identifier(
        os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms"), "DB_SCHEMA"
    )
    organizations_table = _validate_identifier(
        os.environ.get("ORGANIZATIONS_TABLE", f"{schema}.organizations"),
        "ORGANIZATIONS_TABLE",
    )
    states_table = _validate_identifier(
        os.environ.get("STATES_TABLE", f"{schema}.states"), "STATES_TABLE"
    )
    countries_table = _validate_identifier(
        os.environ.get("COUNTRIES_TABLE", f"{schema}.countries"), "COUNTRIES_TABLE"
    )

    org_id_column = _validate_identifier(
        os.environ.get("ORG_ID_COLUMN", "org_id"), "ORG_ID_COLUMN"
    )
    rating_column = _validate_identifier(
        os.environ.get("ORG_RATING_COLUMN", "org_rating"), "ORG_RATING_COLUMN"
    )
    type_column = _validate_identifier(
        os.environ.get("ORG_TYPE_COLUMN", "org_type"), "ORG_TYPE_COLUMN"
    )
    state_id_column = _validate_identifier(
        os.environ.get("ORG_STATE_ID_COLUMN", "state_id"), "ORG_STATE_ID_COLUMN"
    )
    created_at_column = _validate_identifier(
        os.environ.get("ORG_CREATED_AT_COLUMN", "created_at"), "ORG_CREATED_AT_COLUMN"
    )
    state_key_column = _validate_identifier(
        os.environ.get("STATE_ID_COLUMN", "state_id"), "STATE_ID_COLUMN"
    )
    state_country_column = _validate_identifier(
        os.environ.get("STATE_COUNTRY_ID_COLUMN", "country_id"),
        "STATE_COUNTRY_ID_COLUMN",
    )
    country_key_column = _validate_identifier(
        os.environ.get("COUNTRY_ID_COLUMN", "country_id"), "COUNTRY_ID_COLUMN"
    )
    country_code_column = _optional_identifier("COUNTRY_CODE_COLUMN", "country_code")
    country_name_column = _optional_identifier("COUNTRY_NAME_COLUMN", "country_name")

    select_columns = [
        f"o.{org_id_column} AS org_id",
        f"o.{rating_column} AS org_rating",
        f"o.{type_column} AS org_type",
        f"o.{state_id_column} AS state_id",
        f"o.{created_at_column} AS created_at",
    ]
    if country_code_column:
        select_columns.append(f"c.{country_code_column} AS country_code")
    if country_name_column:
        select_columns.append(f"c.{country_name_column} AS country_name")

    connection_kwargs: Dict[str, Any] = {
        "host": os.environ.get("DB_HOST"),
        "dbname": os.environ.get("DB_NAME"),
        "user": os.environ.get("DB_USER"),
        "password": os.environ.get("DB_PASSWORD"),
        "port": os.environ.get("DB_PORT", "5432"),
    }
    sslmode = os.environ.get("DB_SSLMODE")
    if sslmode:
        connection_kwargs["sslmode"] = sslmode
    missing_connection_values = [
        key for key in ("host", "dbname", "user", "password") if not connection_kwargs[key]
    ]
    if missing_connection_values:
        raise RuntimeError(
            "Missing database environment variables: "
            + ", ".join(f"DB_{key.upper()}" for key in missing_connection_values)
        )

    from psycopg2.extras import RealDictCursor

    connection = psycopg2.connect(**connection_kwargs)
    cursor = connection.cursor(cursor_factory=RealDictCursor)
    try:
        query = f"""
            SELECT {", ".join(select_columns)}
            FROM {organizations_table} AS o
            LEFT JOIN {states_table} AS s
                ON o.{state_id_column} = s.{state_key_column}
            LEFT JOIN {countries_table} AS c
                ON s.{state_country_column} = c.{country_key_column}
        """
        cursor.execute(query)
        rows = cursor.fetchall()
    finally:
        cursor.close()
        connection.close()

    data = pandas.DataFrame(rows)
    if data.empty:
        data = pandas.DataFrame(columns=[
            "org_id", "org_rating", "org_type", "state_id", "created_at",
            "country_code", "country_name",
        ])
    if "country_code" not in data.columns:
        data["country_code"] = pandas.NA
    if "country_name" not in data.columns:
        data["country_name"] = pandas.NA

    # Reuse the same normalization rules as the CSV path without requiring
    # duplicate lookup tables in the database response.
    data["org_rating"] = pandas.to_numeric(data["org_rating"], errors="coerce")
    invalid_ratings = data["org_rating"].notna() & ~data["org_rating"].between(1, 5)
    if invalid_ratings.any():
        raise ValueError("org_rating must contain integer values from 1 through 5")
    data["created_at"] = pandas.to_datetime(data["created_at"], errors="coerce", utc=True)
    if data["created_at"].isna().any():
        raise ValueError("created_at must contain valid dates")
    normalized_types = data["org_type"].map(_normalize_org_type)
    invalid_types = data.loc[data["org_type"].notna() & normalized_types.isna(), "org_type"]
    if not invalid_types.drop_duplicates().empty:
        values = ", ".join(str(value) for value in invalid_types.drop_duplicates().tolist())
        raise ValueError(f"Unsupported org_type value(s): {values}")
    data["org_type"] = normalized_types
    return data


def load_data() -> Any:
    """Load and normalize organization data from CSVs or PostgreSQL."""
    if _env_true("USE_MOCK_DATA", default=True):
        return _prepare_mock_data()
    return _load_postgres_data()


def _parse_date(value: Any, key: str) -> datetime:
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        raise RequestValidationError(f"{key} must be a date in YYYY-MM-DD format")
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise RequestValidationError(f"{key} must be a valid calendar date") from exc


def _parse_range(payload: Dict[str, Any], start_key: str, end_key: str) -> Optional[DateRange]:
    start_present = start_key in payload
    end_present = end_key in payload
    if not start_present and not end_present:
        return None
    if not start_present or not end_present:
        raise RequestValidationError(f"Both {start_key} and {end_key} are required")

    start = _parse_date(payload.get(start_key), start_key)
    end = _parse_date(payload.get(end_key), end_key)
    if start > end:
        raise RequestValidationError(f"{start_key} must not be after {end_key}")
    return start, end + timedelta(days=1)


def _parse_payload(event: Any) -> Dict[str, Any]:
    if not isinstance(event, dict):
        raise RequestValidationError("Request must be a JSON object")

    payload: Any = event.get("body", event)
    if payload is None or payload == "":
        return {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RequestValidationError("Request body must contain valid JSON") from exc
    if not isinstance(payload, dict):
        raise RequestValidationError("Request body must be a JSON object")
    return payload


def _filter_country(data: Any, country: Any) -> Any:
    if country is None or country == "":
        return data
    if not isinstance(country, str):
        raise RequestValidationError("country must be a country name, code, or ALL")
    requested = _normalize_token(country)
    if requested in {"", "all"}:
        return data

    mask = data["country_code"].fillna("").map(_normalize_token) == requested
    if "country_name" in data.columns:
        mask = mask | (data["country_name"].fillna("").map(_normalize_token) == requested)
    return data.loc[mask].copy()


def _select_window(data: Any, window: Optional[DateRange]) -> Any:
    if window is None:
        return data
    start, end = window
    return data.loc[(data["created_at"] >= start) & (data["created_at"] < end)]


def _empty_mix() -> Dict[str, List[Dict[str, Any]]]:
    return {"non_profit": [], "for_profit": []}


def _rating_distribution(data: Any, window: Optional[DateRange]) -> List[Dict[str, int]]:
    selected = _select_window(data, window)
    selected = selected.loc[selected["org_rating"].notna()]
    if selected.empty:
        return []
    counts = selected.groupby("org_rating", sort=True).size()
    return [
        {"rating": int(rating), "count": int(count)}
        for rating, count in counts.items()
    ]


def _period_end(period: str, monthly: bool) -> datetime:
    if monthly:
        start = datetime.strptime(period, "%Y-%m").replace(tzinfo=UTC)
        if start.month == 12:
            return start.replace(year=start.year + 1, month=1)
        return start.replace(month=start.month + 1)
    return datetime.strptime(period, "%Y-%m-%d").replace(tzinfo=UTC) + timedelta(days=1)


def _type_trend(data: Any, window: Optional[DateRange], monthly: bool) -> Dict[str, List[Dict[str, Any]]]:
    selected = _select_window(data, window).copy()
    result = _empty_mix()
    if selected.empty:
        return result

    period_format = "%Y-%m" if monthly else "%Y-%m-%d"
    selected["period"] = selected["created_at"].dt.strftime(period_format)
    valid_data = data.loc[data["org_type"].isin(ORG_TYPES)]

    for org_type in ORG_TYPES:
        selected_type = selected.loc[selected["org_type"] == org_type]
        if selected_type.empty:
            continue
        periods = sorted(selected_type["period"].drop_duplicates().tolist())
        all_type = valid_data.loc[valid_data["org_type"] == org_type]
        series: List[Dict[str, Any]] = []
        for period in periods:
            boundary = _period_end(period, monthly)
            if window is not None:
                boundary = min(boundary, window[1])
            cumulative_count = int((all_type["created_at"] < boundary).sum())
            series.append({"period": period, "count": cumulative_count})
        result[org_type] = series

    return result


def _bucket(data: Any, window: Optional[DateRange], monthly: bool) -> Dict[str, Any]:
    return {
        "rating_distribution": _rating_distribution(data, window),
        "organization_mix_trend": _type_trend(data, window, monthly),
    }


def build_analytics(
    data: Any,
    rating_range: Optional[DateRange] = None,
    type_range: Optional[DateRange] = None,
    today: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build the response after data loading and country filtering."""
    pandas = _require_pandas()
    if today is None:
        current_day = pandas.Timestamp.now(tz="UTC").normalize().to_pydatetime()
    else:
        current = pandas.Timestamp(today)
        if current.tzinfo is None:
            current = current.tz_localize("UTC")
        else:
            current = current.tz_convert("UTC")
        current_day = current.normalize().to_pydatetime()

    end = current_day + timedelta(days=1)
    if rating_range is not None or type_range is not None:
        return {
            "Custom": {
                "rating_distribution": _rating_distribution(data, rating_range)
                if rating_range is not None else [],
                "organization_mix_trend": _type_trend(data, type_range, monthly=False)
                if type_range is not None else _empty_mix(),
            }
        }

    windows: Dict[str, Tuple[Optional[DateRange], bool]] = {
        "7D": ((end - timedelta(days=7), end), False),
        "30D": ((end - timedelta(days=30), end), False),
        "1Y": (((pandas.Timestamp(end) - pandas.DateOffset(years=1)).to_pydatetime(), end), True),
        "All": (None, True),
    }
    result: Dict[str, Any] = {}
    for key, (window, monthly) in windows.items():
        result[key] = _bucket(data, window, monthly)
    result["Custom"] = {"rating_distribution": [], "organization_mix_trend": _empty_mix()}
    return result


def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def lambda_handler(event: Any, context: Any) -> Dict[str, Any]:
    try:
        payload = _parse_payload(event)
        rating_range = _parse_range(payload, "rating_start_date", "rating_end_date")
        type_range = _parse_range(payload, "type_start_date", "type_end_date")
        data = _filter_country(load_data(), payload.get("country", "ALL"))
        return _response(200, build_analytics(data, rating_range, type_range))
    except RequestValidationError as exc:
        return _response(400, {"error": str(exc)})
    except Exception:
        LOGGER.exception("Unable to compute rating and type analytics")
        return _response(500, {"error": "Unable to load analytics data"})


if __name__ == "__main__":
    samples = (
        {},
        {"country": "USA"},
        {"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"},
        {"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"},
        {
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-06-30",
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-12-31",
        },
    )
    for sample in samples:
        print(json.dumps({"event": sample, "response": lambda_handler(sample, None)}, indent=2))
