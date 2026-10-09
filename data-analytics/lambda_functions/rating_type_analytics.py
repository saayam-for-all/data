"""Rating & Type Analytics API for the Organization dashboard (issue #380).

Returns the data behind the "Rating & Type" tab. Two charts:

* rating_distribution    - organization counts grouped by org_rating (1-5).
                           Categorical, window-scoped, sparse (ratings with no
                           organizations are omitted, never zero-filled).
* organization_mix_trend - {"non_profit": [...], "for_profit": [...]}, a time
                           series of ABSOLUTE / CUMULATIVE counts (all-time
                           running total per type). Sparse: only periods in
                           which that type gained organizations are emitted.
                           7D/30D/Custom -> daily periods (YYYY-MM-DD),
                           1Y/All        -> monthly periods (YYYY-MM).

Response shapes
---------------
* No Custom date pair supplied -> exactly {"7D", "30D", "1Y", "All", "Custom"};
  Custom has both charts empty.
* rating_start_date/rating_end_date and/or type_start_date/type_end_date
  supplied -> exactly {"Custom": {...}}. Each chart is populated only from its
  own pair; the two pairs are independent and may be combined.

Filters (JSON body, API Gateway event, or plain dict)
-----------------------------------------------------
    {
      "country": "USA",                      # code or name, or "ALL" (default)
      "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30",
      "type_start_date":   "2025-01-01", "type_end_date":   "2025-12-31"
    }

Invalid input (half a pair, bad date format, start after end, unknown or
non-string country) returns HTTP 400 with {"error": "..."} - never a partial
result.

Data sources
------------
* USE_MOCK_DATA=true (default): pandas reads organizations.csv, state(s).csv and
  country/countries.csv from MOCK_DATA_DIR (default: data-analytics/sql).
* USE_MOCK_DATA=false: reads Postgres via psycopg2 (optional import) using
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD and DB_SCHEMA.

Local run
---------
    python data-analytics/lambda_functions/rating_type_analytics.py
"""
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

try:  # Real-DB path only. The mock path must run without psycopg2 installed.
    import psycopg2
except ImportError:  # pragma: no cover - depends on the environment
    psycopg2 = None


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
DEFAULT_MOCK_DATA_DIR = Path(__file__).resolve().parent.parent / "sql"

# The issue says states.csv/countries.csv; the repo tracks state.csv/country.csv.
ORGANIZATION_FILES = ("organizations.csv",)
STATE_FILES = ("state.csv", "states.csv")
COUNTRY_FILES = ("country.csv", "countries.csv")

DEFAULT_DB_SCHEMA = "virginia_dev_saayam_rdbms"

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
BUCKET_WINDOW_DAYS = {"7D": 7, "30D": 30, "1Y": 365}
BUCKET_FREQ = {"7D": "D", "30D": "D", "1Y": "M", "All": "M", "Custom": "D"}

ORG_TYPES = ("non_profit", "for_profit")
VALID_RATINGS = (1, 2, 3, 4, 5)
DATE_FORMAT = "%Y-%m-%d"
ALL_COUNTRIES = "ALL"

RATING_PAIR = ("rating_start_date", "rating_end_date")
TYPE_PAIR = ("type_start_date", "type_end_date")

FRAME_COLUMNS = ["org_id", "org_rating", "org_type", "created_at", "country_code", "country_name"]


class ValidationError(Exception):
    """Bad request parameter. The message is returned in the 400 body."""


def _today() -> date:
    """Today's date, wrapped so tests can freeze it."""
    return date.today()


def _use_mock_data() -> bool:
    return os.environ.get("USE_MOCK_DATA", "true").strip().lower() in {"true", "1", "yes", "y"}


# --------------------------------------------------------------------------- #
# Normalization helpers
# --------------------------------------------------------------------------- #
def normalize_org_type(value: Any) -> Optional[str]:
    """Map 'Non-Profit', 'non_profit', 'For-profit', 'for profit' ... to the API keys."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return key if key in ORG_TYPES else None


def normalize_country_token(value: Any) -> str:
    """Case/spacing-insensitive country key: 'United States' == 'UNITED_STATES'."""
    return str(value).strip().upper().replace(" ", "_").replace("-", "_")


def prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Coerce the raw org frame (from CSV or DB) into clean, typed columns."""
    frame = frame.copy()
    for column in FRAME_COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce")
    frame["org_rating"] = pd.to_numeric(frame["org_rating"], errors="coerce")
    frame["org_type"] = frame["org_type"].map(normalize_org_type)
    frame["country_code"] = frame["country_code"].map(
        lambda v: None if v is None or pd.isna(v) else normalize_country_token(v)
    )
    frame["country_name"] = frame["country_name"].map(
        lambda v: None if v is None or pd.isna(v) else normalize_country_token(v)
    )

    dropped = int(frame["created_at"].isna().sum())
    if dropped:
        print(f"WARNING: dropped {dropped} organization row(s) with an unparseable created_at.")

    return frame.dropna(subset=["created_at"]).reset_index(drop=True)[FRAME_COLUMNS]


