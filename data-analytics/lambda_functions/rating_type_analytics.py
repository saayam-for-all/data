"""
Rating & Type Analytics API for the Organization Analytics dashboard
(issue #380).

Standalone function -- not a refactor of organization_analytics.py -- that
returns data for the "Rating & Type" tab:

  - Rating Distribution: organization counts grouped by org_rating (the
    literal integer 1-5 from the organizations table, not an average).
    Categorical and window-scoped, one row per rating actually present in
    the window -- ratings with no organizations are omitted, not zero-filled.
  - Profit vs Non-Profit (organization_mix_trend): a time series with two
    series, non_profit and for_profit. Counts are absolute/cumulative
    (all-time running total per type as of each period, never reset at the
    start of the window), with sparse periods -- a period only appears in a
    type's series if at least one organization of that type was created in
    it within the window.

Response shape depends on which Custom params are present:
  - Neither rating_start_date/rating_end_date nor type_start_date/
    type_end_date supplied: full response with exactly the 5 top-level keys
    "7D"/"30D"/"1Y"/"All"/"Custom".
  - Either or both Custom pairs supplied: response has exactly 1 top-level
    key, "Custom" -- no fixed buckets are computed. Each Custom sub-chart is
    populated independently based on which pair was given; supplying both
    populates both (no priority, no dropping one).

Filters: country only (code or name, case-insensitive, or ALL). There is no
organization_type filter on this tab, since Chart 2 is itself the type
breakdown.

Data source: organizations.csv / states.csv / countries.csv, loaded with
pandas when USE_MOCK_DATA=true (default here, so the file runs standalone
for local testing). psycopg2 is an optional import for the real Postgres
path, so this file still runs with USE_MOCK_DATA=true when psycopg2 isn't
installed. Mock CSVs are local-only and are NOT committed with this PR.
"""

import json
import os
from datetime import datetime, timedelta

import pandas as pd

try:
    import psycopg2
except ImportError:  # psycopg2 isn't required for the USE_MOCK_DATA path.
    psycopg2 = None

USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "true").lower() == "true"

MOCK_DATA_DIR = os.environ.get(
    "MOCK_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data"),
)

DB_SCHEMA = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")

ORG_TYPES = ("non_profit", "for_profit")
VALID_RATINGS = {1, 2, 3, 4, 5}

BUCKET_GRANULARITY = {
    "7D": "day",
    "30D": "day",
    "1Y": "month",
    "All": "month",
    "Custom": "day",
}


class InvalidFilterError(Exception):
    """Raised when a request's filters fail validation."""


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body) if not isinstance(body, str) else body,
    }


def _empty_bucket():
    return {
        "rating_distribution": [],
        "organization_mix_trend": {"non_profit": [], "for_profit": []},
    }


