"""Growth and location analytics Lambda for the organization dashboard."""
import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

REQUIRED_COLUMNS = {
    "organizations": ("org_id", "state_id", "city_name", "is_collaborator", "created_at"),
    "states": ("state_id", "state_name", "country_id"),
    "countries": ("country_id", "country_code"),
}
_TRUE_VALUES = {"true", "1", "yes", "y", "t"}
_FALSE_VALUES = {"false", "0", "no", "n", "f"}
_DATE_FORMAT = "%Y-%m-%d"
FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
ALL_BUCKETS = FIXED_BUCKETS + ("Custom",)
_JSON_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
_cached_df = None


class DataLoadError(ValueError):
    """Raised when local CSV inputs are missing, malformed, or invalid."""


class DateRangeError(ValueError):
    """Raised for invalid or incomplete custom date-range parameters."""


def _mock_data_dir(data_dir=None):
    if data_dir is not None:
        return data_dir
    configured = os.environ.get("MOCK_DATA_DIR")
    if configured:
        return configured
    default_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sql")
    if os.path.isdir(default_dir):
        return default_dir
    raise DataLoadError("Set MOCK_DATA_DIR to the directory containing the analytics CSV files")


def _resolve_csv(directory, names):
    for filename in names:
        path = os.path.join(directory, filename)
        if os.path.isfile(path):
            return path, filename
    if os.path.isdir(directory):
        actual = {name.lower(): name for name in os.listdir(directory)}
        for filename in names:
            match = actual.get(filename.lower())
            if match:
                return os.path.join(directory, match), match
    raise DataLoadError(f"Missing required file: one of {list(names)}")


def _read_csv(directory, names, required_columns):
    path, filename = _resolve_csv(directory, names)
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError as exc:
        raise DataLoadError(f"{filename}: file is empty") from exc
    except pd.errors.ParserError as exc:
        raise DataLoadError(f"{filename}: could not be parsed as CSV") from exc
    missing = set(required_columns) - set(df.columns)
    if missing:
        raise DataLoadError(f"{filename}: missing required columns: {sorted(missing)}")
    return df, filename


def _normalize_is_collaborator(series, filename):
    normalized = series.astype(str).str.strip().str.lower()
    unrecognized = ~normalized.isin(_TRUE_VALUES | _FALSE_VALUES)
    if unrecognized.any():
        bad_values = sorted(set(series[unrecognized].astype(str)))
        raise DataLoadError(
            f"{filename}: column 'is_collaborator' has unrecognized values {bad_values}"
        )
    return normalized.isin(_TRUE_VALUES)


def _normalize_created_at(series, filename):
    parsed = series.apply(lambda value: pd.to_datetime(value, utc=True, errors="coerce"))
    if parsed.isna().any():
        bad_rows = series[parsed.isna()].tolist()
        raise DataLoadError(f"{filename}: column 'created_at' has unparseable values {bad_rows}")
    return pd.to_datetime(parsed, utc=True)


def _assert_unique_key(df, column, filename):
    duplicates = df[column][df[column].duplicated()]
    if not duplicates.empty:
        bad_ids = sorted(duplicates.unique().tolist())
        raise DataLoadError(
            f"{filename}: column '{column}' has duplicate value(s) {bad_ids}"
        )


def load_data(data_dir=None):
    directory = _mock_data_dir(data_dir)
    organizations, org_filename = _read_csv(
        directory, ("organizations.csv",), REQUIRED_COLUMNS["organizations"]
    )
    states, states_filename = _read_csv(
        directory, ("states.csv", "state.csv"), REQUIRED_COLUMNS["states"]
    )
    countries, countries_filename = _read_csv(
        directory, ("countries.csv", "country.csv"), REQUIRED_COLUMNS["countries"]
    )
    _assert_unique_key(states, "state_id", states_filename)
    _assert_unique_key(countries, "country_id", countries_filename)
    organizations = organizations.copy()
    organizations["is_collaborator"] = _normalize_is_collaborator(
        organizations["is_collaborator"], org_filename
    )
    organizations["created_at"] = _normalize_created_at(
        organizations["created_at"], org_filename
    )
    merged = organizations.merge(
        states[["state_id", "country_id"]], on="state_id", how="left", validate="many_to_one"
    ).merge(
        countries[["country_id", "country_code"]], on="country_id", how="left", validate="many_to_one"
    )
    merged["country_code"] = merged["country_code"].fillna("Unknown")
    return merged


def _calendar_months_back(now, n):
    year, month = now.year, now.month - (n - 1)
    while month < 1:
        month += 12
        year -= 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def fixed_windows(now):
    return {
        "7D": (now - timedelta(days=6), now + timedelta(days=1), "day"),
        "30D": (now - timedelta(days=29), now + timedelta(days=1), "day"),
        "1Y": (_calendar_months_back(now, 12), now + timedelta(days=1), "month"),
        "All": (None, now + timedelta(days=1), "month"),
    }


