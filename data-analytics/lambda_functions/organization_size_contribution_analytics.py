"""Size & Contribution Analytics API for the Organization Dashboard (issue #376).

Standalone function (no DB) - reads organizations.csv, state.csv, and
country.csv, joins organizations -> states -> countries, and returns two
charts: organizations_by_size and collaborator_vs_contributor.

Unlike Growth & Location (#336), the response *shape* changes depending on
which Custom date-range params are supplied:

- Neither size_start_date/size_end_date nor contribution_start_date/
  contribution_end_date given: the response has all 5 fixed buckets
  (7D/30D/1Y/All/Custom), with Custom's two charts both empty.
- Either or both Custom pairs given: the response has exactly one top-level
  key, "Custom" - no 7D/30D/1Y/All at all. organizations_by_size populates
  if size_start_date/size_end_date was given; collaborator_vs_contributor
  populates if contribution_start_date/contribution_end_date was given -
  independently of each other, so both can populate at once. This
  deliberately does NOT replicate the early-return bug in the volunteer-side
  reference implementation (volunteer_application_analytics.py), where
  supplying both Custom pairs silently drops the second one.

state/country loading mirrors organization_growth_location_analytics.py. The
state.csv country_id=1 (Afghanistan) -> 233 (USA) data bug is fixed in the
CSV itself, not in this code.
"""
import json
import os
from datetime import datetime

import pandas as pd

try:
    import psycopg2
except ImportError:  # psycopg2 is only needed for the real Postgres path;
    psycopg2 = None  # the file still runs standalone with USE_MOCK_DATA=true.

DEFAULT_CSV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sql")
STANDARD_BUCKETS = ["7D", "30D", "1Y", "All"]
USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "true").strip().lower() == "true"

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


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
            return {}
    if isinstance(body, dict):
        return body
    return {}


def _response(status_code, payload):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(payload, default=str),
    }


_TRUE_TOKENS = {"true", "t", "1", "1.0", "yes", "y"}


def _to_bool(value):
    """Accepts bool, numeric 1/0, and strings like 'TRUE'/'true'/'1'/'yes'
    (any case, surrounding whitespace ignored). Anything else, including
    NaN, is False."""
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip().lower() in _TRUE_TOKENS


def _read_csv(csv_dir, *candidate_names):
    """Reads the first of candidate_names that exists in csv_dir. The repo
    has shipped these lookup tables under both singular (state.csv,
    country.csv) and plural (states.csv, countries.csv) names."""
    for name in candidate_names:
        path = os.path.join(csv_dir, name)
        if os.path.exists(path):
            return pd.read_csv(path)
    raise FileNotFoundError(f"None of {candidate_names} found in {csv_dir}")


def _normalize_enum(value):
    """'Non-Profit' / 'non_profit' / 'NON PROFIT' all normalize to the same
    token, so filters match regardless of how a source's enum is cased."""
    if value is None:
        return ""
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


class DateRangeError(ValueError):
    """A Custom date-range pair is missing a half, malformed, or inverted."""


def _parse_date_range(params, start_key, end_key):
    """Returns (start, end) as pandas Timestamps if both are present and
    valid, or (None, None) if neither is present. Raises DateRangeError for
    any half-supplied/malformed/inverted pair, so a bad Custom range fails
    the request instead of silently degrading."""
    start_raw = params.get(start_key)
    end_raw = params.get(end_key)

    if not start_raw and not end_raw:
        return None, None
    if not start_raw or not end_raw:
        raise DateRangeError(f"Both {start_key} and {end_key} are required together.")

    try:
        start = pd.Timestamp(start_raw)
        end = pd.Timestamp(end_raw)
    except (ValueError, TypeError):
        raise DateRangeError(f"{start_key}/{end_key} must be valid dates.")

    if pd.isna(start) or pd.isna(end):
        raise DateRangeError(f"{start_key}/{end_key} must be valid dates.")
    if start > end:
        raise DateRangeError(f"{start_key} must not be after {end_key}.")

    return start, end


# --- Data loading --------------------------------------------------------

def load_organizations(csv_dir=DEFAULT_CSV_DIR):
    df = pd.read_csv(os.path.join(csv_dir, "organizations.csv"))
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["is_collaborator"] = df["is_collaborator"].map(_to_bool)
    if "is_contributor" in df.columns:
        df["is_contributor"] = df["is_contributor"].map(_to_bool)
    else:
        df["is_contributor"] = False
    df["org_size_norm"] = df["org_size"].apply(_normalize_enum)
    df["org_type_norm"] = df["org_type"].apply(_normalize_enum)
    return df


def load_states(csv_dir=DEFAULT_CSV_DIR):
    df = _read_csv(csv_dir, "state.csv", "states.csv")
    df["country_id"] = pd.to_numeric(df["country_id"], errors="coerce")
    return df


def load_countries(csv_dir=DEFAULT_CSV_DIR):
    df = _read_csv(csv_dir, "country.csv", "countries.csv")
    df["country_id"] = pd.to_numeric(df["country_id"], errors="coerce")
    return df


