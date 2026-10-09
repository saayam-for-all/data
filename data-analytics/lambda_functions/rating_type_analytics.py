"""Rating & Type analytics for the Organization Dashboard (Issue #380).

Set USE_MOCK_DATA=true and MOCK_DATA_DIR for local CSV runs. The PostgreSQL
path uses DB_DSN and DB_SCHEMA; no connection details are stored in source.
"""

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

try:
    import psycopg2
except ImportError:  # Local CSV runs do not need a PostgreSQL driver.
    psycopg2 = None


HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}
SERIES = ("non_profit", "for_profit")
FIXED_BUCKETS = ("7D", "30D", "1Y", "All")


class InvalidFilter(ValueError):
    """An invalid request filter that should receive a 400 response."""


def response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """Return an API Gateway proxy response."""
    return {"statusCode": status_code, "headers": HEADERS, "body": json.dumps(body)}


def parse_event(event: dict[str, Any] | None) -> dict[str, Any]:
    """Accept a direct payload or a JSON object in an API Gateway body."""
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise InvalidFilter("Request must be a JSON object.")
    if "body" not in event or event["body"] is None:
        return event
    body = event["body"]
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise InvalidFilter("Body must contain valid JSON.") from exc
    if not isinstance(body, dict):
        raise InvalidFilter("Body must be a JSON object.")
    return body


def parse_country(payload: dict[str, Any]) -> str:
    """Validate the optional country name or code filter."""
    country = payload.get("country", "ALL")
    if not isinstance(country, str) or not country.strip():
        raise InvalidFilter("country must be a non-empty string.")
    return country.strip().upper()


def parse_date_pair(payload: dict[str, Any], prefix: str) -> tuple[date, date] | None:
    """Validate one independently optional inclusive Custom date range."""
    start_key, end_key = f"{prefix}_start_date", f"{prefix}_end_date"
    if start_key not in payload and end_key not in payload:
        return None
    start_value, end_value = payload.get(start_key), payload.get(end_key)
    for key, value in ((start_key, start_value), (end_key, end_value)):
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise InvalidFilter(f"{key} must be a date in YYYY-MM-DD format.")
    try:
        start, end = date.fromisoformat(start_value), date.fromisoformat(end_value)
    except ValueError as exc:
        raise InvalidFilter(f"{prefix} dates must be valid calendar dates.") from exc
    if start > end:
        raise InvalidFilter(f"{start_key} must not be after {end_key}.")
    return start, end


def empty_bucket() -> dict[str, Any]:
    """Create independent empty chart containers for a response bucket."""
    return {
        "rating_distribution": [],
        "organization_mix_trend": {"non_profit": [], "for_profit": []},
    }


def load_mock_records() -> pd.DataFrame:
    """Join organizations, states, and countries from local mock CSV files."""
    data_dir = os.environ.get("MOCK_DATA_DIR")
    if not data_dir:
        raise RuntimeError("MOCK_DATA_DIR is required when USE_MOCK_DATA=true")

    organizations = pd.read_csv(os.path.join(data_dir, "organizations.csv"), dtype=str)
    states = pd.read_csv(os.path.join(data_dir, "states.csv"), dtype=str)
    countries = pd.read_csv(os.path.join(data_dir, "countries.csv"), dtype=str)
    required = (
        (organizations, {"org_id", "org_rating", "org_type", "state_id", "created_at"}),
        (states, {"state_id", "country_id"}),
        (countries, {"country_id"}),
    )
    for frame, columns in required:
        missing = columns - set(frame.columns)
        if missing:
            raise ValueError(f"Mock CSV is missing columns: {sorted(missing)}")
    if not ({"country_code", "country_name"} & set(countries.columns)):
        raise ValueError("countries.csv requires country_code or country_name")
    for column in ("country_code", "country_name"):
        if column not in countries:
            countries[column] = ""

    joined = organizations.merge(
        states[["state_id", "country_id"]].drop_duplicates("state_id"),
        on="state_id", how="left", validate="many_to_one",
    ).merge(
        countries[["country_id", "country_code", "country_name"]].drop_duplicates("country_id"),
        on="country_id", how="left", validate="many_to_one",
    )
    return joined[["org_rating", "org_type", "created_at", "country_code", "country_name"]]


def load_postgres_records() -> pd.DataFrame:
    """Read the same fields from PostgreSQL using an optional psycopg2 import."""
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required when USE_MOCK_DATA is false")
    dsn = os.environ.get("DB_DSN")
    if not dsn:
        raise RuntimeError("DB_DSN is required when USE_MOCK_DATA is false")
    schema = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
        raise RuntimeError("DB_SCHEMA must be a simple SQL identifier")

    query = f"""
        SELECT o.org_rating, o.org_type, o.created_at,
               c.country_code, c.country_name
        FROM {schema}.organizations AS o
        LEFT JOIN {schema}.states AS s ON s.state_id = o.state_id
        LEFT JOIN {schema}.countries AS c ON c.country_id = s.country_id
    """
    connection = psycopg2.connect(dsn)
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()
    return pd.DataFrame(
        rows,
        columns=["org_rating", "org_type", "created_at", "country_code", "country_name"],
    )


