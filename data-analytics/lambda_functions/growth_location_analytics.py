"""Lambda entry point for Growth & Location Analytics (#336).

Two charts for the org dashboard's Growth & Location tab: growth_trend
(organizations + collaborators over time) and organizations_by_location
(top countries by organization count).

The four fixed buckets ("7D", "30D", "1Y", "All") are always computed and
returned. "Custom" is only included in the response when at least one of
the two independent Custom date-range pairs is supplied:
  - start_date/end_date -> Custom.growth_trend
  - location_start_date/location_end_date -> Custom.organizations_by_location
Each pair populates its own section of Custom independently; the other
section is returned empty if its pair wasn't supplied.

Single file per the existing analytics Lambda convention in this
directory (see kpi_api_analytics.py, volunteer_application_analytics.py,
beneficiariesTrendAnalysis.py).
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

# ---------------------------------------------------------------------------
# Data loading (join organizations/states/countries into one DataFrame)
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = {
    "organizations": ("org_id", "state_id", "city_name", "is_collaborator", "created_at"),
    "states": ("state_id", "state_name", "country_id"),
    "countries": ("country_id", "country_code"),
}

_TRUE_VALUES = {"true", "1", "yes", "y", "t"}
_FALSE_VALUES = {"false", "0", "no", "n", "f"}


class DataLoadError(ValueError):
    """Raised when the local CSV inputs are missing, malformed, or invalid."""


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


def _normalize_is_collaborator(series, filename):
    normalized = series.astype(str).str.strip().str.lower()
    unrecognized = ~normalized.isin(_TRUE_VALUES | _FALSE_VALUES)
    if unrecognized.any():
        bad_values = sorted(set(series[unrecognized].astype(str)))
        raise DataLoadError(
            f"{filename}: column 'is_collaborator' has unrecognized values {bad_values}; "
            f"expected one of {sorted(_TRUE_VALUES | _FALSE_VALUES)}"
        )
    return normalized.isin(_TRUE_VALUES)


def _normalize_created_at(series, filename):
    # Parsed element-wise rather than via pd.to_datetime(series, ...) directly:
    # that column-wide fast path infers ONE format from an early value and
    # applies it to the whole column, silently marking every row in a
    # different (but valid) format as unparseable -- exactly the mixed
    # date-only / full-timestamp scenario this loader needs to tolerate.
    parsed = series.apply(lambda value: pd.to_datetime(value, utc=True, errors="coerce"))
    if parsed.isna().any():
        bad_rows = series[parsed.isna()].tolist()
        raise DataLoadError(f"{filename}: column 'created_at' has unparseable values {bad_rows}")
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


def load_data(data_dir=None):
    """Loads organizations/states/countries and returns one joined DataFrame.

    The returned frame has one row per organization with a `country_code`
    column attached via states.country_id -> countries.country_id, plus a
    normalized boolean `is_collaborator` and a UTC-aware `created_at`.
    """
    directory = _mock_data_dir(data_dir)

    organizations = _read_csv(directory, "organizations.csv", REQUIRED_COLUMNS["organizations"])
    states = _read_csv(directory, "states.csv", REQUIRED_COLUMNS["states"])
    countries = _read_csv(directory, "countries.csv", REQUIRED_COLUMNS["countries"])

    _assert_unique_key(states, "state_id", "states.csv")
    _assert_unique_key(countries, "country_id", "countries.csv")

    organizations = organizations.copy()
    organizations["is_collaborator"] = _normalize_is_collaborator(
        organizations["is_collaborator"], "organizations.csv"
    )
    organizations["created_at"] = _normalize_created_at(
        organizations["created_at"], "organizations.csv"
    )

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


# ---------------------------------------------------------------------------
# Date-window resolution and the growth/location calculations
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


def compute_growth_trend(df, start, end, granularity):
    """total_organizations is an all-time cumulative count as of each period
    (never reset to the window); collaborators is window-scoped per period.
    Both are sparse: a period only appears if it has activity in the window.
    """
    upto_end = df[df["created_at"] < end]
    in_window = upto_end[upto_end["created_at"] >= start] if start is not None else upto_end

    if in_window.empty:
        return {"total_organizations": [], "collaborators": []}

    in_window = in_window.copy()
    in_window["period"] = in_window["created_at"].apply(lambda t: _period_label(t, granularity))
    periods = sorted(in_window["period"].unique())

    upto_end = upto_end.copy()
    upto_end["period"] = upto_end["created_at"].apply(lambda t: _period_label(t, granularity))
    total_series = [
        {"period": p, "count": int((upto_end["period"] <= p).sum())} for p in periods
    ]

    collab_counts = (
        in_window[in_window["is_collaborator"]].groupby("period").size().to_dict()
    )
    collaborators_series = [
        {"period": p, "count": int(collab_counts.get(p, 0))} for p in periods
    ]

    return {"total_organizations": total_series, "collaborators": collaborators_series}


def compute_locations(df, start, end):
    """Top 4 countries by organization count within the window, descending.
    No "Other" entry, no percentage field.
    """
    upto_end = df[df["created_at"] < end]
    in_window = upto_end[upto_end["created_at"] >= start] if start is not None else upto_end

    if in_window.empty:
        return []

    counts = in_window.groupby("country_code").size().sort_values(ascending=False)
    return [{"country": country, "count": int(count)} for country, count in counts.head(4).items()]


def build_bucket(df, start, end, granularity):
    return {
        "growth_trend": compute_growth_trend(df, start, end, granularity),
        "organizations_by_location": compute_locations(df, start, end),
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

# Cached per warm Lambda instance: AWS often reuses the same running
# container across back-to-back invocations, so a cold start pays for
# load_data() once and every subsequent warm call on that instance reuses
# the same DataFrame instead of re-reading the CSVs from disk. This is a
# per-instance cache only -- each of the fleet's instances still loads its
# own copy once. A fleet-wide one-time load would need a shared cache
# (e.g. ElastiCache) in front of this, which is a deployment decision.
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
        growth_custom = parse_custom_pair(params, "start_date", "end_date")
        location_custom = parse_custom_pair(
            params, "location_start_date", "location_end_date"
        )
    except DateRangeError as exc:
        return _response(400, {"error": str(exc)})

    try:
        df = _get_data()
    except DataLoadError as exc:
        return _response(500, {"error": f"Failed to load analytics data: {exc}"})

    now = datetime.now(timezone.utc)
    result = {}
    for bucket, (start, end, granularity) in fixed_windows(now).items():
        result[bucket] = build_bucket(df, start, end, granularity)

    if growth_custom or location_custom:
        growth_start, growth_end = growth_custom if growth_custom else (None, None)
        location_start, location_end = location_custom if location_custom else (None, None)

        custom_growth_trend = (
            compute_growth_trend(df, growth_start, growth_end, "day")
            if growth_custom
            else {"total_organizations": [], "collaborators": []}
        )
        custom_locations = (
            compute_locations(df, location_start, location_end)
            if location_custom
            else []
        )
        result["Custom"] = {
            "growth_trend": custom_growth_trend,
            "organizations_by_location": custom_locations,
        }

    expected_keys = ALL_BUCKETS if (growth_custom or location_custom) else FIXED_BUCKETS
    assert tuple(result) == expected_keys, "unexpected bucket configuration"
    return _response(200, result)


def _run_local_samples():
    """Prints the handler's output for a handful of representative requests.
    Run with `MOCK_DATA_DIR=/path/to/csvs python growth_location_analytics.py`.
    """
    samples = {
        "no params": {},
        "growth Custom only": {"start_date": "2026-01-01", "end_date": "2026-06-30"},
        "location Custom only": {
            "location_start_date": "2025-01-01",
            "location_end_date": "2025-12-31",
        },
        "both Custom ranges": {
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "location_start_date": "2025-01-01",
            "location_end_date": "2025-12-31",
        },
        "lone start_date (should be 400)": {"start_date": "2026-01-01"},
        "malformed date (should be 400)": {"start_date": "not-a-date", "end_date": "2026-06-30"},
        "start after end (should be 400)": {"start_date": "2026-06-30", "end_date": "2026-01-01"},
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
