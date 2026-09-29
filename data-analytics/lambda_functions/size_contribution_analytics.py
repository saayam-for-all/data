"""
Size & Contribution Analytics API for the Organization Analytics dashboard
(issue #376).

Standalone function -- not a refactor of organization_analytics.py -- that
returns data for the "Size & Contribution" tab:

  - Organizations by Size: organization counts by org_size category
    (small/medium/large), window-scoped.
  - Collaborators vs Contributors: two independently-computed counts
    (count(is_collaborator=True), count(is_contributor=True)) against the
    same window's total organization count. These are NOT a partition of
    each other -- an org can be both, either, or neither -- so the two
    counts/percentages are not expected to sum to the window total.

Response shape depends on which Custom params are present:
  - Neither size_start_date/size_end_date nor contribution_start_date/
    contribution_end_date supplied: full response with exactly the 5
    top-level keys "7D"/"30D"/"1Y"/"All"/"Custom".
  - Either or both Custom pairs supplied: response has exactly 1 top-level
    key, "Custom" -- no fixed buckets are computed at all. Each Custom
    sub-chart is populated independently based on which pair was given;
    supplying both populates both (no priority, no dropping one).

Data source: organizations.csv / states.csv / countries.csv, loaded with
pandas when USE_MOCK_DATA=true (default here, since this file is meant to
run standalone without AWS/Postgres for local testing). psycopg2 is an
optional import for the real Postgres path, exactly like the existing
analytics Lambdas -- this file still runs with USE_MOCK_DATA=true even
when psycopg2 isn't installed. Mock CSVs are local-only and are NOT
committed as part of this PR.
"""

import json
import os
from datetime import datetime, timedelta

import pandas as pd

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # psycopg2 isn't required for the USE_MOCK_DATA path.
    psycopg2 = None
    RealDictCursor = None

USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "true").lower() == "true"

MOCK_DATA_DIR = os.environ.get(
    "MOCK_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data"),
)

ORGANIZATIONS_CSV = os.path.join(MOCK_DATA_DIR, "organizations.csv")
STATES_CSV = os.path.join(MOCK_DATA_DIR, "states.csv")
COUNTRIES_CSV = os.path.join(MOCK_DATA_DIR, "countries.csv")

DB_SCHEMA = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")

TRUE_VALUES = {"true", "t", "1", "yes", "y"}
FALSE_VALUES = {"false", "f", "0", "no", "n", ""}


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


def get_default_full_response():
    empty_bucket = {"organizations_by_size": [], "collaborator_vs_contributor": []}
    return {
        "7D": json.loads(json.dumps(empty_bucket)),
        "30D": json.loads(json.dumps(empty_bucket)),
        "1Y": json.loads(json.dumps(empty_bucket)),
        "All": json.loads(json.dumps(empty_bucket)),
        "Custom": json.loads(json.dumps(empty_bucket)),
    }


# ---------------------------------------------------------------------------
# Data loading (mock / pandas path)
# ---------------------------------------------------------------------------

def _coerce_bool(value):
    """Converts a CSV cell to a real bool, handling bool/numeric/string forms.

    Plain `.astype(bool)` is unsafe: pandas may read a boolean column as
    dtype=object (mixed casing, blanks, numeric-looking values), and
    Python's bool() on any non-empty string -- including "False" or "0"
    -- returns True, silently overcounting.
    """
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    print(f"Unrecognized boolean value {value!r}; treating as False")
    return False


