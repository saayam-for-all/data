"""Growth & Location Analytics API for the Organization dashboard (issue #336).

Returns the data behind the "Growth & Location" tab in a single response so the
frontend can switch either chart's time range without another API call:

    {
      "7D" | "30D" | "1Y" | "All" | "Custom": {
        "growth_trend": {"total_organizations": [...], "collaborators": [...]},
        "organizations_by_location": [...]
      }
    }

`total_organizations` is an absolute, all-time running total as of each period -
it is never reset to zero at the start of a bucket's window. `collaborators` is a
per-period count scoped to the bucket's own window. Both series share the same
period list, and periods with no organization activity are omitted entirely
(sparse arrays, not zero-filled).

Local run
---------
    python data-analytics/lambda_functions/growth_location_analytics.py

Reads CSVs from MOCK_DATA_DIR, defaulting to the tracked `data-analytics/sql`
folder so a fresh clone runs with no setup. No mock CSVs are added by this
module - it only reads files that already live in the repo.

Known data caveat
-----------------
`organizations_by_location` currently reports a single row, `AFG`, for the whole
dataset. That is faithful to the data, not a bug in this function: every one of
the 51 rows in `state.csv` carries `country_id = 1`, and `country.csv` defines
`country_id = 1` as AFGHANISTAN (`country_code = "AFG"`). USA is `country_id =
233`. The join is implemented exactly as specified; the seed data is what points
US state codes at Afghanistan.
"""
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

# The tracked CSVs live one level up from this file, in data-analytics/sql.
DEFAULT_MOCK_DATA_DIR = Path(__file__).resolve().parent.parent / "sql"

# The issue refers to states.csv/countries.csv; the repo has state.csv/country.csv.
# Accept either spelling so the function works against both.
ORGANIZATION_FILES = ("organizations.csv",)
STATE_FILES = ("state.csv", "states.csv")
COUNTRY_FILES = ("country.csv", "countries.csv")

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")

# pandas period freqs. str(pd.Period(x, "D")) renders "2025-01-05" and
# str(pd.Period(x, "M")) renders "2025-01", which are exactly the period labels
# the spec asks for - so one code path produces both formats.
BUCKET_FREQ = {"7D": "D", "30D": "D", "1Y": "M", "All": "M", "Custom": "D"}

BUCKET_WINDOW_DAYS = {"7D": 7, "30D": 30, "1Y": 365}

TOP_LOCATION_LIMIT = 4
UNKNOWN_COUNTRY = "Unknown"
DATE_FORMAT = "%Y-%m-%d"
TRUE_TOKENS = frozenset({"TRUE", "T", "YES", "Y", "1", "1.0"})


class ValidationError(Exception):
    """A bad request parameter. Carries the message returned in the 400 body."""


def _today() -> date:
    """Today's date, wrapped so tests can freeze it by patching one symbol."""
    return date.today()


def get_mock_data_dir() -> Path:
    """Directory holding the CSVs. Read at call time so tests can set the env var."""
    return Path(os.environ.get("MOCK_DATA_DIR") or DEFAULT_MOCK_DATA_DIR)


def resolve_csv_path(data_dir: Path, candidates: Sequence[str]) -> Path:
    """First existing candidate in data_dir, matched case-insensitively as a fallback."""
    for name in candidates:
        path = data_dir / name
        if path.is_file():
            return path

    # Windows resolves paths case-insensitively but Linux does not, so a
    # States.csv would only break after deployment without this fallback.
    wanted = {name.lower() for name in candidates}
    if data_dir.is_dir():
        for path in data_dir.iterdir():
            if path.is_file() and path.name.lower() in wanted:
                return path

    raise FileNotFoundError(f"None of {list(candidates)} found in {data_dir}")


def normalize_bool_series(series: pd.Series) -> pd.Series:
    """Coerce a truthiness column to real bools, whatever pandas inferred.

    organizations.csv holds the literal text TRUE/FALSE, which pandas reads as
    bool dtype - so comparing against the string "TRUE" silently yields all
    False and zeroes out every collaborator count. Handle bool, numeric and
    string forms so the column's inferred dtype cannot change the answer.
    """
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0) != 0
    return series.astype(str).str.strip().str.upper().isin(TRUE_TOKENS)


