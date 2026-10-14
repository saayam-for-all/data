"""Lambda entry point for Size & Contribution Analytics (#376).

Two charts for the org dashboard's Size & Contribution tab:
organizations_by_size (organization counts by org_size category) and
collaborator_vs_contributor (two independent counts -- is_collaborator and
is_contributor are separate flags, not a partition, so they are not
expected to sum to the bucket total or to each other).

Response contract:
  - No Custom date-range params -> all 4 fixed buckets ("7D"/"30D"/"1Y"/
    "All") plus a "Custom" key with both charts empty. Exactly 5 top-level
    keys.
  - size_start_date/size_end_date and/or contribution_start_date/
    contribution_end_date supplied -> exactly 1 top-level key, "Custom".
    organizations_by_size is populated if the size pair was given,
    collaborator_vs_contributor if the contribution pair was given --
    independently, so both can populate at once (the issue explicitly
    calls out a known bug elsewhere where supplying both silently drops
    the second one -- this implementation must not replicate that). The 4
    fixed buckets are dropped entirely in this mode, same contract as
    #380.

Both charts are window-scoped snapshots, not cumulative like Growth &
Location's total_organizations -- each bucket reflects only organizations
created within that bucket's own window.

Data source: pandas-backed mock CSVs (USE_MOCK_DATA=true, the default) for
local dev, or Postgres via an optional psycopg2 import otherwise -- this
file must still import and run the mock path standalone when psycopg2
isn't installed.

Single file per the existing analytics Lambda convention in this
directory (see kpi_api_analytics.py, growth_location_analytics.py,
rating_type_analytics.py).
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

try:
    import psycopg2
except ImportError:  # pragma: no cover - exercised only when the driver is absent
    psycopg2 = None

# ---------------------------------------------------------------------------
# Data loading (mock CSVs, or Postgres via an optional psycopg2 import)
# ---------------------------------------------------------------------------

# is_contributor is deliberately NOT required: some datasets predate that
# column, and the issue requires degrading to Contributor=0 rather than
# failing to load.
REQUIRED_COLUMNS = {
    "organizations": ("org_id", "org_size", "is_collaborator", "org_type", "state_id", "created_at"),
    "states": ("state_id", "country_id"),
    "countries": ("country_id", "country_code"),
}

_NON_PROFIT_ALIASES = {"non_profit", "nonprofit", "non-profit", "not_for_profit"}
_FOR_PROFIT_ALIASES = {"for_profit", "forprofit", "for-profit"}
ORG_TYPES = ("non_profit", "for_profit")

_TRUE_VALUES = {"true", "1", "yes", "y", "t"}
_FALSE_VALUES = {"false", "0", "no", "n", "f"}

# Display-order hint only -- NOT a validation allowlist and NOT used to
# zero-fill or restrict results. organizations_by_size emits whatever
# org_size values are actually present in the window, using the raw value
# as-is; this just orders the common three categories the way a human
# reading the chart would expect, with any other value appended after.
_SIZE_DISPLAY_ORDER = {"small": 0, "medium": 1, "large": 2}

DB_SCHEMA = os.environ.get("ORG_ANALYTICS_SCHEMA", "virginia_dev_saayam_rdbms")


class DataLoadError(ValueError):
    """Raised when the input data (mock CSVs or Postgres) is missing, malformed, or invalid."""


def _use_mock_data():
    return os.environ.get("USE_MOCK_DATA", "true").strip().lower() == "true"


def _mock_data_dir(data_dir=None):
    if data_dir is not None:
        return data_dir
    configured = os.environ.get("MOCK_DATA_DIR")
    if not configured:
        raise DataLoadError(
            "No data directory given: pass data_dir or set MOCK_DATA_DIR"
        )
    return configured


def _read_csv(directory, filename, required_columns):
    path = os.path.join(directory, filename)
    if not os.path.isfile(path):
        raise DataLoadError(f"Missing required file: {path}")
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError as exc:
        raise DataLoadError(f"{filename}: file is empty") from exc
    except pd.errors.ParserError as exc:
        raise DataLoadError(f"{filename}: could not be parsed as CSV") from exc

    missing = set(required_columns) - set(df.columns)
    if missing:
        raise DataLoadError(f"{filename}: missing required columns: {sorted(missing)}")
    return df


def _normalize_org_type(series, source):
    """Maps common encodings ("Non-Profit", "nonprofit", ...) onto exactly
    "non_profit"/"for_profit". Anything unrecognized fails loud rather than
    silently miscategorizing that organization (same precedent as #380).
    """
    normalized = series.astype(str).str.strip().str.lower()
    mapped = normalized.where(~normalized.isin(_NON_PROFIT_ALIASES), "non_profit")
    mapped = mapped.where(~normalized.isin(_FOR_PROFIT_ALIASES), "for_profit")

    unrecognized = ~mapped.isin(ORG_TYPES)
    if unrecognized.any():
        bad_values = sorted(set(series[unrecognized].astype(str)))
        raise DataLoadError(
            f"{source}: column 'org_type' has unrecognized values {bad_values}; "
            f"expected one of {sorted(_NON_PROFIT_ALIASES | _FOR_PROFIT_ALIASES)}"
        )
    return mapped


def _normalize_boolean(series, column, source):
    normalized = series.astype(str).str.strip().str.lower()
    unrecognized = ~normalized.isin(_TRUE_VALUES | _FALSE_VALUES)
    if unrecognized.any():
        bad_values = sorted(set(series[unrecognized].astype(str)))
        raise DataLoadError(
            f"{source}: column '{column}' has unrecognized values {bad_values}; "
            f"expected one of {sorted(_TRUE_VALUES | _FALSE_VALUES)}"
        )
    return normalized.isin(_TRUE_VALUES)


def _normalize_created_at(series, source):
    # Parsed element-wise rather than via pd.to_datetime(series, ...) directly:
    # that column-wide fast path infers ONE format from an early value and
    # applies it to the whole column, silently marking every row in a
    # different (but valid) format as unparseable.
    parsed = series.apply(lambda value: pd.to_datetime(value, utc=True, errors="coerce"))
    if parsed.isna().any():
        bad_rows = series[parsed.isna()].tolist()
        raise DataLoadError(f"{source}: column 'created_at' has unparseable values {bad_rows}")
    return pd.to_datetime(parsed, utc=True)  # normalize dtype to datetime64[ns, UTC]


def _assert_unique_key(df, column, filename):
    """A duplicate join key on the right side of a left-merge silently
    fans out matching rows on the left -- e.g. a repeated state_id in
    states.csv would double-count every organization in that state, with
    no error. Catch it before the merge, not after.
    """
    duplicates = df[column][df[column].duplicated()]
    if not duplicates.empty:
        bad_ids = sorted(duplicates.unique().tolist())
        raise DataLoadError(
            f"{filename}: column '{column}' has duplicate value(s) {bad_ids}; "
            f"expected each {column} to appear at most once"
        )


def _finish_organizations(organizations, source):
    """Shared normalization for the organizations frame, regardless of
    whether it came from CSV or Postgres.
    """
    organizations = organizations.copy()
    organizations["org_size"] = organizations["org_size"].astype(str).str.strip()
    organizations["org_type"] = _normalize_org_type(organizations["org_type"], source)
    organizations["is_collaborator"] = _normalize_boolean(
        organizations["is_collaborator"], "is_collaborator", source
    )
    if "is_contributor" in organizations.columns:
        organizations["is_contributor"] = _normalize_boolean(
            organizations["is_contributor"], "is_contributor", source
        )
    else:
        organizations["is_contributor"] = False
    organizations["created_at"] = _normalize_created_at(organizations["created_at"], source)
    return organizations


def _load_mock_data(data_dir=None):
    """Loads organizations/states/countries CSVs and returns one joined
    DataFrame, one row per organization with a `country_code` column
    attached via states.country_id -> countries.country_id.
    """
    directory = _mock_data_dir(data_dir)

    organizations = _read_csv(directory, "organizations.csv", REQUIRED_COLUMNS["organizations"])
    states = _read_csv(directory, "states.csv", REQUIRED_COLUMNS["states"])
    countries = _read_csv(directory, "countries.csv", REQUIRED_COLUMNS["countries"])

    _assert_unique_key(states, "state_id", "states.csv")
    _assert_unique_key(countries, "country_id", "countries.csv")

    organizations = _finish_organizations(organizations, "organizations.csv")

    merged = organizations.merge(
        states[["state_id", "country_id"]], on="state_id", how="left"
    ).merge(
        countries[["country_id", "country_code"]], on="country_id", how="left"
    )

    unmatched = merged["country_code"].isna()
    if unmatched.any():
        bad_ids = sorted(merged.loc[unmatched, "state_id"].unique().tolist())
        raise DataLoadError(
            f"organizations.csv: state_id(s) {bad_ids} do not resolve to a country via "
            f"states.csv -> countries.csv"
        )

    return merged


def _load_postgres_data():
    """Real-DB counterpart to _load_mock_data(): same join, same columns,
    same normalization, so the analytics functions below don't care which
    source produced the DataFrame. Only reached when USE_MOCK_DATA=false.
    """
    if psycopg2 is None:
        raise DataLoadError(
            "USE_MOCK_DATA is false but psycopg2 is not installed; "
            "install psycopg2 or set USE_MOCK_DATA=true"
        )

    query = f"""
        SELECT
            o.org_id AS org_id,
            o.org_size AS org_size,
            o.is_collaborator AS is_collaborator,
            o.is_contributor AS is_contributor,
            o.org_type AS org_type,
            o.state_id AS state_id,
            o.created_at AS created_at,
            c.country_code AS country_code
        FROM {DB_SCHEMA}.organizations o
        LEFT JOIN {DB_SCHEMA}.states s ON s.state_id = o.state_id
        LEFT JOIN {DB_SCHEMA}.countries c ON c.country_id = s.country_id
    """
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST"),
            port=os.environ.get("DB_PORT"),
            dbname=os.environ.get("DB_NAME"),
            user=os.environ.get("DB_USER"),
            password=os.environ.get("DB_PASSWORD"),
        )
    except psycopg2.OperationalError as exc:
        raise DataLoadError(f"Failed to connect to Postgres: {exc}") from exc

    try:
        df = pd.read_sql(query, conn)
    finally:
        conn.close()

    unmatched = df["country_code"].isna()
    if unmatched.any():
        bad_ids = sorted(df.loc[unmatched, "state_id"].unique().tolist())
        raise DataLoadError(
            f"organizations: state_id(s) {bad_ids} do not resolve to a country via "
            f"states -> countries"
        )

    return _finish_organizations(df, "organizations (postgres)")


def load_data(data_dir=None):
    if _use_mock_data():
        return _load_mock_data(data_dir)
    return _load_postgres_data()


# ---------------------------------------------------------------------------
# Date-window resolution
# ---------------------------------------------------------------------------

_DATE_FORMAT = "%Y-%m-%d"


class DateRangeError(ValueError):
    """Raised for invalid or incomplete Custom date-range parameters."""


def _calendar_months_back(now, n):
    """1st of the month that is (n-1) months before `now`'s month."""
    year, month = now.year, now.month - (n - 1)
    while month < 1:
        month += 12
        year -= 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def fixed_windows(now):
    """Returns {bucket: (start, end)} for the four fixed buckets.
    start is None for "All" (unbounded). end is always `now`.
    """
    return {
        "7D": (now - timedelta(days=7), now),
        "30D": (now - timedelta(days=30), now),
        "1Y": (_calendar_months_back(now, 12), now),
        "All": (None, now),
    }


def parse_custom_pair(params, start_key, end_key):
    """Parses one Custom date pair.

    Returns (start, end) as UTC-aware datetimes (end is exclusive, i.e. the
    start of the day *after* the supplied end date, since end dates are
    inclusive of the whole calendar day), or None if neither key was
    supplied.

    Raises DateRangeError if only one of the pair was supplied, either
    value fails to parse, or start is after end.
    """
    start_raw = params.get(start_key)
    end_raw = params.get(end_key)

    if start_raw is None and end_raw is None:
        return None
    if start_raw is None or end_raw is None:
        raise DateRangeError(f"{start_key} and {end_key} must be supplied together")

    try:
        start = datetime.strptime(start_raw, _DATE_FORMAT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError) as exc:
        raise DateRangeError(f"Invalid date format for {start_key}: {start_raw!r}") from exc
    try:
        end = datetime.strptime(end_raw, _DATE_FORMAT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError) as exc:
        raise DateRangeError(f"Invalid date format for {end_key}: {end_raw!r}") from exc

    if start > end:
        raise DateRangeError(f"{start_key} must be on or before {end_key}")

    return start, end + timedelta(days=1)  # end date is inclusive of the whole day


# ---------------------------------------------------------------------------
# Filters and chart calculations
# ---------------------------------------------------------------------------

def filter_country(df, country):
    """Restricts to rows whose country_code matches `country` (case-insensitive).
    A no-op if `country` is None/empty/"ALL".
    """
    if not country:
        return df
    normalized = country.strip().upper()
    if normalized == "ALL":
        return df
    return df[df["country_code"].str.upper() == normalized]


def filter_organization_type(df, organization_type):
    """Restricts to rows whose org_type matches `organization_type`
    (accepting the same aliases as the loader's normalization).
    A no-op if `organization_type` is None/empty/"ALL".
    """
    if not organization_type:
        return df
    normalized = organization_type.strip().lower()
    if normalized == "all":
        return df
    if normalized in _NON_PROFIT_ALIASES:
        normalized = "non_profit"
    elif normalized in _FOR_PROFIT_ALIASES:
        normalized = "for_profit"
    return df[df["org_type"] == normalized]


def _window(df, start, end):
    windowed = df[df["created_at"] < end]
    return windowed[windowed["created_at"] >= start] if start is not None else windowed


def _size_sort_key(size):
    return (_SIZE_DISPLAY_ORDER.get(size, len(_SIZE_DISPLAY_ORDER)), size)


def compute_organizations_by_size(df, start, end):
    """Organization counts grouped by org_size within the window, one row
    per category actually present -- no zero-filling, no hardcoded enum
    list, raw value emitted as-is.
    """
    windowed = _window(df, start, end)
    if windowed.empty:
        return []

    counts = windowed.groupby("org_size").size()
    sizes = sorted(counts.index, key=_size_sort_key)
    return [{"size": size, "count": int(counts[size])} for size in sizes]


def compute_collaborator_vs_contributor(df, start, end):
    """Always exactly 2 rows -- Collaborator and Contributor -- each
    computed independently against the window's total organization count.
    Not a partition: the two counts/percentages are not expected to sum to
    the total or to each other.
    """
    windowed = _window(df, start, end)
    total = len(windowed)

    def _row(label, column):
        count = int(windowed[column].sum()) if total else 0
        percentage = round((count / total) * 100, 1) if total else 0.0
        return {"type": label, "count": count, "percentage": percentage}

    return [
        _row("Collaborator", "is_collaborator"),
        _row("Contributor", "is_contributor"),
    ]


def build_bucket(df, start, end):
    return {
        "organizations_by_size": compute_organizations_by_size(df, start, end),
        "collaborator_vs_contributor": compute_collaborator_vs_contributor(df, start, end),
    }


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
ALL_BUCKETS = FIXED_BUCKETS + ("Custom",)

_JSON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}