def load_data_from_csv(data_dir=None):
    """Loads organizations/states/countries CSVs into DataFrames.

    Returns empty-but-correctly-shaped DataFrames if a file is missing or
    empty, so downstream aggregation code doesn't need to special-case it.
    is_contributor is optional -- if the column isn't present at all, it's
    simply left out of df_orgs, and fetch_collaborator_vs_contributor
    degrades Contributor to 0 rather than crashing.
    """
    org_path = os.path.join(data_dir, "organizations.csv") if data_dir else ORGANIZATIONS_CSV
    states_path = os.path.join(data_dir, "states.csv") if data_dir else STATES_CSV
    countries_path = os.path.join(data_dir, "countries.csv") if data_dir else COUNTRIES_CSV

    try:
        df_orgs = pd.read_csv(org_path)
        df_orgs["created_at"] = pd.to_datetime(df_orgs["created_at"], errors="coerce")
        if "is_collaborator" in df_orgs.columns:
            df_orgs["is_collaborator"] = df_orgs["is_collaborator"].apply(_coerce_bool)
        if "is_contributor" in df_orgs.columns:
            df_orgs["is_contributor"] = df_orgs["is_contributor"].apply(_coerce_bool)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        df_orgs = pd.DataFrame(columns=[
            "org_id", "org_size", "is_collaborator", "is_contributor",
            "org_type", "state_id", "created_at",
        ])

    try:
        df_states = pd.read_csv(states_path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        df_states = pd.DataFrame(columns=["state_id", "country_id"])

    try:
        df_countries = pd.read_csv(countries_path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        df_countries = pd.DataFrame(columns=["country_id", "country_code"])

    return df_orgs, df_states, df_countries


# ---------------------------------------------------------------------------
# Data loading (real Postgres path -- optional, mirrors organization_analytics.py)
# ---------------------------------------------------------------------------

def get_db_connection():
    """Builds a psycopg2 connection from DATABASE_URL or DB_* env vars.

    Only used when USE_MOCK_DATA is false. No boto3/SSM -- consistent with
    how organization_analytics.py and the Growth & Location API connect
    for local testing.
    """
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
    """Loads the same three tables from Postgres into DataFrames, using the
    same column set as load_data_from_csv so downstream code is identical
    regardless of data source."""
    conn = get_db_connection()
    try:
        df_orgs = pd.read_sql(
            f"SELECT org_id, org_size, is_collaborator, is_contributor, "
            f"org_type, state_id, created_at FROM {DB_SCHEMA}.organizations",
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
# Filters
# ---------------------------------------------------------------------------

def apply_filters(df_orgs, df_states, df_countries, country, organization_type):
    """Applies organization_type and country filters. country matches
    either country_code or country_name (case-insensitive); "ALL"/None/""
    means no filter for either param."""
    df = df_orgs

    if organization_type and str(organization_type).upper() != "ALL":
        df = df[df["org_type"].astype(str).str.lower() == str(organization_type).lower()]

    if country and str(country).upper() != "ALL":
        if df.empty or df_states.empty or df_countries.empty:
            return df.iloc[0:0]

        merge_cols = ["country_id", "country_code"]
        if "country_name" in df_countries.columns:
            merge_cols.append("country_name")

        merged = df.merge(df_states[["state_id", "country_id"]], on="state_id", how="left")
        merged = merged.merge(df_countries[merge_cols], on="country_id", how="left")

        target = str(country).upper()
        mask = merged["country_code"].astype(str).str.upper() == target
        if "country_name" in merged.columns:
            mask = mask | (merged["country_name"].astype(str).str.upper() == target)

        df = merged.loc[mask, df_orgs.columns.tolist()]

    return df


def _parse_date(value, field_name):
    try:
        return pd.Timestamp(datetime.strptime(value, "%Y-%m-%d"))
    except (ValueError, TypeError):
        raise InvalidFilterError(f"{field_name} must be a valid date in YYYY-MM-DD format")


def validate_date_pair(start_value, end_value, start_field, end_field):
    """Validates one start/end pair. Returns (start_ts, end_ts) or (None, None)
    if neither value was supplied. Raises InvalidFilterError on bad/partial input."""
    if start_value is None and end_value is None:
        return None, None
    if start_value is None or end_value is None:
        raise InvalidFilterError(f"Both {start_field} and {end_field} are required together")

    start_ts = _parse_date(start_value, start_field)
    end_ts = _parse_date(end_value, end_field)
    if start_ts > end_ts:
        raise InvalidFilterError(f"{start_field} must not be after {end_field}")

    end_ts = end_ts + timedelta(hours=23, minutes=59, seconds=59)
    return start_ts, end_ts


def get_fixed_window(bucket, now=None):
    """Returns (start_ts, end_ts) for a fixed bucket. start_ts is None for
    'All' (no lower bound)."""
    now = now or pd.Timestamp.now()
    end_ts = now
    if bucket == "7D":
        return end_ts - timedelta(days=7), end_ts
    if bucket == "30D":
        return end_ts - timedelta(days=30), end_ts
    if bucket == "1Y":
        # Calendar year, not a fixed 365-day approximation (drifts around
        # leap years and doesn't line up with "the last 12 months").
        return end_ts - pd.DateOffset(years=1), end_ts
    if bucket == "All":
        return None, end_ts
    raise ValueError(f"Unknown fixed bucket: {bucket}")


def window_df(df, window_start, window_end):
    if window_end is None or df.empty:
        return df.iloc[0:0]
    mask = df["created_at"] <= window_end
    if window_start is not None:
        mask &= df["created_at"] >= window_start
    return df.loc[mask]


# ---------------------------------------------------------------------------
# Organizations by Size
# ---------------------------------------------------------------------------

def fetch_organizations_by_size(df_window):
    """One row per org_size value actually present in the window (sparse,
    not zero-filled for absent categories) -- mirrors how Growth & Location
    omits empty periods rather than zero-filling them."""
    if df_window.empty or "org_size" not in df_window.columns:
        return []

    counts = df_window["org_size"].dropna().value_counts()
    if counts.empty:
        return []

    counts = counts.sort_values(ascending=False)
    return [{"size": size, "count": int(count)} for size, count in counts.items()]


# ---------------------------------------------------------------------------
# Collaborator vs Contributor
# ---------------------------------------------------------------------------

def fetch_collaborator_vs_contributor(df_window):
    """Exactly 2 rows (Collaborator, Contributor) when the window has any
    organizations, each computed independently against the window's total
    count -- not a partition, so they aren't expected to sum to the total.
    Degrades Contributor to 0 if is_contributor isn't in the data at all.
    Returns [] if the window is empty (no organizations at all)."""
    if df_window.empty:
        return []

    total = len(df_window)
    collaborator_count = int(df_window["is_collaborator"].sum()) if "is_collaborator" in df_window.columns else 0
    contributor_count = int(df_window["is_contributor"].sum()) if "is_contributor" in df_window.columns else 0

    return [
        {
            "type": "Collaborator",
            "count": collaborator_count,
            "percentage": round(collaborator_count / total * 100, 1) if total else 0.0,
        },
        {
            "type": "Contributor",
            "count": contributor_count,
            "percentage": round(contributor_count / total * 100, 1) if total else 0.0,
        },
    ]


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def _extract_payload(event):
    """Returns the request parameters as a plain dict.

    Supports both a direct dict (local testing / direct Lambda invoke) and
    an API Gateway proxy integration, where the actual payload is a JSON
    string under event["body"] (which may also be None).
    """
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
    except InvalidFilterError as e:
        return build_response(400, {"error": str(e)})

    country = event.get("country") or "ALL"
    organization_type = event.get("organization_type") or "ALL"

    try:
        size_start, size_end = validate_date_pair(
            event.get("size_start_date"), event.get("size_end_date"),
            "size_start_date", "size_end_date",
        )
        contribution_start, contribution_end = validate_date_pair(
            event.get("contribution_start_date"), event.get("contribution_end_date"),
            "contribution_start_date", "contribution_end_date",
        )
    except InvalidFilterError as e:
        return build_response(400, {"error": str(e)})

    try:
        df_orgs, df_states, df_countries = load_data()
    except Exception as e:
        print(f"Failed to load analytics data: {e}")
        return build_response(500, {"error": "Failed to load analytics data"})

    try:
        df_filtered = apply_filters(df_orgs, df_states, df_countries, country, organization_type)
    except Exception as e:
        print(f"Failed to apply filters: {e}")
        return build_response(500, {"error": "Failed to apply filters"})

    has_custom = size_start is not None or contribution_start is not None

    if has_custom:
        # Custom-only response: no fixed buckets at all. Each sub-chart
        # populates independently based on which pair was supplied -- both
        # can be populated at once, with no priority between them.
        response_body = {"Custom": {"organizations_by_size": [], "collaborator_vs_contributor": []}}

        if size_start is not None:
            try:
                size_window = window_df(df_filtered, size_start, size_end)
                response_body["Custom"]["organizations_by_size"] = fetch_organizations_by_size(size_window)
            except Exception as e:
                print(f"Custom organizations_by_size failed: {e}")

        if contribution_start is not None:
            try:
                contribution_window = window_df(df_filtered, contribution_start, contribution_end)
                response_body["Custom"]["collaborator_vs_contributor"] = fetch_collaborator_vs_contributor(contribution_window)
            except Exception as e:
                print(f"Custom collaborator_vs_contributor failed: {e}")

        return build_response(200, response_body)

    # No Custom params: full response with all 4 fixed buckets plus an
    # empty Custom.
    response_body = get_default_full_response()
    for bucket in ["7D", "30D", "1Y", "All"]:
        window_start, window_end = get_fixed_window(bucket)
        try:
            bucket_window = window_df(df_filtered, window_start, window_end)
            response_body[bucket] = {
                "organizations_by_size": fetch_organizations_by_size(bucket_window),
                "collaborator_vs_contributor": fetch_collaborator_vs_contributor(bucket_window),
            }
        except Exception as e:
            print(f"{bucket} failed: {e}")

    return build_response(200, response_body)


if __name__ == "__main__":
    scenarios = [
        ("No body", {}),
        ("Country filter by code (US)", {"country": "US"}),
        ("Country filter by name, case-insensitive (united states)", {"country": "united states"}),
        ("Organization type filter (non_profit)", {"organization_type": "non_profit"}),
        ("Size-range only Custom (Custom-only response)", {
            "size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
        }),
        ("Contribution-range only Custom (Custom-only response)", {
            "contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31",
        }),
        ("Both Custom ranges together (both sub-charts populated)", {
            "size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
            "contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31",
        }),
        ("Invalid: only half a pair supplied -> 400", {
            "size_start_date": "2026-01-01",
        }),
        ("Invalid: start_date after end_date -> 400", {
            "contribution_start_date": "2026-06-30", "contribution_end_date": "2026-01-01",
        }),
        ("Invalid: bad date format -> 400", {
            "size_start_date": "01/01/2026", "size_end_date": "2026-06-30",
        }),
    ]

    for title, event in scenarios:
        print(f"\n=== {title} ===")
        print(f"event: {json.dumps(event)}")
        result = lambda_handler(event, None)
        print(f"statusCode: {result['statusCode']}")
        print(result["body"])