def load_country_lookup(data_dir: Path) -> Dict[str, str]:
    """Build {state_id: country_code} by joining state.csv to country.csv.

    Organizations only carry a state_id, so the country has to come from
    organizations.state_id -> states.country_id -> countries.country_code.
    Returns {} if either file is missing - a missing location lookup should
    degrade the location chart, not take down the growth chart with it.
    """
    try:
        states = pd.read_csv(resolve_csv_path(data_dir, STATE_FILES))
        countries = pd.read_csv(resolve_csv_path(data_dir, COUNTRY_FILES))
    except FileNotFoundError as exc:
        print(f"WARNING: location lookup unavailable ({exc}).")
        return {}

    # country.csv is fully quoted, so don't rely on pandas inferring ints here.
    states["country_id"] = pd.to_numeric(states["country_id"], errors="coerce")
    countries["country_id"] = pd.to_numeric(countries["country_id"], errors="coerce")

    joined = states.merge(countries[["country_id", "country_code"]], on="country_id", how="left")
    joined = joined.dropna(subset=["state_id", "country_code"])

    return {
        str(state_id).strip().upper(): str(country_code).strip()
        for state_id, country_code in zip(joined["state_id"], joined["country_code"])
    }


def load_organizations(data_dir: Optional[Path] = None) -> pd.DataFrame:
    """Load organizations.csv into ['org_id', 'created_at', 'is_collaborator', 'country']."""
    data_dir = data_dir or get_mock_data_dir()
    organizations = pd.read_csv(resolve_csv_path(data_dir, ORGANIZATION_FILES))

    if "created_at" not in organizations.columns:
        raise KeyError("organizations.csv is missing the required 'created_at' column.")

    frame = pd.DataFrame(index=organizations.index)
    frame["org_id"] = (
        organizations["org_id"] if "org_id" in organizations.columns else organizations.index
    )
    frame["created_at"] = pd.to_datetime(organizations["created_at"], errors="coerce")

    if "is_collaborator" in organizations.columns:
        frame["is_collaborator"] = normalize_bool_series(organizations["is_collaborator"])
    else:
        frame["is_collaborator"] = False

    if "state_id" in organizations.columns:
        lookup = load_country_lookup(data_dir)
        state_ids = organizations["state_id"].astype(str).str.strip().str.upper()
        # map + fillna rather than merge: an unmatched state must become Unknown
        # without dropping the row, since it still counts toward growth_trend.
        frame["country"] = state_ids.map(lookup).fillna(UNKNOWN_COUNTRY)
    else:
        frame["country"] = UNKNOWN_COUNTRY

    dropped = int(frame["created_at"].isna().sum())
    if dropped:
        print(f"WARNING: dropped {dropped} organization row(s) with an unparseable created_at.")

    return frame.dropna(subset=["created_at"]).reset_index(drop=True)


def window_mask(created_at: pd.Series, start: Optional[date], end: Optional[date]) -> pd.Series:
    """Inclusive, day-granular mask. Either bound may be None, meaning unbounded."""
    mask = pd.Series(True, index=created_at.index, dtype=bool)
    # Normalize to midnight so an end bound covers the whole end day - every row
    # carries a clock time, so comparing raw timestamps would drop same-day rows.
    day = created_at.dt.normalize()
    if start is not None:
        mask &= day >= pd.Timestamp(start)
    if end is not None:
        mask &= day <= pd.Timestamp(end)
    return mask


