"""
Rating & Type tab - Organization Analytics dashboard (Issue #380)

Returns two charts:
  1. rating_distribution     - org counts grouped by org_rating (1-5), window-scoped,
                               one row per rating present (no zero-fill).
  2. organization_mix_trend  - non_profit / for_profit cumulative (all-time running
                               total) counts per period, sparse periods.

Response shapes:
  - No Custom params           -> {"7D", "30D", "1Y", "All", "Custom"(empty)}
  - Any Custom pair supplied   -> {"Custom"} only, each sub-chart filled from its own range

Data source:
  - USE_MOCK_DATA=true  -> pandas reads organizations.csv / states.csv / countries.csv
                           from MOCK_DATA_DIR
  - otherwise           -> psycopg2 (optional import) against Postgres
"""

import json
import os
from datetime import date, datetime, timedelta

import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None


SCHEMA_NAME = os.getenv("SCHEMA_NAME", "virginia_dev_saayam_rdbms")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MOCK_DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "mock-data-generation"))

FIXED_BUCKETS = ["7D", "30D", "1Y", "All"]
BUCKET_GRANULARITY = {"7D": "day", "30D": "day", "1Y": "month", "All": "month", "Custom": "day"}
PERIOD_FORMAT = {"day": "%Y-%m-%d", "month": "%Y-%m"}
ORG_TYPES = ["non_profit", "for_profit"]
VALID_RATINGS = {1, 2, 3, 4, 5}

REQUIRED_ORG_COLUMNS = ["org_id", "org_rating", "org_type", "state_id", "created_at"]
REQUIRED_STATE_COLUMNS = ["state_id", "country_id"]
REQUIRED_COUNTRY_COLUMNS = ["country_id", "country_code"]
OUTPUT_COLUMNS = ["org_id", "org_rating", "org_type", "created_at", "country_code", "country_name"]

RESPONSE_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


class DataError(Exception):
    """Server-side data problem (missing file/column, bad created_at, etc.)."""


# ---------------------------------------------------------------------------
# Response / request helpers
# ---------------------------------------------------------------------------
def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": RESPONSE_HEADERS,
        "body": json.dumps(body, default=str),
    }


def parse_event(event):
    """Accepts a direct dict payload or an API Gateway event with a JSON 'body'."""
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise ValueError("Request must be a JSON object")

    if "body" not in event:
        return event

    body = event.get("body")
    if body is None or body == "":
        return {}
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Request body must be a JSON object")
        return parsed
    raise ValueError("Request body must be a JSON object")


def parse_date(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a date string in YYYY-MM-DD format")
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: '{value}' (expected YYYY-MM-DD)") from exc
    return pd.Timestamp(parsed.date())


def parse_custom_range(request, start_key, end_key):
    """Returns (start, end) Timestamps, or None if neither key is present.
    Raises ValueError for half a pair, bad format, or start after end."""
    start_value = request.get(start_key)
    end_value = request.get(end_key)

    if start_value is None and end_value is None:
        return None
    if start_value is None:
        raise ValueError(f"{start_key} is required when {end_key} is provided")
    if end_value is None:
        raise ValueError(f"{end_key} is required when {start_key} is provided")

    start = parse_date(start_value, start_key)
    end = parse_date(end_value, end_key)
    if start > end:
        raise ValueError(f"{start_key} ({start_value}) cannot be after {end_key} ({end_value})")
    return start, end


def parse_country(request):
    country = request.get("country", "ALL")
    if country is None:
        return None
    if not isinstance(country, str):
        raise ValueError("country must be a string (country name, country code, or ALL)")
    country = country.strip()
    if not country or country.upper() == "ALL":
        return None
    return country


# ---------------------------------------------------------------------------
# Data normalisation (shared by mock + DB paths)
# ---------------------------------------------------------------------------
def _normalize_text(series):
    return series.fillna("").astype(str).str.strip()


def _match_key(value):
    """'United States', 'UNITED_STATES', 'united-states' -> 'unitedstates'."""
    return "".join(ch for ch in str(value).casefold() if ch.isalnum())


def normalize_organizations(df):
    df = df.copy()
    for column in OUTPUT_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    try:
        created = pd.to_datetime(df["created_at"], errors="raise")
    except (ValueError, TypeError) as exc:
        raise DataError(f"organizations.created_at contains invalid timestamps: {exc}") from exc
    if getattr(created.dt, "tz", None) is not None:
        created = created.dt.tz_convert(None)
    df["created_at"] = created

    df["org_type"] = (
        _normalize_text(df["org_type"]).str.lower()
        .str.replace("-", "_", regex=False).str.replace(" ", "_", regex=False)
    )

    # org_rating is the literal integer value. Blank/NULL = unrated, anything
    # outside 1-5 or non-integer is not counted in rating_distribution.
    ratings = pd.to_numeric(df["org_rating"], errors="coerce")
    is_int = ratings.notna() & (ratings % 1 == 0)
    df["org_rating"] = ratings.where(is_int & ratings.isin(VALID_RATINGS)).astype("Int64")

    df["country_code"] = _normalize_text(df["country_code"])
    df["country_name"] = _normalize_text(df["country_name"])
    df.loc[df["country_code"].eq(""), "country_code"] = "Unknown"
    return df[OUTPUT_COLUMNS]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _read_csv(data_dir, filename, required_columns):
    path = os.path.join(data_dir, filename)
    if not os.path.isfile(path):
        raise DataError(f"Missing mock data file: {path}")
    df = pd.read_csv(path, dtype=str)
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        raise DataError(f"{filename} is missing required columns: {', '.join(missing)}")
    return df


def load_mock_data(data_dir=None):
    data_dir = data_dir or os.getenv("MOCK_DATA_DIR", DEFAULT_MOCK_DATA_DIR)

    organizations = _read_csv(data_dir, "organizations.csv", REQUIRED_ORG_COLUMNS)
    states = _read_csv(data_dir, "states.csv", REQUIRED_STATE_COLUMNS)
    countries = _read_csv(data_dir, "countries.csv", REQUIRED_COUNTRY_COLUMNS)

    for frame, column in [(organizations, "state_id"), (states, "state_id"),
                          (states, "country_id"), (countries, "country_id")]:
        frame[column] = _normalize_text(frame[column])

    country_columns = ["country_id", "country_code"] + (
        ["country_name"] if "country_name" in countries.columns else []
    )
    location = states[["state_id", "country_id"]].drop_duplicates("state_id").merge(
        countries[country_columns].drop_duplicates("country_id"), on="country_id", how="left"
    )
    merged = organizations.merge(location, on="state_id", how="left")
    return normalize_organizations(merged)


def get_db_connection():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required when USE_MOCK_DATA is not 'true'")
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD must be set when USE_MOCK_DATA is not 'true'")
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "Saayam"),
        user=os.getenv("DB_USER", "postgres"),
        password=password,
        port=os.getenv("DB_PORT", "5432"),
    )