# Cached per warm Lambda instance, same rationale as #336/#380: a cold
# start pays for load_data() once and every subsequent warm call on that
# instance reuses the same DataFrame instead of re-reading the CSVs from
# disk.
_cached_df = None


def _get_data():
    global _cached_df
    if _cached_df is None:
        _cached_df = load_data()
    return _cached_df


def _parse_event_body(event):
    """Accepts a direct JSON-object event or an API Gateway proxy event
    whose `body` is a JSON string. A missing/null proxy body is empty.
    """
    if not isinstance(event, dict):
        raise ValueError("event must be a JSON object")
    if "body" not in event:
        return event

    raw_body = event["body"]
    if raw_body is None:
        return {}
    if isinstance(raw_body, dict):
        return raw_body
    return json.loads(raw_body)


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": dict(_JSON_HEADERS),
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    del context
    try:
        params = _parse_event_body(event)
    except (ValueError, json.JSONDecodeError) as exc:
        return _response(400, {"error": f"Invalid request body: {exc}"})

    try:
        size_custom = parse_custom_pair(params, "size_start_date", "size_end_date")
        contribution_custom = parse_custom_pair(
            params, "contribution_start_date", "contribution_end_date"
        )
    except DateRangeError as exc:
        return _response(400, {"error": str(exc)})

    try:
        df = _get_data()
    except DataLoadError as exc:
        return _response(500, {"error": f"Failed to load analytics data: {exc}"})

    df = filter_country(df, params.get("country"))
    df = filter_organization_type(df, params.get("organization_type"))

    if size_custom is None and contribution_custom is None:
        now = datetime.now(timezone.utc)
        result = {}
        for bucket, (start, end) in fixed_windows(now).items():
            result[bucket] = build_bucket(df, start, end)
        result["Custom"] = {"organizations_by_size": [], "collaborator_vs_contributor": []}
        assert tuple(result) == ALL_BUCKETS, "unexpected bucket configuration"
        return _response(200, result)

    # Pre-initialize both keys empty, then overwrite each independently --
    # guarantees both are always present even when only one pair is
    # supplied, and guarantees both populate when both pairs are supplied
    # (the known "silently drops the second one" bug this issue warns
    # against doing).
    custom = {"organizations_by_size": [], "collaborator_vs_contributor": []}
    if size_custom:
        size_start, size_end = size_custom
        custom["organizations_by_size"] = compute_organizations_by_size(df, size_start, size_end)
    if contribution_custom:
        contribution_start, contribution_end = contribution_custom
        custom["collaborator_vs_contributor"] = compute_collaborator_vs_contributor(
            df, contribution_start, contribution_end
        )

    return _response(200, {"Custom": custom})