def parse_custom_pair(params, start_key, end_key):
    start_raw = params.get(start_key)
    end_raw = params.get(end_key)
    if start_raw is None and end_raw is None:
        return None
    if start_raw is None or end_raw is None:
        raise DateRangeError(f"{start_key} and {end_key} must be supplied together")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        raise DateRangeError(f"{start_key} and {end_key} must use YYYY-MM-DD format")
    try:
        start = datetime.strptime(start_raw, _DATE_FORMAT).replace(tzinfo=timezone.utc)
        end = datetime.strptime(end_raw, _DATE_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise DateRangeError("Custom dates must use YYYY-MM-DD format") from exc
    if start.strftime(_DATE_FORMAT) != start_raw or end.strftime(_DATE_FORMAT) != end_raw:
        raise DateRangeError("Custom dates must use YYYY-MM-DD format")
    if start > end:
        raise DateRangeError(f"{start_key} must be on or before {end_key}")
    return start, end + timedelta(days=1)


def _period_label(ts, granularity):
    return ts.strftime("%Y-%m-%d") if granularity == "day" else ts.strftime("%Y-%m")


def compute_growth_trend(df, start, end, granularity):
    upto_end = df[df["created_at"] < end]
    in_window = upto_end[upto_end["created_at"] >= start] if start is not None else upto_end
    if in_window.empty:
        return {"total_organizations": [], "collaborators": []}

    in_window = in_window.copy()
    in_window["period"] = in_window["created_at"].apply(
        lambda timestamp: _period_label(timestamp, granularity)
    )
    periods = sorted(in_window["period"].unique())

    upto_end = upto_end.copy()
    upto_end["period"] = upto_end["created_at"].apply(
        lambda timestamp: _period_label(timestamp, granularity)
    )
    total_series = [
        {"period": period, "count": int((upto_end["period"] <= period).sum())}
        for period in periods
    ]
    collaborator_counts = (
        in_window[in_window["is_collaborator"]].groupby("period").size().to_dict()
    )
    collaborator_series = [
        {"period": period, "count": int(collaborator_counts.get(period, 0))}
        for period in periods
    ]
    return {
        "total_organizations": total_series,
        "collaborators": collaborator_series,
    }


def compute_locations(df, start, end):
    upto_end = df[df["created_at"] < end]
    in_window = upto_end[upto_end["created_at"] >= start] if start is not None else upto_end
    if in_window.empty:
        return []
    counts = in_window.groupby("country_code").size().sort_values(ascending=False)
    return [
        {"country": str(country), "count": int(count)}
        for country, count in counts.head(4).items()
    ]


def build_bucket(df, start, end, granularity):
    return {
        "growth_trend": compute_growth_trend(df, start, end, granularity),
        "organizations_by_location": compute_locations(df, start, end),
    }


def _get_data():
    global _cached_df
    if _cached_df is None:
        _cached_df = load_data()
    return _cached_df


def clear_data_cache():
    global _cached_df
    _cached_df = None


def _parse_event_body(event):
    if not isinstance(event, dict):
        raise ValueError("event must be a JSON object")
    if "body" not in event:
        return event
    raw_body = event["body"]
    if raw_body is None:
        return {}
    if isinstance(raw_body, dict):
        return raw_body
    parsed = json.loads(raw_body)
    if not isinstance(parsed, dict):
        raise ValueError("body must be a JSON object")
    return parsed


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
    except (DataLoadError, OSError, ValueError):
        return _response(500, {"error": "Failed to load analytics data"})

    now = datetime.now(timezone.utc)
    result = {}
    for bucket, (start, end, granularity) in fixed_windows(now).items():
        result[bucket] = build_bucket(df, start, end, granularity)

    custom_growth = {
        "total_organizations": [],
        "collaborators": [],
    }
    custom_locations = []

    if growth_custom:
        growth_start, growth_end = growth_custom
        custom_growth = compute_growth_trend(
            df,
            growth_start,
            growth_end,
            "day",
        )

    if location_custom:
        location_start, location_end = location_custom
        custom_locations = compute_locations(
            df,
            location_start,
            location_end,
        )

    result["Custom"] = {
        "growth_trend": custom_growth,
        "organizations_by_location": custom_locations,
    }

    assert tuple(result) == ALL_BUCKETS
    return _response(200, result)


def _run_local_samples():
    samples = {
        "default": {},
        "growth custom": {
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
        },
        "location custom": {
            "location_start_date": "2025-01-01",
            "location_end_date": "2025-12-31",
        },
        "both custom": {
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "location_start_date": "2025-01-01",
            "location_end_date": "2025-12-31",
        },
    }
    for label, event in samples.items():
        print(f"\n=== {label} ===")
        response = lambda_handler(event, None)
        print(f"status={response['statusCode']}")
        print(json.dumps(json.loads(response["body"]), indent=2))


if __name__ == "__main__":
    _run_local_samples()
