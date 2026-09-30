"""
Organization Analytics - Rating & Type tab.

Returns data for two charts:
  1. rating_distribution     - organization counts per star rating (1-5), window-scoped.
  2. organization_mix_trend  - cumulative (all-time running total) counts of
                               non_profit / for_profit organizations over time.

Response shapes:
  * No Custom date pairs      -> {"7D", "30D", "1Y", "All", "Custom"(empty)}
  * Any Custom date pair(s)   -> {"Custom"} only; each sub-chart is populated
                                 only if its own date pair was supplied.

Data source:
  * USE_MOCK_DATA=true  -> CSVs in MOCK_DATA_DIR (organizations.csv, states.csv, countries.csv)
  * otherwise           -> Virginia RDS (credentials from SSM), same connection
                           pattern as organization_analytics.py / kpi_api_analytics.py

Both paths load the same columns into a pandas DataFrame, so the chart logic
(and its tests) is shared and the mock output matches the real one.

Time windows follow build_date_filter() in organization_analytics.py:
they are measured from CURRENT_DATE (midnight today, UTC).
"""

import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

try:  # optional so the file runs standalone with USE_MOCK_DATA=true
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

try:  # available in the AWS Lambda runtime; only needed for the real DB path
    import boto3
except ImportError:
    boto3 = None


SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ORGANIZATIONS_TABLE = f"{SCHEMA_NAME}.organizations"
STATE_TABLE = f"{SCHEMA_NAME}.state"
COUNTRY_TABLE = f"{SCHEMA_NAME}.country"  # TODO: confirm table/column names against the DDL
SSM_DB_PARAMETER = "/dev/saayam/db/Virginia/Analytics/user"


RATING_START, RATING_END = "rating_start_date", "rating_end_date"
TYPE_START, TYPE_END = "type_start_date", "type_end_date"
DATE_FORMAT = "%Y-%m-%d"
ORG_TYPES = ("non_profit", "for_profit")
VALID_RATINGS = {1, 2, 3, 4, 5}

# bucket -> (window length, trend period granularity); None = all time
FIXED_BUCKETS = {
    "7D": ("7 days", "day"),
    "30D": ("30 days", "day"),
    "1Y": ("1 year", "month"),
    "All": (None, "month"),
}
PERIOD_FORMATS = {"day": "%Y-%m-%d", "month": "%Y-%m"}