def get_default_full_response():
    return {bucket: _empty_bucket() for bucket in ["7D", "30D", "1Y", "All", "Custom"]}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data_from_csv(data_dir=None):
    """Loads organizations/states/countries CSVs into DataFrames.

    Returns empty-but-correctly-shaped DataFrames if a file is missing or
    empty, so downstream aggregation code doesn't need to special-case it.
    """
    data_dir = data_dir or MOCK_DATA_DIR
    org_path = os.path.join(data_dir, "organizations.csv")
    states_path = os.path.join(data_dir, "states.csv")
    countries_path = os.path.join(data_dir, "countries.csv")

    try:
        df_orgs = pd.read_csv(org_path)
        df_orgs["created_at"] = pd.to_datetime(df_orgs["created_at"], errors="coerce")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        df_orgs = pd.DataFrame(columns=["org_id", "org_rating", "org_type", "state_id", "created_at"])
        df_orgs["created_at"] = pd.to_datetime(df_orgs["created_at"])

    try:
        df_states = pd.read_csv(states_path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        df_states = pd.DataFrame(columns=["state_id", "country_id"])

    try:
        df_countries = pd.read_csv(countries_path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        df_countries = pd.DataFrame(columns=["country_id", "country_code"])

    return df_orgs, df_states, df_countries


def get_db_connection():
    """Builds a psycopg2 connection from DATABASE_URL or DB_* env vars.
    Only used when USE_MOCK_DATA is false."""
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed; set USE_MOCK_DATA=true to use the mock data path")

    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    return psycopg2.connect(
        host=os.environ.get("DB_HOST", os.environ.get("PGHOST", "localhost")),
        port=os.environ.get("DB_PORT", os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("DB_NAME", os.environ.get("PGDATABASE", "postgres")),
        user=os.environ.get("DB_USER", os.environ.get("PGUSER", "postgres")),
        password=os.environ.get("DB_PASSWORD", os.environ.get("PGPASSWORD", "")),
    )


def load_data_from_db():
    """Loads the same three tables from Postgres, with the same columns as
    the CSV path, so downstream code is identical for either source."""
    conn = get_db_connection()
    try:
        df_orgs = pd.read_sql(
            f"SELECT org_id, org_rating, org_type, state_id, created_at "
            f"FROM {DB_SCHEMA}.organizations",
            conn,
        )
        df_orgs["created_at"] = pd.to_datetime(df_orgs["created_at"], errors="coerce")
        df_states = pd.read_sql(f"SELECT state_id, country_id FROM {DB_SCHEMA}.states", conn)
        df_countries = pd.read_sql(
            f"SELECT country_id, country_code, country_name FROM {DB_SCHEMA}.countries", conn
        )
        return df_orgs, df_states, df_countries
    finally:
        conn.close()


def load_data():
    if USE_MOCK_DATA:
        return load_data_from_csv()
    return load_data_from_db()


# ---------------------------------------------------------------------------
# Filters and windows
# ---------------------------------------------------------------------------

def apply_country_filter(df_orgs, df_states, df_countries, country):
    """country matches either country_code or country_name (case-insensitive)
    via organizations.state_id -> states.country_id -> countries. "ALL",
    None, or "" means no filter."""
    if not country or str(country).upper() == "ALL":
        return df_orgs
    if df_orgs.empty or df_states.empty or df_countries.empty:
        return df_orgs.iloc[0:0]

    merge_cols = ["country_id", "country_code"]
    if "country_name" in df_countries.columns:
        merge_cols.append("country_name")

    merged = df_orgs.merge(df_states[["state_id", "country_id"]], on="state_id", how="left")
    merged = merged.merge(df_countries[merge_cols], on="country_id", how="left")

    target = str(country).strip().upper()
    mask = merged["country_code"].astype(str).str.upper() == target
    if "country_name" in merged.columns:
        mask = mask | (merged["country_name"].astype(str).str.upper() == target)

    return merged.loc[mask, df_orgs.columns.tolist()]


def _parse_date(value, field_name):
    try:
        return pd.Timestamp(datetime.strptime(value, "%Y-%m-%d"))
    except (ValueError, TypeError):
        raise InvalidFilterError(f"{field_name} must be a valid date in YYYY-MM-DD format")


def validate_date_pair(start_value, end_value, start_field, end_field):
    """Returns (start_ts, end_ts), or (None, None) if neither value was
    supplied. Raises InvalidFilterError on partial or malformed input."""
    if start_value is None and end_value is None:
        return None, None
    if start_value is None or end_value is None:
        raise InvalidFilterError(f"Both {start_field} and {end_field} are required together")

    start_ts = _parse_date(start_value, start_field)
    end_ts = _parse_date(end_value, end_field)
    if start_ts > end_ts:
        raise InvalidFilterError(f"{start_field} must not be after {end_field}")

    # Make end_ts inclusive of the whole day.
    return start_ts, end_ts + timedelta(hours=23, minutes=59, seconds=59)


def get_fixed_window(bucket, now=None):
    """Returns (start_ts, end_ts). start_ts is None for 'All'."""
    now = now or pd.Timestamp.now()
    if bucket == "7D":
        return now - timedelta(days=7), now
    if bucket == "30D":
        return now - timedelta(days=30), now
    if bucket == "1Y":
        # Calendar year, not a fixed 365-day approximation.
        return now - pd.DateOffset(years=1), now
    if bucket == "All":
        return None, now
    raise ValueError(f"Unknown fixed bucket: {bucket}")


def window_df(df, window_start, window_end):
    if window_end is None or df.empty:
        return df.iloc[0:0]
    mask = df["created_at"] <= window_end
    if window_start is not None:
        mask &= df["created_at"] >= window_start
    return df.loc[mask]


# ---------------------------------------------------------------------------
# Rating Distribution
# ---------------------------------------------------------------------------

def fetch_rating_distribution(df_window):
    """One row per integer rating (1-5) present in the window, ascending.
    Rows with a missing or out-of-range rating are left out of the counts."""
    if df_window.empty or "org_rating" not in df_window.columns:
        return []

    ratings = pd.to_numeric(df_window["org_rating"], errors="coerce").dropna()
    ratings = ratings[ratings == ratings.round()].astype(int)
    ratings = ratings[ratings.isin(VALID_RATINGS)]
    if ratings.empty:
        return []

    counts = ratings.value_counts().sort_index()
    return [{"rating": int(rating), "count": int(count)} for rating, count in counts.items()]


# ---------------------------------------------------------------------------
# Profit vs Non-Profit (organization_mix_trend)
# ---------------------------------------------------------------------------

def fetch_organization_mix_trend(df_all, window_start, window_end, granularity):
    """Returns {"non_profit": [...], "for_profit": [...]}.

    For each type:
      - periods come from organizations of that type created within the
        window (sparse -- no zero-filled periods);
      - each period's count is the all-time running total of that type as
        of the last organization of that type created in the period,
        counted across the full (country-filtered) dataset -- not reset at
        the start of the window, so the series is non-decreasing.
    """
    result = {org_type: [] for org_type in ORG_TYPES}
    if df_all.empty or window_end is None or "org_type" not in df_all.columns:
        return result

    df_all = df_all.dropna(subset=["created_at"])
    org_type_norm = df_all["org_type"].astype(str).str.strip().str.lower()
    strftime_fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m"

    for org_type in ORG_TYPES:
        type_all = df_all.loc[org_type_norm == org_type]
        type_window = window_df(type_all, window_start, window_end)
        if type_window.empty:
            continue

        periods = type_window["created_at"].dt.strftime(strftime_fmt)
        type_created = type_all["created_at"]

        series = []
        for period in sorted(periods.unique()):
            period_end = type_window.loc[periods == period, "created_at"].max()
            cumulative = int((type_created <= period_end).sum())
            series.append({"period": period, "count": cumulative})
        result[org_type] = series

    return result


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def _extract_payload(event):
    """Supports a direct dict (local testing / direct invoke) and an API
    Gateway proxy event whose payload is a JSON string under event["body"]."""
    if not event:
        return {}
    if "body" in event:
        body = event.get("body")
        if body is None or body == "":
            return {}
        if isinstance(body, dict):
            return body
        try:
            parsed = json.loads(body)
        except (TypeError, json.JSONDecodeError):
            raise InvalidFilterError("Request body must be valid JSON")
        return parsed if isinstance(parsed, dict) else {}
    return event


def lambda_handler(event, context):
    try:
        event = _extract_payload(event)
        rating_start, rating_end = validate_date_pair(
            event.get("rating_start_date"), event.get("rating_end_date"),
            "rating_start_date", "rating_end_date",
        )
        type_start, type_end = validate_date_pair(
            event.get("type_start_date"), event.get("type_end_date"),
            "type_start_date", "type_end_date",
        )
    except InvalidFilterError as e:
        return build_response(400, {"error": str(e)})

    country = event.get("country") or "ALL"

    try:
        df_orgs, df_states, df_countries = load_data()
    except Exception as e:
        print(f"Failed to load analytics data: {e}")
        return build_response(500, {"error": "Failed to load analytics data"})

    try:
        df_filtered = apply_country_filter(df_orgs, df_states, df_countries, country)
    except Exception as e:
        print(f"Failed to apply country filter: {e}")
        return build_response(500, {"error": "Failed to apply filters"})

    if rating_start is not None or type_start is not None:
        # Custom-only response: no fixed buckets. Each sub-chart populates
        # independently; both can be populated at once.
        response_body = {"Custom": _empty_bucket()}

        if rating_start is not None:
            try:
                response_body["Custom"]["rating_distribution"] = fetch_rating_distribution(
                    window_df(df_filtered, rating_start, rating_end)
                )
            except Exception as e:
                print(f"Custom rating_distribution failed: {e}")

        if type_start is not None:
            try:
                response_body["Custom"]["organization_mix_trend"] = fetch_organization_mix_trend(
                    df_filtered, type_start, type_end, BUCKET_GRANULARITY["Custom"]
                )
            except Exception as e:
                print(f"Custom organization_mix_trend failed: {e}")

        return build_response(200, response_body)

    # No Custom params: all 4 fixed buckets plus an empty Custom.
    response_body = get_default_full_response()
    for bucket in ["7D", "30D", "1Y", "All"]:
        window_start, window_end = get_fixed_window(bucket)
        try:
            response_body[bucket]["rating_distribution"] = fetch_rating_distribution(
                window_df(df_filtered, window_start, window_end)
            )
        except Exception as e:
            print(f"{bucket} rating_distribution failed: {e}")
        try:
            response_body[bucket]["organization_mix_trend"] = fetch_organization_mix_trend(
                df_filtered, window_start, window_end, BUCKET_GRANULARITY[bucket]
            )
        except Exception as e:
            print(f"{bucket} organization_mix_trend failed: {e}")

    return build_response(200, response_body)


if __name__ == "__main__":
    scenarios = [
        ("No body", {}),
        ("Country filter by code (US)", {"country": "US"}),
        ("Country filter by name, case-insensitive (united states)", {"country": "united states"}),
        ("Rating-range only Custom (Custom-only response)", {
            "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30",
        }),
        ("Type-range only Custom (Custom-only response)", {
            "type_start_date": "2025-01-01", "type_end_date": "2025-03-31",
        }),
        ("Both Custom ranges together (both sub-charts populated)", {
            "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30",
            "type_start_date": "2025-01-01", "type_end_date": "2025-03-31",
        }),
        ("API Gateway proxy shape (JSON string body)", {
            "body": json.dumps({"country": "US", "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"}),
        }),
        ("Invalid: only half a pair supplied -> 400", {"rating_start_date": "2026-01-01"}),
        ("Invalid: start after end -> 400", {
            "type_start_date": "2026-06-30", "type_end_date": "2026-01-01",
        }),
        ("Invalid: bad date format -> 400", {
            "rating_start_date": "01/01/2026", "rating_end_date": "2026-06-30",
        }),
    ]

    for title, event in scenarios:
        print(f"\n=== {title} ===")
        print(f"event: {json.dumps(event)}")
        result = lambda_handler(event, None)
        print(f"statusCode: {result['statusCode']}")
        print(result["body"])