def load_database_data():
    query = f"""
        SELECT
            o.org_id,
            o.org_rating,
            o.org_type,
            o.created_at,
            c.country_code,
            c.country_name
        FROM {SCHEMA_NAME}.organizations AS o
        LEFT JOIN {SCHEMA_NAME}.states    AS s ON o.state_id   = s.state_id
        LEFT JOIN {SCHEMA_NAME}.countries AS c ON s.country_id = c.country_id
    """
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        return normalize_organizations(pd.DataFrame(rows, columns=columns))
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def load_data():
    if os.getenv("USE_MOCK_DATA", "false").strip().lower() == "true":
        return load_mock_data()
    return load_database_data()


# ---------------------------------------------------------------------------
# Filters & windows
# ---------------------------------------------------------------------------
def get_today():
    return pd.Timestamp(date.today())


def apply_country_filter(df, country):
    if country is None or df.empty:
        return df
    key = _match_key(country)
    code_match = df["country_code"].map(_match_key) == key
    name_match = df["country_name"].map(_match_key) == key
    return df[code_match | name_match]


def get_bucket_range(bucket, today):
    """Inclusive (start, end) by calendar day. start=None means 'from the beginning'."""
    if bucket == "7D":
        return today - timedelta(days=6), today
    if bucket == "30D":
        return today - timedelta(days=29), today
    if bucket == "1Y":
        return today - pd.DateOffset(years=1) + timedelta(days=1), today
    if bucket == "All":
        return None, today
    raise ValueError(f"Unknown bucket: {bucket}")


def window(df, start, end):
    """Rows whose created_at calendar day falls in [start, end]."""
    if df.empty:
        return df
    day = df["created_at"].dt.normalize()
    mask = day <= end
    if start is not None:
        mask &= day >= start
    return df[mask]


# ---------------------------------------------------------------------------
# Chart 1: Rating Distribution
# ---------------------------------------------------------------------------
def compute_rating_distribution(df, start, end):
    rated = window(df, start, end)
    rated = rated[rated["org_rating"].notna()]
    if rated.empty:
        return []
    counts = rated.groupby("org_rating").size().sort_index()
    return [{"rating": int(r), "count": int(c)} for r, c in counts.items()]


# ---------------------------------------------------------------------------
# Chart 2: Profit vs Non-Profit (cumulative, sparse)
# ---------------------------------------------------------------------------
def _cumulative_series(type_df, start, end, granularity):
    """Running all-time total of this org type, reported only for periods inside
    [start, end] in which at least one new org of this type was created."""
    if type_df.empty:
        return []
    fmt = PERIOD_FORMAT[granularity]

    up_to_end = window(type_df, None, end)
    if up_to_end.empty:
        return []
    running = (
        up_to_end["created_at"].dt.strftime(fmt)
        .value_counts().sort_index().cumsum()
    )

    in_window = window(type_df, start, end)
    periods = sorted(in_window["created_at"].dt.strftime(fmt).unique())
    return [{"period": p, "count": int(running[p])} for p in periods]