def build_joined_dataframe(csv_dir=DEFAULT_CSV_DIR):
    orgs = load_organizations(csv_dir)
    states = load_states(csv_dir)
    countries = load_countries(csv_dir)

    merged = orgs.merge(
        states[["state_id", "country_id"]], on="state_id", how="left"
    ).merge(
        countries[["country_id", "country_name", "country_code"]], on="country_id", how="left"
    )
    merged["country_name"] = merged["country_name"].fillna("Unknown")
    merged["country_code"] = merged["country_code"].fillna("Unknown")
    return merged


def get_db_connection():
    """Real Postgres path. Connection params come from standard env vars
    rather than an SSM parameter name, since no organizations-table SSM
    parameter is established in this codebase yet (unlike volunteer_
    application_analytics.py's REAL_TABLE_*_VIRGINIA/_IRELAND constants) -
    confirm the right parameter/host against the real analytics DB setup
    before relying on this path in production."""
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is not installed; set USE_MOCK_DATA=true to use the CSV path."
        )
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def build_joined_dataframe_from_postgres():
    """Same shape as build_joined_dataframe(), sourced from Postgres instead
    of CSVs. org_size/is_contributor/state_id are carried over from the
    organizations table as ASSUMED columns per data-engineering/infrastructure/
    db/init/001_organizations.sql's disclaimer (no confirmed DDL for this
    table exists in the repo) - verify column names against the real
    virginia_dev_saayam_rdbms.organizations table before deploying this path."""
    conn = get_db_connection()
    try:
        orgs = pd.read_sql(
            """
            SELECT org_id, org_size, org_type, is_collaborator, is_contributor,
                   state_id, created_at
            FROM virginia_dev_saayam_rdbms.organizations
            """,
            conn,
        )
        states = pd.read_sql(
            "SELECT state_id, country_id FROM virginia_dev_saayam_rdbms.state", conn
        )
        countries = pd.read_sql(
            "SELECT country_id, country_name, country_code FROM virginia_dev_saayam_rdbms.country",
            conn,
        )
    finally:
        conn.close()

    orgs["created_at"] = pd.to_datetime(orgs["created_at"], errors="coerce")
    orgs["is_collaborator"] = orgs["is_collaborator"].map(_to_bool)
    if "is_contributor" in orgs.columns:
        orgs["is_contributor"] = orgs["is_contributor"].map(_to_bool)
    else:
        orgs["is_contributor"] = False
    orgs["org_size_norm"] = orgs["org_size"].apply(_normalize_enum)
    orgs["org_type_norm"] = orgs["org_type"].apply(_normalize_enum)

    merged = orgs.merge(states, on="state_id", how="left").merge(countries, on="country_id", how="left")
    merged["country_name"] = merged["country_name"].fillna("Unknown")
    merged["country_code"] = merged["country_code"].fillna("Unknown")
    return merged


def load_source_dataframe():
    if USE_MOCK_DATA:
        return build_joined_dataframe()
    return build_joined_dataframe_from_postgres()


# --- Filtering -------------------------------------------------------------

def apply_common_filters(df, country=None, organization_type=None):
    """country/organization_type apply the same way to both charts, in every
    response shape. 'ALL' (case-insensitive) or omitted means no filter."""
    filtered = df

    if country and _normalize_enum(country) != "all":
        target = _normalize_enum(country)
        mask = (
            filtered["country_name"].apply(_normalize_enum) == target
        ) | (
            filtered["country_code"].apply(_normalize_enum) == target
        )
        filtered = filtered[mask]

    if organization_type and _normalize_enum(organization_type) != "all":
        target = _normalize_enum(organization_type)
        filtered = filtered[filtered["org_type_norm"] == target]

    return filtered


def apply_window(df, window_start, window_end):
    if df.empty:
        return df
    valid = df.dropna(subset=["created_at"])
    if window_start is not None:
        valid = valid[valid["created_at"].dt.date >= window_start.date()]
    if window_end is not None:
        valid = valid[valid["created_at"].dt.date <= window_end.date()]
    return valid


# --- Aggregation -----------------------------------------------------------

def resolve_standard_window(bucket_key, reference_date):
    """(window_start, window_end) for the 4 non-Custom buckets."""
    reference_date = pd.Timestamp(reference_date)
    if bucket_key == "7D":
        return reference_date - pd.Timedelta(days=6), reference_date
    if bucket_key == "30D":
        return reference_date - pd.Timedelta(days=29), reference_date
    if bucket_key == "1Y":
        start = (reference_date - pd.DateOffset(months=11)).replace(day=1)
        return start, reference_date
    if bucket_key == "All":
        return None, reference_date
    raise ValueError(f"resolve_standard_window does not handle {bucket_key!r}")


def compute_organizations_by_size(df, window_start, window_end):
    """Flat array of {"size": ..., "count": ...}, one row per org_size
    category actually present in the window - no hardcoded category list, no
    zero-filling of absent categories (mirrors Growth & Location's sparse
    arrays). Uses the raw org_size value as it appears in the data."""
    windowed = apply_window(df, window_start, window_end)
    if windowed.empty:
        return []

    counts = windowed.groupby("org_size").size()
    return [{"size": size, "count": int(count)} for size, count in counts.items()]