def _run_local_samples():
    """Prints the handler's output for a handful of representative requests.
    Run with `MOCK_DATA_DIR=/path/to/csvs python size_contribution_analytics.py`.
    """
    samples = {
        "no params": {},
        "country filter only": {"country": "USA"},
        "country ALL is a no-op": {"country": "ALL"},
        "organization_type filter only": {"organization_type": "non_profit"},
        "size Custom only": {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"},
        "contribution Custom only": {
            "contribution_start_date": "2025-01-01",
            "contribution_end_date": "2025-12-31",
        },
        "both Custom ranges": {
            "size_start_date": "2026-01-01",
            "size_end_date": "2026-06-30",
            "contribution_start_date": "2025-01-01",
            "contribution_end_date": "2025-12-31",
        },
        "lone size_start_date (should be 400)": {"size_start_date": "2026-01-01"},
        "malformed date (should be 400)": {"size_start_date": "not-a-date", "size_end_date": "2026-06-30"},
        "start after end (should be 400)": {"size_start_date": "2026-06-30", "size_end_date": "2026-01-01"},
    }
    for label, event in samples.items():
        print(f"\n=== {label} ===")
        print(json.dumps(event))
        response = lambda_handler(event, None)
        print(f"status={response['statusCode']}")
        print(json.dumps(json.loads(response["body"]), indent=2))


if __name__ == "__main__":
    if not os.environ.get("MOCK_DATA_DIR"):
        print("Set MOCK_DATA_DIR to a directory with organizations/states/countries.csv")
    else:
        _run_local_samples()