def normalize_records(records: pd.DataFrame, country: str) -> pd.DataFrame:
    """Normalize source values and apply the shared country filter."""
    frame = records.copy()
    frame["created_at"] = pd.to_datetime(frame["created_at"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["created_at"])
    frame["org_rating"] = pd.to_numeric(frame["org_rating"], errors="coerce")
    org_type = frame["org_type"].fillna("").astype(str).str.lower()
    org_type = org_type.str.strip().str.replace(r"[\s-]+", "_", regex=True)
    frame["org_type"] = org_type.replace({"nonprofit": "non_profit", "forprofit": "for_profit"})
    if country != "ALL":
        code = frame["country_code"].fillna("").astype(str).str.upper().str.strip()
        name = frame["country_name"].fillna("").astype(str).str.upper().str.strip()
        frame = frame.loc[(code == country) | (name == country)].copy()
    return frame


def date_bounds(start: date | None, end: date) -> tuple[pd.Timestamp | None, pd.Timestamp]:
    """Convert inclusive calendar dates to a half-open UTC timestamp range."""
    lower = pd.Timestamp(start, tz="UTC") if start is not None else None
    upper = pd.Timestamp(end + timedelta(days=1), tz="UTC")
    return lower, upper


def rating_distribution(frame: pd.DataFrame, start: date | None, end: date) -> list[dict[str, int]]:
    """Count only integer ratings from 1 through 5 present in the window."""
    lower, upper = date_bounds(start, end)
    selected = frame.loc[frame["created_at"] < upper]
    if lower is not None:
        selected = selected.loc[selected["created_at"] >= lower]
    ratings = selected["org_rating"]
    ratings = ratings.loc[ratings.between(1, 5) & (ratings % 1 == 0)]
    counts = ratings.astype(int).value_counts().sort_index()
    return [{"rating": int(rating), "count": int(count)} for rating, count in counts.items()]


def organization_mix_trend(
    frame: pd.DataFrame, start: date | None, end: date, monthly: bool,
) -> dict[str, list[dict[str, Any]]]:
    """Return sparse per-type periods with all-time cumulative counts."""
    lower, upper = date_bounds(start, end)
    typed = frame.loc[frame["org_type"].isin(SERIES) & (frame["created_at"] < upper)]
    visible = typed if lower is None else typed.loc[typed["created_at"] >= lower]
    baseline = typed.iloc[0:0] if lower is None else typed.loc[typed["created_at"] < lower]
    pattern = "%Y-%m" if monthly else "%Y-%m-%d"
    result: dict[str, list[dict[str, Any]]] = {}
    for org_type in SERIES:
        rows = visible.loc[visible["org_type"] == org_type]
        periods = rows["created_at"].dt.strftime(pattern).value_counts().sort_index()
        running = periods.cumsum() + int((baseline["org_type"] == org_type).sum())
        result[org_type] = [
            {"period": period, "count": int(count)} for period, count in running.items()
        ]
    return result


def utc_today() -> date:
    """Return the current UTC calendar date (patchable in local tests)."""
    return datetime.now(timezone.utc).date()


def fixed_window(bucket: str, today: date) -> tuple[date | None, date, bool]:
    """Return a fixed bucket's start, inclusive end, and grouping size."""
    offsets = {"7D": 6, "30D": 29, "1Y": 364}
    start = None if bucket == "All" else today - timedelta(days=offsets[bucket])
    return start, today, bucket in {"1Y", "All"}


def lambda_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    """Serve fixed buckets or independently requested Custom chart ranges."""
    try:
        payload = parse_event(event)
        country = parse_country(payload)
        rating_range = parse_date_pair(payload, "rating")
        type_range = parse_date_pair(payload, "type")
    except InvalidFilter as exc:
        return response(400, {"error": str(exc)})

    try:
        use_mock = os.environ.get("USE_MOCK_DATA", "false").lower() == "true"
        raw = load_mock_records() if use_mock else load_postgres_records()
        frame = normalize_records(raw, country)
        if rating_range or type_range:
            custom = empty_bucket()
            if rating_range:
                custom["rating_distribution"] = rating_distribution(frame, *rating_range)
            if type_range:
                custom["organization_mix_trend"] = organization_mix_trend(
                    frame, *type_range, monthly=False,
                )
            return response(200, {"Custom": custom})

        today = utc_today()
        output = {}
        for bucket in FIXED_BUCKETS:
            start, end, monthly = fixed_window(bucket, today)
            output[bucket] = {
                "rating_distribution": rating_distribution(frame, start, end),
                "organization_mix_trend": organization_mix_trend(frame, start, end, monthly),
            }
        output["Custom"] = empty_bucket()
        return response(200, output)
    except Exception:  # Database and local file details must not leak to callers.
        return response(500, {"error": "Unable to retrieve organization analytics."})


if __name__ == "__main__":
    today = utc_today()
    start = (today - timedelta(days=30)).isoformat()
    end = today.isoformat()
    samples = {
        "no_body": {},
        "country": {"country": "USA"},
        "rating_custom": {"rating_start_date": start, "rating_end_date": end},
        "type_custom": {"type_start_date": start, "type_end_date": end},
        "both_custom": {
            "rating_start_date": start, "rating_end_date": end,
            "type_start_date": start, "type_end_date": end,
        },
    }
    for name, sample in samples.items():
        result = lambda_handler(sample, None)
        print(f"{name}: {result['statusCode']} {result['body']}")