def compute_collaborator_vs_contributor(df, window_start, window_end):
    """Exactly 2 rows, Collaborator and Contributor, each computed
    independently against the window's total organization count. Not a
    partition - an organization can be both, or neither - so the two counts
    (and percentages) are not expected to sum to the total or to 100."""
    windowed = apply_window(df, window_start, window_end)
    total = len(windowed)

    if total == 0:
        collaborator_count = 0
        contributor_count = 0
    else:
        collaborator_count = int(windowed["is_collaborator"].sum())
        contributor_count = int(windowed["is_contributor"].sum())

    def pct(count):
        return round((count / total) * 100, 1) if total else 0.0

    return [
        {"type": "Collaborator", "count": collaborator_count, "percentage": pct(collaborator_count)},
        {"type": "Contributor", "count": contributor_count, "percentage": pct(contributor_count)},
    ]


def build_bucket(df, size_window=None, contribution_window=None,
                  include_size=True, include_contribution=True):
    size_start, size_end = size_window if size_window else (None, None)
    contribution_start, contribution_end = contribution_window if contribution_window else (None, None)

    return {
        "organizations_by_size": compute_organizations_by_size(df, size_start, size_end) if include_size else [],
        "collaborator_vs_contributor": (
            compute_collaborator_vs_contributor(df, contribution_start, contribution_end)
            if include_contribution else []
        ),
    }


def generate_response(df, size_start=None, size_end=None, contribution_start=None,
                       contribution_end=None, reference_date=None):
    """size_start/size_end and contribution_start/contribution_end are each
    either both None (that pair wasn't supplied) or both set (validated
    upstream by _parse_date_range). If either pair is set, the response is
    Custom-only; otherwise it's the full 5-bucket response with an empty
    Custom."""
    has_size_range = size_start is not None and size_end is not None
    has_contribution_range = contribution_start is not None and contribution_end is not None

    if has_size_range or has_contribution_range:
        return {
            "Custom": build_bucket(
                df,
                size_window=(size_start, size_end) if has_size_range else None,
                contribution_window=(contribution_start, contribution_end) if has_contribution_range else None,
                include_size=has_size_range,
                include_contribution=has_contribution_range,
            )
        }

    reference_date = reference_date or datetime.now()
    response = {}
    for bucket_key in STANDARD_BUCKETS:
        window = resolve_standard_window(bucket_key, reference_date)
        response[bucket_key] = build_bucket(df, size_window=window, contribution_window=window)
    response["Custom"] = {"organizations_by_size": [], "collaborator_vs_contributor": []}
    return response


# --- Lambda entrypoint -----------------------------------------------------

def lambda_handler(event, context):
    try:
        params = parse_event_body(event)
        country = params.get("country", "ALL")
        organization_type = params.get("organization_type", "ALL")

        try:
            size_start, size_end = _parse_date_range(params, "size_start_date", "size_end_date")
            contribution_start, contribution_end = _parse_date_range(
                params, "contribution_start_date", "contribution_end_date"
            )
        except DateRangeError as exc:
            return _response(400, {"error": str(exc)})

        df = apply_common_filters(load_source_dataframe(), country=country, organization_type=organization_type)
        payload = generate_response(
            df,
            size_start=size_start, size_end=size_end,
            contribution_start=contribution_start, contribution_end=contribution_end,
        )
        return _response(200, payload)
    except Exception as exc:  # keep the dashboard from getting a raw 5xx traceback
        return _response(500, {"error": str(exc)})


if __name__ == "__main__":
    # Sample data (data-analytics/sql/organizations.csv) spans 2023-09 to
    # 2026-01, so a fixed reference_date inside that range gives non-empty
    # 7D/30D/1Y buckets for a local smoke test rather than relying on
    # whatever "today" happens to be when this is run.
    REFERENCE_DATE = datetime(2026, 1, 15)

    sample_events = {
        "no_body": {},
        "country_filter": {"country": "USA"},
        "org_type_filter": {"organization_type": "non_profit"},
        "size_custom_only": {"size_start_date": "2025-01-01", "size_end_date": "2026-01-15"},
        "contribution_custom_only": {
            "contribution_start_date": "2025-01-01", "contribution_end_date": "2026-01-15"
        },
        "both_custom": {
            "size_start_date": "2025-01-01", "size_end_date": "2026-01-15",
            "contribution_start_date": "2025-06-01", "contribution_end_date": "2026-01-15",
        },
    }

    joined = build_joined_dataframe()
    for name, event in sample_events.items():
        filtered = apply_common_filters(
            joined, country=event.get("country", "ALL"),
            organization_type=event.get("organization_type", "ALL"),
        )
        size_start, size_end = _parse_date_range(event, "size_start_date", "size_end_date")
        contribution_start, contribution_end = _parse_date_range(
            event, "contribution_start_date", "contribution_end_date"
        )
        result = generate_response(
            filtered,
            size_start=size_start, size_end=size_end,
            contribution_start=contribution_start, contribution_end=contribution_end,
            reference_date=REFERENCE_DATE,
        )
        print(f"--- {name} ---")
        print(json.dumps(result, indent=2, default=str))
