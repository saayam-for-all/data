"""Lambda entry point for Growth & Location Analytics (#336).

Returns all five fixed-and-custom analytics buckets ("7D", "30D", "1Y",
"All", "Custom") in a single response, so the frontend can switch time
ranges without another round trip.
"""
import json
import os
from datetime import datetime, timezone

from analytics import (
    DateRangeError,
    build_bucket,
    fixed_windows,
    parse_custom_pair,
)
from loader import DataLoadError, load_data

ALL_BUCKETS = ("7D", "30D", "1Y", "All", "Custom")

_JSON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


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
        df = load_data()
    except DataLoadError as exc:
        return _response(500, {"error": f"Failed to load analytics data: {exc}"})

    now = datetime.now(timezone.utc)
    result = {}
    for bucket, (start, end, granularity) in fixed_windows(now).items():
        result[bucket] = build_bucket(df, start, end, granularity)

    growth_start, growth_end = growth_custom if growth_custom else (None, None)
    location_start, location_end = location_custom if location_custom else (None, None)

    custom_growth_trend = (
        build_bucket(df, growth_start, growth_end, "day")["growth_trend"]
        if growth_custom
        else {"total_organizations": [], "collaborators": []}
    )
    custom_locations = (
        build_bucket(df, location_start, location_end, "day")["organizations_by_location"]
        if location_custom
        else []
    )
    result["Custom"] = {
        "growth_trend": custom_growth_trend,
        "organizations_by_location": custom_locations,
    }

    assert tuple(result) == ALL_BUCKETS, "unexpected bucket configuration"
    return _response(200, result)


def _run_local_samples():
    """Prints the handler's output for a handful of representative requests.
    Run with `MOCK_DATA_DIR=/path/to/csvs python lambda_function.py`.
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