def resolve_bucket_window(
    bucket: str,
    today: date,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> Tuple[Optional[date], Optional[date]]:
    """Resolve a bucket name into its (start, end) window. None means unbounded."""
    if bucket in BUCKET_WINDOW_DAYS:
        return today - timedelta(days=BUCKET_WINDOW_DAYS[bucket]), None
    if bucket == "All":
        return None, None
    if bucket == "Custom":
        return start, end
    raise ValueError(f"Unknown bucket {bucket!r}")


def empty_growth_trend() -> Dict[str, List[Dict[str, Any]]]:
    """A fresh, empty growth_trend payload."""
    return {"total_organizations": [], "collaborators": []}


def build_growth_trend(
    df: pd.DataFrame,
    freq: str,
    start: Optional[date],
    end: Optional[date],
) -> Dict[str, List[Dict[str, Any]]]:
    """Build both growth series for one bucket.

    `df` must be the FULL dataset, never a pre-filtered frame: total_organizations
    is an all-time running total, and filtering before the cumulative sum is
    exactly what would reset it to zero at the window start. start/end decide
    only which periods are emitted, never what the counts are.
    """
    if df.empty:
        return empty_growth_trend()

    # Period key for every row in the dataset, not just the window.
    all_periods = df["created_at"].dt.to_period(freq)

    # Prefix sum over all periods, so cumulative[p] already includes every
    # organization created before p - no separate base-count pass needed.
    cumulative = all_periods.value_counts().sort_index().cumsum()

    mask = window_mask(df["created_at"], start, end)
    if not mask.any():
        return empty_growth_trend()

    window = df.loc[mask].copy()
    # Reuse the periods computed above so lookups into cumulative cannot miss.
    window["_period"] = all_periods[mask]
    periods = sorted(window["_period"].unique())

    collaborators = window.loc[window["is_collaborator"], "_period"].value_counts()

    return {
        "total_organizations": [
            {"period": str(period), "count": int(cumulative.get(period, 0))} for period in periods
        ],
        "collaborators": [
            {"period": str(period), "count": int(collaborators.get(period, 0))} for period in periods
        ],
    }


def build_organizations_by_location(
    df: pd.DataFrame,
    start: Optional[date],
    end: Optional[date],
    limit: int = TOP_LOCATION_LIMIT,
) -> List[Dict[str, Any]]:
    """Top countries by organization count within the window. No 'Other', no percentage."""
    if df.empty:
        return []

    window = df.loc[window_mask(df["created_at"], start, end)]
    if window.empty:
        return []

    counts = window["country"].value_counts()
    # Sort count-descending, then country-ascending, so ties are stable across
    # pandas versions instead of falling back on insertion order.
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    return [{"country": country, "count": int(count)} for country, count in ordered[:limit]]


def parse_date_param(value: Any, field_name: str) -> Optional[date]:
    """Parse one YYYY-MM-DD param. None/blank means 'not supplied'."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if not isinstance(value, str):
        raise ValidationError(f"Invalid {field_name}: expected a YYYY-MM-DD string.")

    try:
        # strptime rather than date.fromisoformat, which would also accept
        # "20250105" and "2025-01-05T10:00:00".
        return datetime.strptime(value.strip(), DATE_FORMAT).date()
    except ValueError:
        raise ValidationError(f"Invalid {field_name} '{value}'. Expected format YYYY-MM-DD.")


def parse_date_pair(
    params: Dict[str, Any],
    start_key: str,
    end_key: str,
) -> Tuple[Optional[date], Optional[date]]:
    """Parse and validate one date pair. Either side may be omitted (open-ended)."""
    start = parse_date_param(params.get(start_key), start_key)
    end = parse_date_param(params.get(end_key), end_key)

    if start is not None and end is not None and start > end:
        raise ValidationError(f"{start_key} must be on or before {end_key}.")

    return start, end


def parse_event_body(event: Any) -> Dict[str, Any]:
    """Pull request params out of an API Gateway event, a plain dict, or nothing."""
    if not event:
        return {}
    if not isinstance(event, dict):
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


def build_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """API Gateway proxy response with a JSON-serialized body."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    """Return every time bucket for the Growth & Location tab in one response."""
    params = parse_event_body(event)

    # Validate both pairs up front, independently, before touching the CSVs.
    try:
        growth_start, growth_end = parse_date_pair(params, "start_date", "end_date")
        location_start, location_end = parse_date_pair(
            params, "location_start_date", "location_end_date"
        )
    except ValidationError as exc:
        return build_response(400, {"error": str(exc)})

    try:
        organizations = load_organizations()
    except FileNotFoundError as exc:
        return build_response(500, {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001 - the handler must not leak a stack trace
        print(f"ERROR: could not load organization data: {exc}")
        return build_response(500, {"error": "Could not load organization data."})

    today = _today()
    response: Dict[str, Any] = {}

    # There is no time_filter param - every fixed bucket is always computed.
    for bucket in FIXED_BUCKETS:
        start, end = resolve_bucket_window(bucket, today)
        response[bucket] = {
            "growth_trend": build_growth_trend(organizations, BUCKET_FREQ[bucket], start, end),
            "organizations_by_location": build_organizations_by_location(organizations, start, end),
        }

    # Each half of Custom is gated on its own pair, so the two charts populate
    # independently of one another.
    has_growth_range = growth_start is not None or growth_end is not None
    has_location_range = location_start is not None or location_end is not None

    response["Custom"] = {
        "growth_trend": (
            build_growth_trend(organizations, BUCKET_FREQ["Custom"], growth_start, growth_end)
            if has_growth_range
            else empty_growth_trend()
        ),
        "organizations_by_location": (
            build_organizations_by_location(organizations, location_start, location_end)
            if has_location_range
            else []
        ),
    }

    return build_response(200, response)


SAMPLE_EVENTS = (
    ("no body (all fixed buckets)", {}),
    ("growth range only", {"start_date": "2025-01-01", "end_date": "2025-12-31"}),
    (
        "location range only",
        {"location_start_date": "2024-01-01", "location_end_date": "2024-12-31"},
    ),
    (
        "both ranges",
        {
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "location_start_date": "2024-01-01",
            "location_end_date": "2024-12-31",
        },
    ),
    ("invalid date -> 400", {"start_date": "2025-13-45", "end_date": "2025-12-31"}),
)


if __name__ == "__main__":
    for label, sample_event in SAMPLE_EVENTS:
        print(f"\n=== {label} ===")
        result = lambda_handler(sample_event, None)
        # Re-parse the body so the output is readable instead of one escaped blob.
        print(
            json.dumps(
                {"statusCode": result["statusCode"], "body": json.loads(result["body"])},
                indent=2,
            )
        )
