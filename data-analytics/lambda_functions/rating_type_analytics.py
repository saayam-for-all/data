"""
Rating & Type analytics for the Organization Analytics dashboard (issue #380).

Charts:
  - rating_distribution:   [{"rating": 4, "count": 2}, ...]  (ratings present only)
  - organization_mix_trend: {"non_profit": [{"period", "count"}], "for_profit": [...]}
                            cumulative all-time counts, sparse periods.

Request (all optional):
  country                                   "ALL" (default), country code or name
  rating_start_date / rating_end_date       custom range for rating_distribution
  type_start_date   / type_end_date         custom range for organization_mix_trend

No custom pair -> 7D, 30D, 1Y, All and an empty Custom.
Any custom pair -> only Custom; each chart uses its own pair (empty if absent).

Data source:
  USE_MOCK_DATA=true   pandas over organizations/state/country CSVs in MOCK_DATA_DIR
  otherwise            PostgreSQL via psycopg2 (optional import), configured with
                       DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SCHEMA
"""
import json
import os
import re
from datetime import datetime

import pandas as pd

try:
    import psycopg2
except ImportError:  # mock-data runs must work without a Postgres driver
    psycopg2 = None

DEFAULT_SCHEMA = "virginia_dev_saayam_rdbms"
DEFAULT_MOCK_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, "sql"
)

DATE_FORMAT = "%Y-%m-%d"
FIXED_RANGES = ["7D", "30D", "1Y", "All"]
TYPE_KEYS = ("non_profit", "for_profit")
DATA_COLUMNS = ["org_id", "org_rating", "org_type_key", "created_at", "country_code", "country_name"]


# ---------------------------------------------------------------------------
# Request parsing / validation
# ---------------------------------------------------------------------------

def parse_event_body(event):
    if not event:
        return {}
    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("Request body is not valid JSON.")
    if isinstance(body, dict):
        return body
    raise ValueError("Request body must be a JSON object.")


