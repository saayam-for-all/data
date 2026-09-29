"""Lambda entry point for Rating & Type Analytics (#380).

Two charts for the org dashboard's Rating & Type tab: rating_distribution
(organization counts by star rating, 1-5) and organization_mix_trend
(cumulative organization counts by type -- non_profit/for_profit -- over
time).

Response contract:
  - No Custom date-range params -> all 4 fixed buckets ("7D"/"30D"/"1Y"/
    "All") plus a "Custom" key with both charts empty. Exactly 5 top-level
    keys.
  - rating_start_date/rating_end_date and/or type_start_date/type_end_date
    supplied -> exactly 1 top-level key, "Custom". rating_distribution is
    populated if the rating pair was given, organization_mix_trend if the
    type pair was given -- independently. The 4 fixed buckets are dropped
    entirely in this mode (unlike #336, where Custom always rides alongside
    the fixed buckets).

Data source: pandas-backed mock CSVs (USE_MOCK_DATA=true, the default) for
local dev, or Postgres via an optional psycopg2 import otherwise -- this
file must still import and run the mock path standalone when psycopg2
isn't installed.

Single file per the existing analytics Lambda convention in this
directory (see kpi_api_analytics.py, volunteer_application_analytics.py,
beneficiariesTrendAnalysis.py, growth_location_analytics.py).
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

REQUIRED_COLUMNS = {
    "organizations": ("org_id", "org_rating", "org_type", "state_id", "created_at"),
    "states": ("state_id", "country_id"),
    "countries": ("country_id", "country_code"),
}

_MIN_RATING = 1
_MAX_RATING = 5

ORG_TYPES = ("non_profit", "for_profit")
_NON_PROFIT_ALIASES = {"non_profit", "nonprofit", "non-profit", "not_for_profit"}
_FOR_PROFIT_ALIASES = {"for_profit", "forprofit", "for-profit"}

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


def _normalize_org_rating(series, source):
    numeric = pd.to_numeric(series, errors="coerce")
    bad = numeric.isna() | (numeric != numeric.round()) | (numeric < _MIN_RATING) | (numeric > _MAX_RATING)
    if bad.any():
        bad_values = sorted(set(series[bad].astype(str)))
        raise DataLoadError(
            f"{source}: column 'org_rating' has invalid values {bad_values}; "
            f"expected an integer between {_MIN_RATING} and {_MAX_RATING}"
        )
    return numeric.astype(int)


def _normalize_org_type(series, source):
    """Maps common encodings ("Non-Profit", "nonprofit", ...) onto exactly
    "non_profit"/"for_profit" -- the two keys the response contract
    requires. Anything unrecognized fails loud rather than silently
    dropping that organization from both series (same "loud, not silent"
    precedent as #336's is_collaborator normalization).
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

    organizations = organizations.copy()
    organizations["org_rating"] = _normalize_org_rating(organizations["org_rating"], "organizations.csv")
    organizations["org_type"] = _normalize_org_type(organizations["org_type"], "organizations.csv")
    organizations["created_at"] = _normalize_created_at(organizations["created_at"], "organizations.csv")

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
            o.org_rating AS org_rating,
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

    df["org_rating"] = _normalize_org_rating(df["org_rating"], "organizations (postgres)")
    df["org_type"] = _normalize_org_type(df["org_type"], "organizations (postgres)")
    df["created_at"] = _normalize_created_at(df["created_at"], "organizations (postgres)")
    return df


def load_data(data_dir=None):
    if _use_mock_data():
        return _load_mock_data(data_dir)
    return _load_postgres_data()


# ---------------------------------------------------------------------------
# Date-window resolution and the rating/type-mix calculations
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
    """Returns {bucket: (start, end, granularity)} for the four fixed buckets.

    start is None for "All" (unbounded). end is always `now`.
    """
    return {
        "7D": (now - timedelta(days=7), now, "day"),
        "30D": (now - timedelta(days=30), now, "day"),
        "1Y": (_calendar_months_back(now, 12), now, "month"),
        "All": (None, now, "month"),
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


def _period_label(ts, granularity):
    return ts.strftime("%Y-%m-%d") if granularity == "day" else ts.strftime("%Y-%m")


def filter_country(df, country):
    """Restricts to rows whose country_code matches `country` (case-insensitive).
    A no-op if `country` is None/empty/"ALL" -- "ALL" is the documented
    default meaning "every country", not a literal country code to match.
    """
    if not country:
        return df
    normalized = country.strip().upper()
    if normalized == "ALL":
        return df
    return df[df["country_code"].str.upper() == normalized]


def compute_rating_distribution(df, start, end):
    """Organization counts grouped by org_rating (1-5) within the window,
    ascending by rating. No zero-filling: a rating with no organizations in
    the window is simply absent rather than reported as a zero count.
    """
    upto_end = df[df["created_at"] < end]
    in_window = upto_end[upto_end["created_at"] >= start] if start is not None else upto_end

    if in_window.empty:
        return []

    counts = in_window.groupby("org_rating").size().sort_index()
    return [{"rating": int(rating), "count": int(count)} for rating, count in counts.items()]


def compute_organization_mix_trend(df, start, end, granularity):
    """Cumulative, all-time (never reset to the window start) organization
    counts per org_type, as of each period within the window -- mirrors
    growth_trend's total_organizations semantics from #336. Always returns
    both "non_profit" and "for_profit" keys, each independently sparse
    (a period appears in a type's series only if that type had activity in
    the window in that period).
    """
    upto_end = df[df["created_at"] < end]
    in_window = upto_end[upto_end["created_at"] >= start] if start is not None else upto_end

    trend = {org_type: [] for org_type in ORG_TYPES}
    if in_window.empty:
        return trend

    in_window = in_window.copy()
    in_window["period"] = in_window["created_at"].apply(lambda t: _period_label(t, granularity))

    upto_end = upto_end.copy()
    upto_end["period"] = upto_end["created_at"].apply(lambda t: _period_label(t, granularity))

    for org_type in ORG_TYPES:
        periods = sorted(in_window.loc[in_window["org_type"] == org_type, "period"].unique())
        type_upto_end = upto_end[upto_end["org_type"] == org_type]
        trend[org_type] = [
            {"period": p, "count": int((type_upto_end["period"] <= p).sum())} for p in periods
        ]

    return trend


def build_bucket(df, start, end, granularity):
    return {
        "rating_distribution": compute_rating_distribution(df, start, end),
        "organization_mix_trend": compute_organization_mix_trend(df, start, end, granularity),
    }


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
ALL_BUCKETS = FIXED_BUCKETS + ("Custom",)
_EMPTY_MIX_TREND = {org_type: [] for org_type in ORG_TYPES}

_JSON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}

# Cached per warm Lambda instance, same rationale as #336: a cold start pays
# for load_data() once and every subsequent warm call on that instance
# reuses the same DataFrame instead of re-reading the CSVs from disk.
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
        rating_custom = parse_custom_pair(params, "rating_start_date", "rating_end_date")
        type_custom = parse_custom_pair(params, "type_start_date", "type_end_date")
    except DateRangeError as exc:
        return _response(400, {"error": str(exc)})

    try:
        df = _get_data()
    except DataLoadError as exc:
        return _response(500, {"error": f"Failed to load analytics data: {exc}"})

    df = filter_country(df, params.get("country"))

    if rating_custom is None and type_custom is None:
        now = datetime.now(timezone.utc)
        result = {}
        for bucket, (start, end, granularity) in fixed_windows(now).items():
            result[bucket] = build_bucket(df, start, end, granularity)
        result["Custom"] = {"rating_distribution": [], "organization_mix_trend": dict(_EMPTY_MIX_TREND)}
        assert tuple(result) == ALL_BUCKETS, "unexpected bucket configuration"
        return _response(200, result)

    rating_start, rating_end = rating_custom if rating_custom else (None, None)
    type_start, type_end = type_custom if type_custom else (None, None)

    result = {
        "Custom": {
            "rating_distribution": (
                compute_rating_distribution(df, rating_start, rating_end)
                if rating_custom
                else []
            ),
            "organization_mix_trend": (
                compute_organization_mix_trend(df, type_start, type_end, "day")
                if type_custom
                else dict(_EMPTY_MIX_TREND)
            ),
        }
    }
    return _response(200, result)


def _run_local_samples():
    """Prints the handler's output for a handful of representative requests.
    Run with `MOCK_DATA_DIR=/path/to/csvs python rating_type_analytics.py`.
    """
    samples = {
        "no params": {},
        "country filter only": {"country": "USA"},
        "country ALL is a no-op": {"country": "ALL"},
        "rating Custom only": {"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"},
        "type Custom only": {"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"},
        "both Custom ranges": {
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-06-30",
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-12-31",
        },
        "lone rating_start_date (should be 400)": {"rating_start_date": "2026-01-01"},
        "malformed date (should be 400)": {"rating_start_date": "not-a-date", "rating_end_date": "2026-06-30"},
        "start after end (should be 400)": {"rating_start_date": "2026-06-30", "rating_end_date": "2026-01-01"},
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