class ValidationError(Exception):
    """Raised for malformed or incomplete request input."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _today():
    """CURRENT_DATE in UTC (kept separate so tests can patch it)."""
    return datetime.now(timezone.utc).date()


def _window_start(today, window):
    """Mirrors CURRENT_DATE - INTERVAL '<window>' from build_date_filter()."""
    midnight = datetime.combine(today, datetime.min.time())
    if window == "1 year":
        try:
            return midnight.replace(year=midnight.year - 1)
        except ValueError:  # Feb 29 -> Feb 28
            return midnight.replace(year=midnight.year - 1, day=28)
    return midnight - timedelta(days=int(window.split()[0]))


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def _empty_chart():
    return {
        "rating_distribution": [],
        "organization_mix_trend": {"non_profit": [], "for_profit": []},
    }


def parse_event_body(event):
    """
    Same contract as organization_analytics.parse_event_body, except malformed
    JSON is rejected with a 400 instead of silently treated as an empty body.
    """
    if not event:
        return {}
    if isinstance(event, dict) and "body" in event:
        body = event.get("body")
        if body in (None, ""):
            return {}
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                raise ValidationError("Request body must be valid JSON.")
    else:
        body = event
    if not isinstance(body, dict):
        raise ValidationError("Request body must be a JSON object.")
    return body


def _is_blank(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def _parse_date(name, value):
    if not isinstance(value, str):
        raise ValidationError(f"'{name}' must be a string in YYYY-MM-DD format.")
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT)
    except ValueError:
        raise ValidationError(
            f"'{name}' has an invalid date '{value}'. Expected format YYYY-MM-DD."
        )


def _parse_date_pair(body, start_key, end_key):
    """
    Returns (start, end_exclusive) or None when neither key is supplied.
    The end date is inclusive for the caller, so the window runs to the
    start of the following day.
    """
    start_raw, end_raw = body.get(start_key), body.get(end_key)
    if _is_blank(start_raw) and _is_blank(end_raw):
        return None
    if _is_blank(start_raw) or _is_blank(end_raw):
        missing = start_key if _is_blank(start_raw) else end_key
        raise ValidationError(
            f"'{start_key}' and '{end_key}' must be supplied together; '{missing}' is missing."
        )
    start = _parse_date(start_key, start_raw)
    end = _parse_date(end_key, end_raw)
    if start > end:
        raise ValidationError(f"'{start_key}' must be on or before '{end_key}'.")
    return start, end + timedelta(days=1)


def _parse_country(body):
    country = body.get("country", "ALL")
    if _is_blank(country):
        return "ALL"
    if not isinstance(country, str):
        raise ValidationError("'country' must be a string (country name, country code, or ALL).")
    return country.strip()


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
def _load_mock_frames():
    data_dir = os.environ.get("MOCK_DATA_DIR", ".")
    orgs = pd.read_csv(os.path.join(data_dir, "organizations.csv"))
    states = pd.read_csv(os.path.join(data_dir, "states.csv"))
    countries = pd.read_csv(os.path.join(data_dir, "countries.csv"))

    df = orgs.merge(states[["state_id", "country_id"]], on="state_id", how="left")
    country_cols = ["country_id"] + [
        c for c in ("country_code", "country_name") if c in countries.columns
    ]
    return df.merge(countries[country_cols], on="country_id", how="left")


def get_db_connection():
    """Same SSM-backed Virginia RDS connection as organization_analytics.py."""
    if psycopg2 is None or boto3 is None:
        raise RuntimeError(
            "psycopg2/boto3 not installed; set USE_MOCK_DATA=true to use local CSV data."
        )
    ssm = boto3.client("ssm", region_name="us-east-1")
    response = ssm.get_parameter(Name=SSM_DB_PARAMETER, WithDecryption=True)
    creds = json.loads(response["Parameter"]["Value"])
    return psycopg2.connect(
        host=creds["HOST"],
        database=creds["DATABASE NAME"],
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require",
    )


DB_QUERY = f"""
    SELECT
        o.org_id,
        o.org_rating,
        o.org_type::text AS org_type,
        o.created_at,
        c.country_code,
        c.country_name
    FROM {ORGANIZATIONS_TABLE} o
    LEFT JOIN {STATE_TABLE} s   ON o.state_id = s.state_id
    LEFT JOIN {COUNTRY_TABLE} c ON s.country_id = c.country_id;
"""


def _load_db_frame():
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(DB_QUERY)
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    columns = ["org_id", "org_rating", "org_type", "created_at", "country_code", "country_name"]
    return pd.DataFrame(rows, columns=columns)


def _clean(df):
    """Normalise types; drop rows that can't be placed in time."""
    df = df.copy()
    for col in ("org_rating", "org_type", "created_at", "country_code", "country_name"):
        if col not in df.columns:
            df[col] = None

    created = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
    df["created_at"] = created.dt.tz_localize(None)
    df = df[df["created_at"].notna()]

    df["org_rating"] = pd.to_numeric(df["org_rating"], errors="coerce")
    df["org_type"] = (
        df["org_type"].astype("string").str.strip().str.lower().str.replace("-", "_", regex=False)
    )
    return df


def _filter_country(df, country):
    if country.upper() == "ALL":
        return df
    target = country.lower()
    code_match = df["country_code"].astype("string").str.strip().str.lower() == target
    name_match = df["country_name"].astype("string").str.strip().str.lower() == target
    return df[(code_match | name_match).fillna(False)]


def load_organizations(country):
    use_mock = os.environ.get("USE_MOCK_DATA", "false").strip().lower() == "true"
    df = _load_mock_frames() if use_mock else _load_db_frame()
    return _filter_country(_clean(df), country)


# --------------------------------------------------------------------------- #
# Chart builders
# --------------------------------------------------------------------------- #
def rating_distribution(df, start, end):
    """Counts per rating for orgs created in [start, end). start=None means all time."""
    in_window = df[df["created_at"] < end]
    if start is not None:
        in_window = in_window[in_window["created_at"] >= start]
    ratings = in_window["org_rating"].dropna()
    ratings = ratings[ratings.isin(VALID_RATINGS)].astype(int)
    counts = ratings.value_counts().sort_index()
    return [{"rating": int(r), "count": int(c)} for r, c in counts.items()]


