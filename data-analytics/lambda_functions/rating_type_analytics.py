"""Rating & Type Analytics API for the Organization dashboard (issue #380).

Returns the data behind the "Rating & Type" tab: a Rating Distribution chart
(organization counts by star rating) and a Profit vs Non-Profit chart (a
cumulative time series split by organization type).

Response shape is conditional on whether a Custom date range was requested:

    no Custom date params  -> {"7D": ..., "30D": ..., "1Y": ..., "All": ...,
                               "Custom": <empty>}      exactly 5 top-level keys
    either/both pairs sent -> {"Custom": {...}}         exactly 1 top-level key

`rating_distribution` is a window-scoped categorical breakdown. Its counts come
from the rows inside the window only.

`organization_mix_trend` is the opposite: its counts are absolute, all-time
running totals per type, computed over the entire dataset. The window decides
only which of those points are visible. Each series keeps its own sparse period
list - a period appears in `non_profit` only if a non-profit was created in it,
and likewise for `for_profit`, so the two series routinely differ.

Data source
-----------
`USE_MOCK_DATA` selects the loader and **defaults to "true"**, so this module
runs standalone and the test suite needs no setup.

    WARNING: because the default is "true", a deployed Lambda that forgets to
    set USE_MOCK_DATA=false will silently serve mock CSV data from its own
    deployment package instead of querying Postgres. Set it explicitly in any
    real environment.

The mock path reads CSVs from `MOCK_DATA_DIR`, defaulting to the tracked
`data-analytics/sql` folder. No mock CSVs are added by this module.

The Postgres path is **UNVERIFIED** - it has never been executed against a live
database. Its column names come from `database/mock-data-generation/db_info.json`,
which is mock-generation metadata rather than an information_schema dump, so the
column names are as unverified as the connection itself.

Known data caveat
-----------------
Every organization resolves to country `AFG` / `AFGHANISTAN`. That is faithful to
the data, not a bug here: all 51 rows of `state.csv` carry `country_id = 1`, and
`country.csv` defines `country_id = 1` as AFGHANISTAN. USA is `country_id = 233`.
A consequence worth knowing before reading any output: `country="USA"` correctly
returns nothing, and `country="AFG"` is the only real-data happy path. The join
is implemented as specified; the seed data is what points US states at Afghanistan.
"""
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    PSYCOPG2_AVAILABLE = True
except ImportError:  # keeps the module importable with USE_MOCK_DATA=true
    psycopg2 = None
    RealDictCursor = None
    PSYCOPG2_AVAILABLE = False


SCHEMA_NAME = "virginia_dev_saayam_rdbms"

# The tracked CSVs live one level up from this file, in data-analytics/sql.
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "sql"

# The issue refers to states.csv/countries.csv; the repo has state.csv/country.csv.
ORGANIZATION_FILE = "organizations.csv"
STATE_FILES = ("state.csv", "states.csv")
COUNTRY_FILES = ("country.csv", "countries.csv")

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
BUCKET_WINDOW_DAYS = {"7D": 7, "30D": 30, "1Y": 365}
GRANULARITY = {"7D": "day", "30D": "day", "1Y": "month", "All": "month", "Custom": "day"}
PERIOD_FORMAT = {"day": "%Y-%m-%d", "month": "%Y-%m"}

SERIES_KEYS = ("non_profit", "for_profit")
OTHER_ORG_TYPE = "other"
ORG_TYPE_ALIASES = {
    "non_profit": "non_profit",
    "nonprofit": "non_profit",
    "for_profit": "for_profit",
    "forprofit": "for_profit",
}

CANONICAL_COLUMNS = ["org_id", "org_type", "org_rating", "created_at", "country_name", "country_code"]

UNKNOWN_COUNTRY = "UNKNOWN"
ALL_COUNTRIES = "ALL"

# strptime alone accepts "2026-1-5", so the format is pinned with a regex first.
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE_FORMAT = "%Y-%m-%d"

TRUTHY = frozenset({"1", "true", "yes", "y", "on"})


class ValidationError(Exception):
    """A bad request parameter. Carries the message returned in the 400 body."""


def current_time() -> datetime:
    """Now, wrapped so tests can freeze the clock by patching one symbol."""
    return datetime.now()