# --------------------------------------------------------------------------- #
# Data loading - mock CSVs (pandas)
# --------------------------------------------------------------------------- #
def get_mock_data_dir() -> Path:
    return Path(os.environ.get("MOCK_DATA_DIR") or DEFAULT_MOCK_DATA_DIR)


def resolve_csv_path(data_dir: Path, candidates: Sequence[str]) -> Path:
    """First candidate that exists in data_dir (case-insensitive fallback for Linux)."""
    for name in candidates:
        path = data_dir / name
        if path.is_file():
            return path
    wanted = {name.lower() for name in candidates}
    if data_dir.is_dir():
        for path in data_dir.iterdir():
            if path.is_file() and path.name.lower() in wanted:
                return path
    raise FileNotFoundError(f"None of {list(candidates)} found in {data_dir}")


def load_mock_data(data_dir: Optional[Path] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return (organizations frame, countries lookup frame) from the CSVs."""
    data_dir = data_dir or get_mock_data_dir()

    orgs = pd.read_csv(resolve_csv_path(data_dir, ORGANIZATION_FILES))
    states = pd.read_csv(resolve_csv_path(data_dir, STATE_FILES))
    countries = pd.read_csv(resolve_csv_path(data_dir, COUNTRY_FILES))

    for required in ("created_at", "org_rating", "org_type", "state_id"):
        if required not in orgs.columns:
            raise KeyError(f"organizations.csv is missing the required '{required}' column.")

    states["country_id"] = pd.to_numeric(states["country_id"], errors="coerce")
    countries["country_id"] = pd.to_numeric(countries["country_id"], errors="coerce")
    if "country_name" not in countries.columns:
        countries["country_name"] = None

    orgs["state_id"] = orgs["state_id"].astype(str).str.strip().str.upper()
    states["state_id"] = states["state_id"].astype(str).str.strip().str.upper()

    # organizations.state_id -> state.country_id -> country.country_code
    # Left joins so an org with an unknown state is kept (it still counts under ALL).
    merged = orgs.merge(states[["state_id", "country_id"]].drop_duplicates("state_id"),
                        on="state_id", how="left")
    merged = merged.merge(countries[["country_id", "country_code", "country_name"]],
                          on="country_id", how="left")

    return prepare_frame(merged), countries[["country_code", "country_name"]]


# --------------------------------------------------------------------------- #
# Data loading - real Postgres (psycopg2)
# --------------------------------------------------------------------------- #
def get_db_connection():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed; set USE_MOCK_DATA=true to use CSVs.")
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        sslmode=os.environ.get("DB_SSLMODE", "require"),
    )


def load_db_data() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Same two frames as load_mock_data, read from Postgres."""
    schema = os.environ.get("DB_SCHEMA", DEFAULT_DB_SCHEMA)
    org_query = f"""
        SELECT o.org_id, o.org_rating, o.org_type::text AS org_type, o.created_at,
               c.country_code, c.country_name
        FROM {schema}.organizations o
        LEFT JOIN {schema}.state s   ON s.state_id = o.state_id
        LEFT JOIN {schema}.country c ON c.country_id = s.country_id
    """
    country_query = f"SELECT country_code, country_name FROM {schema}.country"

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(org_query)
            orgs = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
            cur.execute(country_query)
            countries = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
    finally:
        conn.close()

    if orgs.empty:
        orgs = pd.DataFrame(columns=FRAME_COLUMNS)
    return prepare_frame(orgs), countries


def load_data() -> Tuple[pd.DataFrame, pd.DataFrame]:
    return load_mock_data() if _use_mock_data() else load_db_data()


# --------------------------------------------------------------------------- #
# Request parsing / validation
# --------------------------------------------------------------------------- #
def parse_event_body(event: Any) -> Dict[str, Any]:
    """Params from an API Gateway event (JSON body or query string) or a plain dict."""
    if not event or not isinstance(event, dict):
        return {}

    if "body" in event or "queryStringParameters" in event:
        params: Dict[str, Any] = dict(event.get("queryStringParameters") or {})
        body = event.get("body")
        if isinstance(body, dict):
            params.update(body)
        elif isinstance(body, str) and body.strip():
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                raise ValidationError("Request body is not valid JSON.")
            if not isinstance(parsed, dict):
                raise ValidationError("Request body must be a JSON object.")
            params.update(parsed)
        return params

    return event


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def parse_date_param(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise ValidationError(f"Invalid {field_name}: expected a YYYY-MM-DD string.")
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT).date()
    except ValueError:
        raise ValidationError(f"Invalid {field_name} '{value}'. Expected format YYYY-MM-DD.")


def parse_date_pair(params: Dict[str, Any], pair: Tuple[str, str]) -> Optional[Tuple[date, date]]:
    """None if the pair is absent. Both halves are required once either is given."""
    start_key, end_key = pair
    start_raw, end_raw = params.get(start_key), params.get(end_key)

    if _is_blank(start_raw) and _is_blank(end_raw):
        return None
    if _is_blank(start_raw) or _is_blank(end_raw):
        missing = start_key if _is_blank(start_raw) else end_key
        raise ValidationError(f"Incomplete date range: '{missing}' is required "
                              f"when '{start_key}'/'{end_key}' is used.")

    start = parse_date_param(start_raw, start_key)
    end = parse_date_param(end_raw, end_key)
    if start > end:
        raise ValidationError(f"{start_key} ({start}) must be on or before {end_key} ({end}).")
    return start, end


def parse_country(params: Dict[str, Any]) -> Optional[str]:
    """None means ALL. Otherwise a normalized country token."""
    value = params.get("country")
    if _is_blank(value):
        return None
    if not isinstance(value, str):
        raise ValidationError("Invalid country: expected a country name, country code, or 'ALL'.")
    token = normalize_country_token(value)
    return None if token == ALL_COUNTRIES else token


def filter_by_country(orgs: pd.DataFrame, countries: pd.DataFrame,
                      country: Optional[str]) -> pd.DataFrame:
    """Keep only orgs whose country code OR name matches. Unknown country -> 400."""
    if country is None:
        return orgs

    known = {normalize_country_token(v) for col in ("country_code", "country_name")
             if col in countries.columns for v in countries[col].dropna()}
    if country not in known:
        raise ValidationError(f"Unknown country '{country}'. Use a country name, code, or 'ALL'.")

    mask = (orgs["country_code"] == country) | (orgs["country_name"] == country)
    return orgs.loc[mask].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Chart builders
# --------------------------------------------------------------------------- #
def window_mask(created_at: pd.Series, start: Optional[date], end: Optional[date]) -> pd.Series:
    """Inclusive day-granular window; either bound may be None (unbounded)."""
    day = created_at.dt.normalize()
    mask = pd.Series(True, index=created_at.index, dtype=bool)
    if start is not None:
        mask &= day >= pd.Timestamp(start)
    if end is not None:
        mask &= day <= pd.Timestamp(end)
    return mask


def resolve_bucket_window(bucket: str, today: date) -> Tuple[Optional[date], Optional[date]]:
    if bucket in BUCKET_WINDOW_DAYS:
        return today - timedelta(days=BUCKET_WINDOW_DAYS[bucket]), today
    if bucket == "All":
        return None, None
    raise ValueError(f"Unknown bucket {bucket!r}")


def empty_mix_trend() -> Dict[str, List[Dict[str, Any]]]:
    return {org_type: [] for org_type in ORG_TYPES}


def empty_bucket() -> Dict[str, Any]:
    return {"rating_distribution": [], "organization_mix_trend": empty_mix_trend()}


def build_rating_distribution(orgs: pd.DataFrame, start: Optional[date],
                              end: Optional[date]) -> List[Dict[str, int]]:
    """Window-scoped count per literal org_rating (1-5). Sparse, ascending by rating."""
    if orgs.empty:
        return []
    window = orgs.loc[window_mask(orgs["created_at"], start, end)]
    ratings = window["org_rating"].dropna()
    ratings = ratings[ratings.isin(VALID_RATINGS)].astype(int)
    counts = ratings.value_counts().sort_index()
    return [{"rating": int(r), "count": int(c)} for r, c in counts.items()]


def build_mix_trend(orgs: pd.DataFrame, freq: str, start: Optional[date],
                    end: Optional[date]) -> Dict[str, List[Dict[str, Any]]]:
    """Cumulative per-type counts, emitted only for in-window periods with new orgs.

    `orgs` must be the full (country-filtered) dataset, NOT pre-filtered to the
    window - otherwise the running total would restart at zero at the window start.
    """
    trend = empty_mix_trend()
    if orgs.empty:
        return trend

    in_window = window_mask(orgs["created_at"], start, end)
    for org_type in ORG_TYPES:
        is_type = orgs["org_type"] == org_type
        if not is_type.any():
            continue
        periods = orgs.loc[is_type, "created_at"].dt.to_period(freq)
        cumulative = periods.value_counts().sort_index().cumsum()  # all-time running total
        window_periods = sorted(periods[in_window[is_type]].unique())
        trend[org_type] = [{"period": str(p), "count": int(cumulative[p])} for p in window_periods]
    return trend


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #
def build_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    """Rating & Type tab data. See module docstring for the contract."""
    # 1. Validate everything that doesn't need data, before touching it.
    try:
        params = parse_event_body(event)
        rating_range = parse_date_pair(params, RATING_PAIR)
        type_range = parse_date_pair(params, TYPE_PAIR)
        country = parse_country(params)
    except ValidationError as exc:
        return build_response(400, {"error": str(exc)})

    # 2. Load data.
    try:
        orgs, countries = load_data()
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to the client
        print(f"ERROR: could not load organization data: {exc}")
        return build_response(500, {"error": "Could not load organization data."})

    # 3. Country filter (applies to both charts, every response shape).
    try:
        orgs = filter_by_country(orgs, countries, country)
    except ValidationError as exc:
        return build_response(400, {"error": str(exc)})

    # 4a. Any Custom pair supplied -> Custom-only response, each chart independent.
    if rating_range is not None or type_range is not None:
        custom = empty_bucket()
        if rating_range is not None:
            custom["rating_distribution"] = build_rating_distribution(orgs, *rating_range)
        if type_range is not None:
            custom["organization_mix_trend"] = build_mix_trend(orgs, BUCKET_FREQ["Custom"],
                                                               *type_range)
        return build_response(200, {"Custom": custom})

    # 4b. No Custom pair -> all fixed buckets + empty Custom.
    today = _today()
    response: Dict[str, Any] = {}
    for bucket in FIXED_BUCKETS:
        start, end = resolve_bucket_window(bucket, today)
        response[bucket] = {
            "rating_distribution": build_rating_distribution(orgs, start, end),
            "organization_mix_trend": build_mix_trend(orgs, BUCKET_FREQ[bucket], start, end),
        }
    response["Custom"] = empty_bucket()
    return build_response(200, response)


# --------------------------------------------------------------------------- #
# Local run
# --------------------------------------------------------------------------- #
SAMPLE_EVENTS = (
    ("1. no body (all fixed buckets)", {}),
    ("2. country filter (code)", {"country": "AFG"}),
    ("3. rating Custom range only", {"rating_start_date": "2025-01-01",
                                     "rating_end_date": "2025-12-31"}),
    ("4. type Custom range only", {"type_start_date": "2024-01-01",
                                   "type_end_date": "2024-12-31"}),
    ("5. both Custom ranges", {"rating_start_date": "2025-01-01", "rating_end_date": "2025-12-31",
                               "type_start_date": "2024-01-01", "type_end_date": "2024-12-31"}),
    ("6. API Gateway event with JSON string body",
     {"body": json.dumps({"country": "Afghanistan", "type_start_date": "2025-01-01",
                          "type_end_date": "2025-06-30"})}),
    ("7. ERROR: missing half of a pair", {"rating_start_date": "2025-01-01"}),
    ("8. ERROR: bad date format", {"type_start_date": "2025/01/01", "type_end_date": "2025-02-01"}),
    ("9. ERROR: start after end", {"rating_start_date": "2025-12-31",
                                   "rating_end_date": "2025-01-01"}),
    ("10. ERROR: unknown country", {"country": "Atlantis"}),
)


if __name__ == "__main__":
    for label, sample_event in SAMPLE_EVENTS:
        print(f"\n=== {label} ===")
        result = lambda_handler(sample_event, None)
        print(json.dumps({"statusCode": result["statusCode"],
                          "body": json.loads(result["body"])}, indent=2))