def organization_mix_trend(df, start, end, granularity):
    """
    Cumulative all-time totals per org type, one point per period in [start, end)
    that had at least one new org of that type (sparse, not zero-filled).
    """
    fmt = PERIOD_FORMATS[granularity]
    trend = {}
    for org_type in ORG_TYPES:
        of_type = df[(df["org_type"] == org_type) & (df["created_at"] < end)]
        if start is None:
            baseline, in_window = 0, of_type
        else:
            baseline = int((of_type["created_at"] < start).sum())
            in_window = of_type[of_type["created_at"] >= start]

        per_period = in_window["created_at"].dt.strftime(fmt).value_counts().sort_index()
        running = per_period.cumsum() + baseline
        trend[org_type] = [{"period": p, "count": int(c)} for p, c in running.items()]
    return trend


def build_fixed_buckets(df, today):
    # windows are open-ended at the top like the SQL filters; end = start of tomorrow
    end = datetime.combine(today + timedelta(days=1), datetime.min.time())
    result = {}
    for bucket, (window, granularity) in FIXED_BUCKETS.items():
        start = None if window is None else _window_start(today, window)
        result[bucket] = {
            "rating_distribution": rating_distribution(df, start, end),
            "organization_mix_trend": organization_mix_trend(df, start, end, granularity),
        }
    result["Custom"] = _empty_chart()
    return result


def build_custom(df, rating_range, type_range):
    custom = _empty_chart()
    if rating_range:
        custom["rating_distribution"] = rating_distribution(df, *rating_range)
    if type_range:
        custom["organization_mix_trend"] = organization_mix_trend(df, *type_range, "day")
    return {"Custom": custom}


# --------------------------------------------------------------------------- #
# Lambda entry point
# --------------------------------------------------------------------------- #
def lambda_handler(event, context=None):
    try:
        body = parse_event_body(event)
        country = _parse_country(body)
        rating_range = _parse_date_pair(body, RATING_START, RATING_END)
        type_range = _parse_date_pair(body, TYPE_START, TYPE_END)
    except ValidationError as err:
        return build_response(400, {"error": str(err)})

    try:
        df = load_organizations(country)
        if rating_range or type_range:
            result = build_custom(df, rating_range, type_range)
        else:
            result = build_fixed_buckets(df, _today())
    except Exception as err:  # data/DB failures -> 500 with a clear message
        print(f"[rating_type] failed to build analytics: {err}")
        return build_response(500, {"error": f"Failed to build Rating & Type analytics: {err}"})

    return build_response(200, result)


if __name__ == "__main__":
    os.environ.setdefault("USE_MOCK_DATA", "true")

    sample_events = {
        "No body": {},
        "Country filter (USA)": {"body": json.dumps({"country": "USA"})},
        "Rating Custom range only": {
            "body": json.dumps({RATING_START: "2026-01-01", RATING_END: "2026-06-30"})
        },
        "Type Custom range only": {
            "body": json.dumps({TYPE_START: "2025-01-01", TYPE_END: "2025-12-31"})
        },
        "Both Custom ranges": {
            "body": json.dumps({
                "country": "USA",
                RATING_START: "2026-01-01", RATING_END: "2026-06-30",
                TYPE_START: "2025-01-01", TYPE_END: "2025-12-31",
            })
        },
        "Error: missing half of a pair": {"body": json.dumps({RATING_START: "2026-01-01"})},
        "Error: bad date format": {
            "body": json.dumps({TYPE_START: "2025/01/01", TYPE_END: "2025-12-31"})
        },
        "Error: start after end": {
            "body": json.dumps({RATING_START: "2026-06-30", RATING_END: "2026-01-01"})
        },
    }

    for name, event in sample_events.items():
        response = lambda_handler(event, None)
        print(f"\n===== {name} (status {response['statusCode']}) =====")
        print(json.dumps(json.loads(response["body"]), indent=2))