# ---------------------------------------------------------------------------
# Request parsing and responses
# ---------------------------------------------------------------------------


def parse_event_body(event):
    """Pull request params out of an API Gateway event, a plain dict, or nothing."""
    if not event or not isinstance(event, dict):
        return {}

    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def build_response(status_code, payload):
    """API Gateway proxy response with a JSON-serialized body."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(payload),
    }


def _blank_to_none(value):
    """Treat non-strings and whitespace-only strings as 'not supplied'."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def parse_date(value, field_name):
    """Parse one strict YYYY-MM-DD value."""
    if not DATE_RE.match(value):
        raise ValidationError(f"Invalid {field_name} '{value}'. Expected format YYYY-MM-DD.")
    try:
        return datetime.strptime(value, DATE_FORMAT)
    except ValueError:
        raise ValidationError(f"Invalid {field_name} '{value}'. Not a real calendar date.")


def validate_date_pair(params, start_field, end_field):
    """Validate one date pair. Returns (start, end) or None when absent.

    Unlike the Growth & Location API, a half-supplied pair is an error here:
    issue #380 lists "missing half of a pair" as a case that must fail.
    """
    start_raw = _blank_to_none(params.get(start_field))
    end_raw = _blank_to_none(params.get(end_field))

    if start_raw is None and end_raw is None:
        return None
    if start_raw is None:
        raise ValidationError(f"{start_field} is required when {end_field} is supplied.")
    if end_raw is None:
        raise ValidationError(f"{end_field} is required when {start_field} is supplied.")

    start = parse_date(start_raw, start_field)
    end = parse_date(end_raw, end_field)
    if start > end:
        raise ValidationError(f"{start_field} must be on or before {end_field}.")

    # Cover the whole end day - created_at carries a time component, so a range
    # ending 2026-01-10 would otherwise drop an organization created at 23:29.
    return start, end.replace(hour=23, minute=59, second=59, microsecond=999999)


def validate_country(value):
    """Normalize the country filter. Never raises; anything unusable means ALL."""
    country = _blank_to_none(value)
    return country.upper() if country else ALL_COUNTRIES


# ---------------------------------------------------------------------------
# Data loading - the two paths converge on one normalized frame
# ---------------------------------------------------------------------------


def use_mock_data():
    """Whether to read CSVs instead of Postgres. Defaults to true; see module docstring."""
    return os.environ.get("USE_MOCK_DATA", "true").strip().lower() in TRUTHY


def resolve_data_dir():
    """Directory holding the mock CSVs. Read at call time so tests can set the env var."""
    return Path(os.environ.get("MOCK_DATA_DIR") or DEFAULT_DATA_DIR)


def _first_existing(data_dir, candidates):
    """First candidate filename that exists in data_dir, or None."""
    for name in candidates:
        path = data_dir / name
        if path.is_file():
            return path
    return None


def load_organizations_from_csv(data_dir=None):
    """Read the mock CSVs into a raw frame of CANONICAL_COLUMNS.

    Values are left untouched here - all cleaning happens in normalize_frame,
    so both data paths get identical treatment.
    """
    data_dir = Path(data_dir) if data_dir else resolve_data_dir()

    orgs_path = data_dir / ORGANIZATION_FILE
    if not orgs_path.is_file():
        raise FileNotFoundError(f"{ORGANIZATION_FILE} not found in {data_dir}")

    try:
        orgs = pd.read_csv(orgs_path, dtype=str)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    frame = pd.DataFrame(index=orgs.index)
    frame["org_id"] = orgs["org_id"] if "org_id" in orgs.columns else orgs.index
    frame["org_type"] = orgs.get("org_type")
    frame["org_rating"] = orgs.get("org_rating")
    frame["created_at"] = orgs.get("created_at")

    country_name, country_code = _csv_country_columns(data_dir, orgs)
    frame["country_name"] = country_name
    frame["country_code"] = country_code

    return frame


