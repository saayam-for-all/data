"""Rating & Type analytics for the Organization Analytics dashboard (issue #380).

Returns the data for the "Rating & Type" tab:

* ``rating_distribution``      - organization counts per star rating (1-5)
* ``organization_mix_trend``   - cumulative organization counts per type
                                 (non_profit / for_profit) over time

Response shape (same pattern as Growth & Location / Size & Contribution):

* No Custom date pair supplied  -> keys "7D", "30D", "1Y", "All" and an empty "Custom".
* Any Custom date pair supplied -> only the "Custom" key. ``rating_distribution`` is
  populated from rating_start_date/rating_end_date and ``organization_mix_trend`` from
  type_start_date/type_end_date, independently of each other.

Data sources:

* ``USE_MOCK_DATA=true``  -> organizations.csv / states.csv / countries.csv in
  ``MOCK_DATA_DIR`` (local testing only, the CSVs are never committed).
* otherwise               -> Postgres through psycopg2 (optional import).
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta

import pandas as pd

try:
    import psycopg2
except ImportError:  # keeps the file runnable standalone with USE_MOCK_DATA=true
    psycopg2 = None

logger = logging.getLogger(__name__)

DEFAULT_MOCK_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data")

FIXED_BUCKETS = ["7D", "30D", "1Y", "All"]
BUCKET_GRANULARITY = {
    "7D": "day",
    "30D": "day",
    "1Y": "month",
    "All": "month",
    "Custom": "day",
}
ORG_TYPES = ["non_profit", "for_profit"]
ORG_COLUMNS = ["org_id", "org_rating", "org_type", "state_id", "created_at"]


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
def _now():
    return datetime.now()


def _read_csv(path, required):
    """Read a CSV; a completely empty file becomes an empty frame with `required` columns."""
    try:
        df = pd.read_csv(path, dtype={"state_id": str, "country_id": str})
    except pd.errors.EmptyDataError:
        df = pd.DataFrame(columns=required)

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"{os.path.basename(path)} is missing required columns: {', '.join(missing)}")
    return df


def _clean(df):
    """Normalise types after the organizations -> states -> countries join."""
    df = df.copy()
    # tz-aware (timestamptz) and naive values both end up as naive UTC
    df["created_at"] = pd.to_datetime(
        df["created_at"], errors="coerce", utc=True, format="mixed"
    ).dt.tz_localize(None)
    df = df.dropna(subset=["created_at"])
    df["org_rating"] = pd.to_numeric(df["org_rating"], errors="coerce")
    return df


def load_mock_data():
    data_dir = os.environ.get("MOCK_DATA_DIR", DEFAULT_MOCK_DATA_DIR)

    organizations = _read_csv(os.path.join(data_dir, "organizations.csv"), ORG_COLUMNS)
    states = _read_csv(os.path.join(data_dir, "states.csv"), ["state_id", "country_id"])
    countries = _read_csv(os.path.join(data_dir, "countries.csv"), ["country_id"])

    if "country_code" not in countries.columns and "country_name" not in countries.columns:
        raise ValueError("countries.csv needs country_code or country_name")
    for col in ("country_code", "country_name"):
        if col not in countries.columns:
            countries[col] = None

    organizations = organizations[ORG_COLUMNS]
    states = states[["state_id", "country_id"]].drop_duplicates("state_id")
    countries = countries[["country_id", "country_code", "country_name"]].drop_duplicates("country_id")

    merged = organizations.merge(states, on="state_id", how="left")
    merged = merged.merge(countries, on="country_id", how="left")
    return _clean(merged)


def load_db_data():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed; install it or set USE_MOCK_DATA=true")

    schema = os.environ.get("ORG_ANALYTICS_SCHEMA", "virginia_dev_saayam_rdbms")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError(f"Invalid ORG_ANALYTICS_SCHEMA: {schema}")

    query = f"""
        SELECT o.org_id, o.org_rating, o.org_type, o.state_id, o.created_at,
               c.country_code, c.country_name
        FROM {schema}.organizations o
        LEFT JOIN state s ON o.state_id = s.state_id
        LEFT JOIN country c ON s.country_id = c.country_id
    """

    conn = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
    finally:
        conn.close()

    return _clean(pd.DataFrame(rows, columns=columns))


def load_data():
    if os.environ.get("USE_MOCK_DATA", "false").strip().lower() == "true":
        return load_mock_data()
    return load_db_data()


# --------------------------------------------------------------------------- #
# Filters and windows
# --------------------------------------------------------------------------- #
def _normalize_country(value):
    return str(value).strip().upper().replace(" ", "_")


def apply_country_filter(df, country):
    """country is a country name or code; None / '' / 'ALL' means no filter."""
    if country is None:
        return df
    if not isinstance(country, str):
        raise ValueError("country must be a string")
    if country.strip() == "" or country.strip().upper() == "ALL":
        return df

    target = _normalize_country(country)
    codes = df["country_code"].fillna("").map(_normalize_country)
    names = df["country_name"].fillna("").map(_normalize_country)
    return df[(codes == target) | (names == target)]


def _one_year_ago(day):
    try:
        return day.replace(year=day.year - 1)
    except ValueError:  # Feb 29
        return day.replace(year=day.year - 1, day=28)


def get_bucket_range(bucket, now=None):
    now = now or _now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if bucket == "7D":
        return today - timedelta(days=6), now
    if bucket == "30D":
        return today - timedelta(days=29), now
    if bucket == "1Y":
        return _one_year_ago(today) + timedelta(days=1), now
    if bucket == "All":
        return None, now
    raise ValueError(f"get_bucket_range doesn't handle bucket: {bucket}")


def _window(df, window_start, window_end):
    windowed = df[df["created_at"] <= window_end]
    if window_start is not None:
        windowed = windowed[windowed["created_at"] >= window_start]
    return windowed


# --------------------------------------------------------------------------- #
# Chart computations
# --------------------------------------------------------------------------- #
def compute_rating_distribution(df, window_start, window_end):
    """Window-scoped counts, one row per rating (1-5) present; no zero-filling."""
    ratings = _window(df, window_start, window_end)["org_rating"].dropna()
    ratings = ratings[(ratings >= 1) & (ratings <= 5) & (ratings == ratings.round())]

    counts = ratings.astype(int).value_counts().sort_index()
    return [{"rating": int(rating), "count": int(count)} for rating, count in counts.items()]


def compute_organization_mix_trend(df, window_start, window_end, granularity):
    """Cumulative (all-time running total) counts per type, sparse periods only."""
    period_format = "%Y-%m-%d" if granularity == "day" else "%Y-%m"
    trend = {}

    for org_type in ORG_TYPES:
        of_type = df[(df["org_type"] == org_type) & (df["created_at"] <= window_end)]
        if of_type.empty:
            trend[org_type] = []
            continue

        periods = of_type["created_at"].dt.strftime(period_format)
        running_total = periods.value_counts().sort_index().cumsum()

        if window_start is not None:
            in_window = periods[of_type["created_at"] >= window_start]
        else:
            in_window = periods
        trend[org_type] = [
            {"period": period, "count": int(running_total[period])}
            for period in sorted(in_window.unique())
        ]

    return trend


def empty_organization_mix_trend():
    return {"non_profit": [], "for_profit": []}


def build_bucket(df, bucket, window_start, window_end):
    return {
        "rating_distribution": compute_rating_distribution(df, window_start, window_end),
        "organization_mix_trend": compute_organization_mix_trend(
            df, window_start, window_end, BUCKET_GRANULARITY[bucket]
        ),
    }


# --------------------------------------------------------------------------- #
# Input handling
# --------------------------------------------------------------------------- #
def parse_date_or_error(date_str, field_name):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d"), None
    except (ValueError, TypeError):
        return None, f"Invalid date format for {field_name}: {date_str} (expected YYYY-MM-DD)"


def validate_date_range(start_str, end_str, start_field, end_field):
    """Returns (start, end, error). (None, None, None) means the pair was not supplied."""
    if start_str is None and end_str is None:
        return None, None, None

    if start_str is None:
        return None, None, f"{start_field} is required when {end_field} is provided"

    if end_str is None:
        return None, None, f"{end_field} is required when {start_field} is provided"

    start_dt, err = parse_date_or_error(start_str, start_field)
    if err:
        return None, None, err

    end_dt, err = parse_date_or_error(end_str, end_field)
    if err:
        return None, None, err

    if start_dt > end_dt:
        return None, None, f"{start_field} must be on or before {end_field}"

    return start_dt, end_dt, None


def _end_of_day(day):
    return day + timedelta(days=1) - timedelta(microseconds=1)


def parse_event(event):
    """Accepts a plain dict of filters or an API Gateway style event (body / query string)."""
    if event is None:
        return {}, None
    if not isinstance(event, dict):
        return None, "Request must be a JSON object"

    if not any(key in event for key in ("body", "queryStringParameters", "httpMethod")):
        return event, None

    params = dict(event.get("queryStringParameters") or {})
    body = event.get("body")
    if isinstance(body, str):
        if body.strip():
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                return None, "Request body must be valid JSON"
        else:
            body = None
    if body is not None:
        if not isinstance(body, dict):
            return None, "Request body must be a JSON object"
        params.update(body)
    return params, None


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #
def lambda_handler(event, context):
    try:
        params, err = parse_event(event)
        if err:
            return build_response(400, {"error": err})

        country = params.get("country")
        if country is not None and not isinstance(country, str):
            return build_response(400, {"error": "country must be a string"})

        # Validate both pairs up front so bad input never produces a partial result.
        rating_start, rating_end, err = validate_date_range(
            params.get("rating_start_date"), params.get("rating_end_date"),
            "rating_start_date", "rating_end_date",
        )
        if err:
            return build_response(400, {"error": err})

        type_start, type_end, err = validate_date_range(
            params.get("type_start_date"), params.get("type_end_date"),
            "type_start_date", "type_end_date",
        )
        if err:
            return build_response(400, {"error": err})

        df = apply_country_filter(load_data(), country)

        if rating_start is not None or type_start is not None:
            custom = {
                "rating_distribution": [],
                "organization_mix_trend": empty_organization_mix_trend(),
            }
            if rating_start is not None:
                custom["rating_distribution"] = compute_rating_distribution(
                    df, rating_start, _end_of_day(rating_end)
                )
            if type_start is not None:
                custom["organization_mix_trend"] = compute_organization_mix_trend(
                    df, type_start, _end_of_day(type_end), BUCKET_GRANULARITY["Custom"]
                )
            return build_response(200, {"Custom": custom})

        now = _now()
        response_body = {}
        for bucket in FIXED_BUCKETS:
            window_start, window_end = get_bucket_range(bucket, now)
            response_body[bucket] = build_bucket(df, bucket, window_start, window_end)
        response_body["Custom"] = {
            "rating_distribution": [],
            "organization_mix_trend": empty_organization_mix_trend(),
        }
        return build_response(200, response_body)

    except Exception as exc:  # never let a Lambda crash with a raw traceback
        logger.exception("Rating & Type analytics failed")
        return build_response(500, {"error": f"Internal server error ({type(exc).__name__})"})


if __name__ == "__main__":
    # Local testing: python rating_type_analytics.py  (set MOCK_DATA_DIR to the CSV folder)
    os.environ.setdefault("USE_MOCK_DATA", "true")

    samples = [
        ("Test 1: Empty body", {}),
        ("Test 2: Country filter only (USA)", {"country": "USA"}),
        ("Test 3: Rating range only (Custom mode)",
         {"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"}),
        ("Test 4: Type range only (Custom mode)",
         {"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"}),
        ("Test 5: Both ranges + country (Custom mode)",
         {"country": "USA",
          "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30",
          "type_start_date": "2025-01-01", "type_end_date": "2025-12-31"}),
    ]
    for title, event in samples:
        print(f"=== {title} ===")
        print(json.dumps(json.loads(lambda_handler(event, None)["body"]), indent=2))
        print()

    error_samples = [
        ("Test 6: Rating start after end (should be 400)",
         {"rating_start_date": "2026-06-30", "rating_end_date": "2026-01-01"}),
        ("Test 7: Only one half of the type pair (should be 400)",
         {"type_start_date": "2026-01-01"}),
        ("Test 8: Bad date format (should be 400)",
         {"rating_start_date": "01/01/2026", "rating_end_date": "2026-06-30"}),
        ("Test 9: Valid rating pair but bad type pair (should be 400, no partial result)",
         {"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30",
          "type_end_date": "2026-06-30"}),
    ]
    for title, event in error_samples:
        print(f"=== {title} ===")
        result = lambda_handler(event, None)
        print(result["statusCode"], result["body"])
        print()