def _parse_date(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a date string in YYYY-MM-DD format.")
    try:
        return pd.Timestamp(datetime.strptime(value.strip(), DATE_FORMAT))
    except ValueError:
        raise ValueError(f"{field} '{value}' is not a valid date; expected YYYY-MM-DD.")


def parse_date_pair(params, prefix):
    """Return (start, end) Timestamps, or None when neither half is supplied."""
    start_field, end_field = f"{prefix}_start_date", f"{prefix}_end_date"
    start_raw, end_raw = params.get(start_field), params.get(end_field)
    has_start = start_raw not in (None, "")
    has_end = end_raw not in (None, "")

    if not has_start and not has_end:
        return None
    if has_start != has_end:
        missing = end_field if has_start else start_field
        raise ValueError(f"{start_field} and {end_field} must be supplied together; missing {missing}.")

    start = _parse_date(start_raw, start_field)
    end = _parse_date(end_raw, end_field)
    if start > end:
        raise ValueError(f"{start_field} ({start_raw}) must not be after {end_field} ({end_raw}).")
    return start, end


def parse_request(event):
    params = parse_event_body(event)
    if not isinstance(params, dict):
        raise ValueError("Request must be a JSON object.")
    return {
        "country": params.get("country"),
        "rating_range": parse_date_pair(params, "rating"),
        "type_range": parse_date_pair(params, "type"),
    }


# ---------------------------------------------------------------------------
# Data loading (both paths return the same normalized DataFrame)
# ---------------------------------------------------------------------------

def _normalize_type(value):
    """Accept "Non-Profit", "non_profit", "non profit" (and the for_profit forms)."""
    key = re.sub(r"[-\s]+", "_", str(value).strip().lower())
    return key if key in TYPE_KEYS else None


def _normalize_frame(df):
    df = df.copy()
    df["org_rating"] = pd.to_numeric(df["org_rating"], errors="coerce")
    df["org_type_key"] = df["org_type"].map(_normalize_type)
    created = pd.to_datetime(df["created_at"], errors="coerce")
    if getattr(created.dt, "tz", None) is not None:
        created = created.dt.tz_localize(None)
    df["created_at"] = created.dt.normalize()
    df = df.dropna(subset=["created_at"])
    return df[DATA_COLUMNS].reset_index(drop=True)


def _first_existing(directory, *names):
    for name in names:
        path = os.path.join(directory, name)
        if os.path.exists(path):
            return path
    raise FileNotFoundError(f"None of {names} found in {directory}")


def load_mock_data(mock_dir=None):
    mock_dir = mock_dir or os.environ.get("MOCK_DATA_DIR") or DEFAULT_MOCK_DIR
    # Keep everything as text: avoids "NA"/"NULL" becoming NaN and keeps join keys comparable.
    read = lambda path: pd.read_csv(path, dtype=str, keep_default_na=False)

    orgs = read(_first_existing(mock_dir, "organizations.csv"))
    states = read(_first_existing(mock_dir, "state.csv", "states.csv"))
    countries = read(_first_existing(mock_dir, "country.csv", "countries.csv"))

    merged = orgs.merge(states[["state_id", "country_id"]], on="state_id", how="left")
    merged = merged.merge(
        countries[["country_id", "country_code", "country_name"]], on="country_id", how="left"
    )
    return _normalize_frame(merged)


def load_db_data():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed; set USE_MOCK_DATA=true or install it.")

    schema = os.environ.get("DB_SCHEMA", DEFAULT_SCHEMA)
    # Schema comes from Lambda configuration, never from the request; still restrict it.
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise RuntimeError("DB_SCHEMA contains invalid characters.")

    # KNOWN PRE-DEPLOYMENT CONCERN: column names follow issue #380 and the mock CSVs
    # (organizations.state_id, organizations.org_rating). database/mock-data-generation/
    # db_info.json instead lists organizations.state_code and organizations.rating.
    # Confirm against the real table before deploying.
    query = f"""
        SELECT o.org_id, o.org_rating, o.org_type, o.created_at,
               c.country_code, c.country_name
        FROM {schema}.organizations o
        LEFT JOIN {schema}.state s   ON o.state_id = s.state_id
        LEFT JOIN {schema}.country c ON s.country_id = c.country_id
    """
    conn = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        sslmode="require",
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
    finally:
        conn.close()
    return _normalize_frame(pd.DataFrame(rows, columns=columns))


def load_data():
    if os.environ.get("USE_MOCK_DATA", "false").strip().lower() == "true":
        return load_mock_data()
    return load_db_data()


# ---------------------------------------------------------------------------
# Filtering and chart builders
# ---------------------------------------------------------------------------

def _normalize_country(value):
    return str(value).strip().upper().replace(" ", "_")


def filter_country(df, country):
    if country is None or _normalize_country(country) in ("", "ALL"):
        return df
    wanted = _normalize_country(country)
    codes = df["country_code"].fillna("").map(_normalize_country)
    names = df["country_name"].fillna("").map(_normalize_country)
    return df[(codes == wanted) | (names == wanted)]


def _window(range_key, today):
    """Inclusive (start, end) for a fixed range; (None, None) means unbounded."""
    if range_key == "7D":  # 7 calendar days including today
        return today - pd.Timedelta(days=6), today
    if range_key == "30D":  # 30 calendar days including today
        return today - pd.Timedelta(days=29), today
    if range_key == "1Y":
        return today - pd.DateOffset(years=1), today
    return None, None


def _in_window(df, start, end):
    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= df["created_at"] >= start
    if end is not None:
        mask &= df["created_at"] <= end
    return df[mask]


def build_rating_distribution(df, start=None, end=None):
    ratings = _in_window(df, start, end)["org_rating"].dropna()
    ratings = ratings[ratings.isin([1, 2, 3, 4, 5])].astype(int)
    counts = ratings.value_counts().sort_index()
    return [{"rating": int(r), "count": int(c)} for r, c in counts.items()]


def _cumulative_series(df, start, end, monthly):
    """Sparse periods inside [start, end]; counts include orgs created before start."""
    baseline = 0 if start is None else int((df["created_at"] < start).sum())
    windowed = _in_window(df, start, end)
    fmt = "%Y-%m" if monthly else "%Y-%m-%d"
    per_period = windowed["created_at"].dt.strftime(fmt).value_counts().sort_index()
    running = baseline + per_period.cumsum()
    return [{"period": p, "count": int(c)} for p, c in running.items()]


def build_organization_mix_trend(df, start=None, end=None, monthly=False):
    return {
        key: _cumulative_series(df[df["org_type_key"] == key], start, end, monthly)
        for key in ("non_profit", "for_profit")
    }


def empty_charts():
    return {
        "rating_distribution": [],
        "organization_mix_trend": {"non_profit": [], "for_profit": []},
    }


def build_analytics(df, country=None, rating_range=None, type_range=None, today=None):
    """Assemble the response body. `today` is injectable for deterministic tests."""
    df = filter_country(df, country)

    if rating_range or type_range:
        custom = empty_charts()
        if rating_range:
            custom["rating_distribution"] = build_rating_distribution(df, *rating_range)
        if type_range:
            custom["organization_mix_trend"] = build_organization_mix_trend(df, *type_range)
        return {"Custom": custom}

    today = pd.Timestamp(today).normalize() if today is not None else pd.Timestamp.now().normalize()
    body = {}
    for range_key in FIXED_RANGES:
        start, end = _window(range_key, today)
        body[range_key] = {
            "rating_distribution": build_rating_distribution(df, start, end),
            "organization_mix_trend": build_organization_mix_trend(
                df, start, end, monthly=range_key in ("1Y", "All")
            ),
        }
    body["Custom"] = empty_charts()
    return body


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    try:
        request = parse_request(event)
    except ValueError as e:
        return build_response(400, {"error": str(e)})

    try:
        df = load_data()
        return build_response(200, build_analytics(df, **request))
    except Exception as e:
        print(f"rating_type_analytics failed: {e}")
        return build_response(500, {"error": "Failed to compute rating and type analytics."})


if __name__ == "__main__":
    os.environ.setdefault("USE_MOCK_DATA", "true")

    # NOTE: in the current mock CSVs every state has country_id=1 (AFGHANISTAN),
    # so "AFG" is the country code that matches the mock organizations.
    scenarios = [
        ("Empty request", {}),
        ("Country filter", {"country": "AFG"}),
        ("Rating custom range", {"rating_start_date": "2025-01-01", "rating_end_date": "2025-12-31"}),
        ("Type custom range", {"type_start_date": "2024-01-01", "type_end_date": "2025-12-31"}),
        ("Both custom ranges", {
            "rating_start_date": "2025-01-01", "rating_end_date": "2025-12-31",
            "type_start_date": "2024-01-01", "type_end_date": "2025-12-31",
        }),
    ]
    for i, (title, event) in enumerate(scenarios):
        if i:
            print()
        print(f"=== {title}: {json.dumps(event)}")
        result = lambda_handler(event, None)
        print(f"statusCode: {result['statusCode']}")
        print(json.dumps(json.loads(result["body"]), indent=2))