def _csv_country_columns(data_dir, orgs):
    """Resolve each organization's country via state_id -> country_id -> country.

    Returns (country_name, country_code) series aligned to orgs. A missing
    lookup CSV degrades every row to UNKNOWN rather than failing the request.
    """
    missing = pd.Series(None, index=orgs.index, dtype=object)
    if "state_id" not in orgs.columns:
        return missing, missing

    state_path = _first_existing(data_dir, STATE_FILES)
    country_path = _first_existing(data_dir, COUNTRY_FILES)
    if state_path is None or country_path is None:
        print("WARNING: state/country lookup CSV missing; countries will be UNKNOWN.")
        return missing, missing

    states = pd.read_csv(state_path)
    countries = pd.read_csv(country_path)

    # country.csv is fully quoted, so don't rely on pandas inferring ints.
    states["country_id"] = pd.to_numeric(states["country_id"], errors="coerce")
    countries["country_id"] = pd.to_numeric(countries["country_id"], errors="coerce")

    lookup = states.merge(countries[["country_id", "country_name", "country_code"]],
                          on="country_id", how="left")
    lookup = lookup.dropna(subset=["state_id"])
    lookup["state_id"] = lookup["state_id"].astype(str).str.strip().str.upper()

    state_ids = orgs["state_id"].astype(str).str.strip().str.upper()
    # map rather than merge: an unmatched state must become UNKNOWN without
    # dropping the row, which still counts toward the mix trend.
    by_name = dict(zip(lookup["state_id"], lookup["country_name"]))
    by_code = dict(zip(lookup["state_id"], lookup["country_code"]))
    return state_ids.map(by_name), state_ids.map(by_code)


# UNVERIFIED: never executed against a live database. Column names come from
# database/mock-data-generation/db_info.json and differ from the mock CSVs -
# the DB calls the rating column `rating` (CSV: org_rating) and keys states off
# `state_code` ("US-AK") rather than `state_id` ("AK"). Deliberately a plain
# SELECT: no WHERE, GROUP BY, DATE_TRUNC or window function, so every bucket
# boundary, period label and cumulative total stays in the shared pandas code
# below and is covered by the CSV-backed tests.
ORGANIZATIONS_SQL = f"""
SELECT
    o.org_id                            AS org_id,
    o.org_type                          AS org_type,
    o.rating                            AS org_rating,
    o.created_at                        AS created_at,
    COALESCE(c.country_name, 'UNKNOWN') AS country_name,
    COALESCE(c.country_code, 'UNKNOWN') AS country_code
FROM {SCHEMA_NAME}.organizations o
LEFT JOIN {SCHEMA_NAME}.state   s ON o.state_code = s.state_code
LEFT JOIN {SCHEMA_NAME}.country c ON s.country_id = c.country_id
"""


def get_db_connection():
    """Open a Postgres connection from environment variables.

    UNVERIFIED. Note this diverges from the other analytics Lambdas, which pull
    credentials from SSM via boto3 - issue #380 forbids new third-party
    dependencies, so credentials come from the environment instead. Whoever
    wires up the real database should swap in the SSM helper from
    kpi_api_analytics.py.
    """
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        port=int(os.environ.get("DB_PORT", 5432)),
    )


def load_organizations_from_db(conn):
    """Run the thin SELECT and return a raw frame of CANONICAL_COLUMNS. UNVERIFIED."""
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(ORGANIZATIONS_SQL)
        rows = cursor.fetchall()
    return pd.DataFrame([dict(row) for row in rows], columns=CANONICAL_COLUMNS)


def normalize_org_type(value):
    """Map a raw org_type onto non_profit / for_profit / other.

    The mock CSV holds "Non-Profit" and "For-profit" - note the inconsistent
    capitalization - so match on a stripped, lowercased, separator-folded form.
    """
    if not isinstance(value, str):
        return OTHER_ORG_TYPE
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    return ORG_TYPE_ALIASES.get(key, OTHER_ORG_TYPE)