def compute_organization_mix_trend(df, start, end, granularity):
    return {
        org_type: _cumulative_series(df[df["org_type"] == org_type], start, end, granularity)
        for org_type in ORG_TYPES
    }


def empty_mix_trend():
    return {org_type: [] for org_type in ORG_TYPES}


def empty_bucket():
    return {"rating_distribution": [], "organization_mix_trend": empty_mix_trend()}


# ---------------------------------------------------------------------------
# Response assembly
# ---------------------------------------------------------------------------
def build_response_body(df, rating_range, type_range, today):
    if rating_range is not None or type_range is not None:
        custom = empty_bucket()
        if rating_range is not None:
            custom["rating_distribution"] = compute_rating_distribution(df, *rating_range)
        if type_range is not None:
            custom["organization_mix_trend"] = compute_organization_mix_trend(
                df, type_range[0], type_range[1], BUCKET_GRANULARITY["Custom"]
            )
        return {"Custom": custom}

    body = {}
    for bucket in FIXED_BUCKETS:
        start, end = get_bucket_range(bucket, today)
        body[bucket] = {
            "rating_distribution": compute_rating_distribution(df, start, end),
            "organization_mix_trend": compute_organization_mix_trend(
                df, start, end, BUCKET_GRANULARITY[bucket]
            ),
        }
    body["Custom"] = empty_bucket()
    return body


def lambda_handler(event, context=None):
    # 1. Validate input first - bad requests never touch the data source.
    try:
        request = parse_event(event)
        country = parse_country(request)
        rating_range = parse_custom_range(request, "rating_start_date", "rating_end_date")
        type_range = parse_custom_range(request, "type_start_date", "type_end_date")
    except ValueError as exc:
        return build_response(400, {"error": str(exc)})

    # 2. Load, filter, compute.
    try:
        df = apply_country_filter(load_data(), country)
        body = build_response_body(df, rating_range, type_range, get_today())
        return build_response(200, body)
    except DataError as exc:
        print(f"ERROR (data): {exc}")
        return build_response(500, {"error": "Data error", "details": str(exc)})
    except Exception as exc:  # noqa: BLE001 - last-resort guard for the Lambda
        print(f"ERROR (unexpected): {exc!r}")
        return build_response(500, {"error": "Internal server error"})


# ---------------------------------------------------------------------------
# Local run: USE_MOCK_DATA=true python rating_type_analytics.py
# ---------------------------------------------------------------------------
def _sanity_check(label, event, response):
    body = json.loads(response["body"])
    if response["statusCode"] != 200:
        return
    has_custom_params = any(
        k in event for k in ("rating_start_date", "rating_end_date", "type_start_date", "type_end_date")
    )
    expected_keys = ["Custom"] if has_custom_params else FIXED_BUCKETS + ["Custom"]
    assert list(body.keys()) == expected_keys, f"{label}: unexpected top-level keys {list(body)}"
    for key, bucket in body.items():
        assert set(bucket) == {"rating_distribution", "organization_mix_trend"}, f"{label}/{key}"
        assert set(bucket["organization_mix_trend"]) == set(ORG_TYPES), f"{label}/{key}"
        for series in bucket["organization_mix_trend"].values():
            counts = [p["count"] for p in series]
            assert counts == sorted(counts), f"{label}/{key}: mix trend not cumulative"


if __name__ == "__main__":
    os.environ.setdefault("USE_MOCK_DATA", "true")
    print(f"USE_MOCK_DATA={os.environ['USE_MOCK_DATA']}")
    print(f"MOCK_DATA_DIR={os.getenv('MOCK_DATA_DIR', DEFAULT_MOCK_DATA_DIR)}")
    print(f"Reference date (today)={get_today().date()}")

    samples = [
        ("1. No body", {}),
        ("2. Country filter (USA)", {"country": "USA"}),
        ("3. Country filter by name (India)", {"country": "India"}),
        ("4. Rating Custom range only",
         {"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"}),
        ("5. Type Custom range only",
         {"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"}),
        ("6. Both Custom ranges + country",
         {"country": "USA",
          "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30",
          "type_start_date": "2025-01-01", "type_end_date": "2025-12-31"}),
        ("7. ERROR - missing half of a pair", {"rating_start_date": "2026-01-01"}),
        ("8. ERROR - bad date format", {"type_start_date": "2025/01/01", "type_end_date": "2025-12-31"}),
        ("9. ERROR - start after end", {"rating_start_date": "2026-06-30", "rating_end_date": "2026-01-01"}),
        ("10. API Gateway style event (body as JSON string)",
         {"body": json.dumps({"type_start_date": "2026-08-01", "type_end_date": "2026-08-31"})}),
    ]

    for label, event in samples:
        print(f"\n===== {label} =====")
        print(f"Request: {json.dumps(event)}")
        response = lambda_handler(event, None)
        print(f"Status: {response['statusCode']}")
        print(json.dumps(json.loads(response["body"]), indent=2))
        inner = json.loads(event["body"]) if "body" in event else event
        _sanity_check(label, inner, response)

    print("\nAll sanity checks passed.")