def normalize_frame(df):
    """Clean a raw frame from either loader. The single convergence point."""
    df = df.reindex(columns=CANONICAL_COLUMNS).copy()

    if df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
        df["org_type_norm"] = pd.Series(dtype=object)
        df["rating_int"] = pd.Series(dtype="float64")
        return df

    # utc=True then drop the offset: the DB column is timestamptz while the CSV
    # is naive, and comparing aware against naive timestamps raises.
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True).dt.tz_localize(None)

    dropped = int(df["created_at"].isna().sum())
    if dropped:
        print(f"WARNING: dropped {dropped} organization row(s) with an unparseable created_at.")
    # A row with no date cannot be placed in any window or period.
    df = df[df["created_at"].notna()].copy()

    # An unrecognized type is kept as "other": it stays out of the two mix-trend
    # series but still counts toward the rating distribution.
    df["org_type_norm"] = df["org_type"].map(normalize_org_type)

    # A bad rating is kept as NaN rather than dropping the row, which would
    # silently remove a perfectly valid organization from the mix trend.
    rating = pd.to_numeric(df["org_rating"], errors="coerce")
    df["rating_int"] = rating.where(rating == rating.round())

    for column in ("country_name", "country_code"):
        df[column] = df[column].fillna(UNKNOWN_COUNTRY).astype(str).str.strip()

    return df


def load_organizations():
    """Load organizations from CSVs or Postgres, normalized either way."""
    if use_mock_data():
        return normalize_frame(load_organizations_from_csv())

    if not PSYCOPG2_AVAILABLE:
        raise RuntimeError("USE_MOCK_DATA is false but psycopg2 is not installed.")

    conn = None
    try:
        conn = get_db_connection()
        return normalize_frame(load_organizations_from_db(conn))
    finally:
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def filter_by_country(df, country):
    """Keep only rows in the given country, matching code or name case-insensitively."""
    if country == ALL_COUNTRIES or df.empty:
        return df
    code = df["country_code"].str.upper()
    name = df["country_name"].str.upper()
    return df[(code == country) | (name == country)]


def window_bounds(bucket, now):
    """Resolve a fixed bucket into (start, end). A None start means unbounded."""
    if bucket in BUCKET_WINDOW_DAYS:
        return now - timedelta(days=BUCKET_WINDOW_DAYS[bucket]), now
    if bucket == "All":
        return None, now
    raise ValueError(f"Unknown bucket {bucket!r}")


def slice_window(df, start, end):
    """Rows created within [start, end], inclusive. Either bound may be None."""
    if df.empty:
        return df
    mask = pd.Series(True, index=df.index, dtype=bool)
    if start is not None:
        mask &= df["created_at"] >= start
    if end is not None:
        mask &= df["created_at"] <= end
    return df[mask]


def period_labels(created_at, granularity):
    """Format timestamps as YYYY-MM-DD or YYYY-MM period labels."""
    return created_at.dt.strftime(PERIOD_FORMAT[granularity])


def build_rating_distribution(window_df):
    """Counts per rating for one window.

    Takes the WINDOW-SLICED frame - deliberately unlike build_mix_trend, which
    takes the full frame. Getting these two backwards is the easiest bug to
    introduce here.
    """
    if window_df.empty:
        return []

    ratings = window_df["rating_int"].dropna()
    if ratings.empty:
        return []

    counts = ratings.astype(int).value_counts().sort_index()
    # int() is mandatory: numpy.int64 is not JSON-serializable.
    return [{"rating": int(rating), "count": int(count)} for rating, count in counts.items()]


def build_mix_trend(full_df, start, end, granularity):
    """Cumulative organization counts per type.

    Takes the FULL country-filtered frame, never a window-sliced one: the counts
    are all-time running totals, and slicing before the cumulative sum is what
    would reset them to zero at the window start. The window decides only which
    already-computed points are visible.

    Each series is summed over its OWN period index, which is what lets
    non_profit and for_profit end up with genuinely different period lists. A
    shared union index would force both series to the same periods and break the
    spec's "omit periods with no new organizations of that type".
    """
    result = {key: [] for key in SERIES_KEYS}
    if full_df.empty:
        return result

    for key in SERIES_KEYS:
        sub = full_df[full_df["org_type_norm"] == key]
        if sub.empty:
            continue

        labels = period_labels(sub["created_at"], granularity)
        cumulative = labels.value_counts().sort_index().cumsum()

        mask = pd.Series(True, index=sub.index, dtype=bool)
        if start is not None:
            mask &= sub["created_at"] >= start
        if end is not None:
            mask &= sub["created_at"] <= end

        # Zero-padded fixed-width labels sort lexicographically == chronologically.
        visible = sorted(set(labels[mask]))
        result[key] = [{"period": period, "count": int(cumulative[period])} for period in visible]

    return result


def empty_chart_pair():
    """A fresh, fully empty bucket payload."""
    return {
        "rating_distribution": [],
        "organization_mix_trend": {key: [] for key in SERIES_KEYS},
    }


def build_bucket(full_df, start, end, granularity):
    """Both charts for one shared window."""
    return {
        "rating_distribution": build_rating_distribution(slice_window(full_df, start, end)),
        "organization_mix_trend": build_mix_trend(full_df, start, end, granularity),
    }


def build_fixed_buckets(full_df, now):
    """The five-key payload: every fixed bucket plus an empty Custom."""
    buckets = {}
    for bucket in FIXED_BUCKETS:
        start, end = window_bounds(bucket, now)
        buckets[bucket] = build_bucket(full_df, start, end, GRANULARITY[bucket])
    buckets["Custom"] = empty_chart_pair()
    return buckets


def build_custom_bucket(full_df, rating_pair, type_pair):
    """The Custom payload. Each sub-chart is driven by its own range, independently."""
    payload = empty_chart_pair()

    if rating_pair is not None:
        payload["rating_distribution"] = build_rating_distribution(
            slice_window(full_df, rating_pair[0], rating_pair[1])
        )

    if type_pair is not None:
        payload["organization_mix_trend"] = build_mix_trend(
            full_df, type_pair[0], type_pair[1], GRANULARITY["Custom"]
        )

    return payload


def lambda_handler(event, context):
    """Return the Rating & Type tab data for the Organization dashboard."""
    params = parse_event_body(event)
    country = validate_country(params.get("country"))

    # Validate both pairs before choosing a response shape, so a broken pair
    # always 400s rather than silently selecting the Custom-only shape.
    try:
        rating_pair = validate_date_pair(params, "rating_start_date", "rating_end_date")
        type_pair = validate_date_pair(params, "type_start_date", "type_end_date")
    except ValidationError as exc:
        return build_response(400, {"error": str(exc)})

    try:
        organizations = load_organizations()
    except FileNotFoundError as exc:
        return build_response(500, {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001 - the handler must not leak a stack trace
        print(f"ERROR: could not load organization data: {exc}")
        return build_response(500, {"error": "Could not load organization data."})

    # Filter once, before any aggregation: the mix trend's all-time baseline must
    # count only the selected country, so filtering afterwards would leak rows.
    organizations = filter_by_country(organizations, country)

    if rating_pair is not None or type_pair is not None:
        return build_response(200, {"Custom": build_custom_bucket(organizations, rating_pair, type_pair)})

    return build_response(200, build_fixed_buckets(organizations, current_time()))


SAMPLE_EVENTS = (
    ("no body - all fixed buckets", {}),
    ("country filter by code", {"country": "AFG"}),
    ("country filter by name (lowercase)", {"country": "afghanistan"}),
    ("unmatched country - empty but 200", {"country": "USA"}),
    ("rating range alone", {"rating_start_date": "2025-10-01", "rating_end_date": "2026-01-31"}),
    ("type range alone", {"type_start_date": "2025-10-01", "type_end_date": "2026-01-31"}),
    (
        "both ranges, different windows",
        {
            "rating_start_date": "2025-10-01",
            "rating_end_date": "2025-12-31",
            "type_start_date": "2025-11-01",
            "type_end_date": "2026-01-31",
        },
    ),
    ("half pair -> 400", {"rating_start_date": "2025-10-01"}),
    ("start after end -> 400", {"type_start_date": "2026-01-31", "type_end_date": "2025-10-01"}),
    ("bad format -> 400", {"rating_start_date": "01/10/2025", "rating_end_date": "2026-01-31"}),
)


if __name__ == "__main__":
    for label, sample_event in SAMPLE_EVENTS:
        print(f"\n=== {label} ===")
        print(f"event: {json.dumps(sample_event)}")
        result = lambda_handler(sample_event, None)
        # Re-parse the body so the output is readable instead of one escaped blob.
        print(
            json.dumps(
                {"statusCode": result["statusCode"], "body": json.loads(result["body"])},
                indent=2,
            )
        )
