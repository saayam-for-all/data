import json
import logging
import os
import re
from pathlib import Path

import pandas as pd


def parse_range(payload, start_key, end_key):
    if start_key not in payload and end_key not in payload:
        return None
    dates = []
    for key in (start_key, end_key):
        value = payload.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"{key} must be a date in YYYY-MM-DD format")
        try:
            dates.append(pd.Timestamp(value, tz="UTC"))
        except ValueError as exc:
            raise ValueError(f"{key} must be a valid calendar date") from exc
    if dates[0] > dates[1]:
        raise ValueError(f"{start_key} must not be after {end_key}")
    return dates[0], dates[1] + pd.Timedelta(days=1)


def load_data():
    root = Path(os.environ.get("MOCK_DATA_DIR", Path(__file__).parent / "mock_data"))
    organizations = pd.read_csv(root / "organizations.csv", dtype={"state_id": "string"})
    states = pd.read_csv(root / "states.csv", dtype="string")
    countries = pd.read_csv(root / "countries.csv", dtype="string")
    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"], format="ISO8601", utc=True
    )
    if organizations["created_at"].isna().any():
        raise ValueError("Organizations must have creation dates")
    flags = organizations["is_collaborator"].astype("string").str.strip().str.lower()
    if not flags.isin(["true", "false", "1", "0", "t", "f"]).all():
        raise ValueError("Invalid collaborator flag in CSV data")
    organizations["is_collaborator"] = flags.isin(["true", "1", "t"])
    return organizations.merge(
        states[["state_id", "country_id"]], on="state_id", how="left", validate="many_to_one"
    ).merge(
        countries[["country_id", "country_code"]],
        on="country_id", how="left", validate="many_to_one",
    )


def select_window(data, window):
    if window is None:
        return data
    start, end = window
    return data.loc[(data.created_at >= start) & (data.created_at < end)]


def growth(data, window, monthly=False):
    selected = select_window(data, window).copy()
    selected["period"] = selected.created_at.dt.strftime("%Y-%m" if monthly else "%Y-%m-%d")
    totals, collaborators = [], []
    timestamps = data.created_at.sort_values()
    for period, rows in selected.groupby("period", sort=True):
        boundary = pd.Timestamp(period, tz="UTC")
        boundary += pd.DateOffset(months=1) if monthly else pd.Timedelta(days=1)
        if window is not None:
            boundary = min(boundary, window[1])
        totals.append({"period": period, "count": int(timestamps.searchsorted(boundary))})
        collaborators.append({"period": period, "count": int(rows.is_collaborator.sum())})
    return {"total_organizations": totals, "collaborators": collaborators}


def locations(data, window):
    counts = select_window(data, window).groupby("country_code").size()
    return [
        {"country": country, "count": int(count)}
        for country, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:4]
    ]


def build_analytics(data, growth_range=None, location_range=None, today=None):
    today = pd.Timestamp.now(tz="UTC") if today is None else pd.Timestamp(today)
    today = today.tz_localize("UTC") if today.tzinfo is None else today.tz_convert("UTC")
    today = today.normalize()
    end = today + pd.Timedelta(days=1)
    windows = {
        "7D": (end - pd.Timedelta(days=7), end),
        "30D": (end - pd.Timedelta(days=30), end),
        "1Y": (end - pd.DateOffset(years=1), end),
        "All": None,
    }
    result = {
        key: {
            "growth_trend": growth(data, window, monthly=key in ("1Y", "All")),
            "organizations_by_location": locations(data, window),
        }
        for key, window in windows.items()
    }
    result["Custom"] = {
        "growth_trend": growth(data, growth_range) if growth_range else {
            "total_organizations": [], "collaborators": [],
        },
        "organizations_by_location": locations(data, location_range) if location_range else [],
    }
    return result


def response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    try:
        if not isinstance(event, dict):
            raise ValueError("Request must be a JSON object")
        payload = event.get("body", event)
        if payload is None or payload == "":
            payload = {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        growth_range = parse_range(payload, "start_date", "end_date")
        location_range = parse_range(payload, "location_start_date", "location_end_date")
    except ValueError as exc:
        return response(400, {"error": str(exc)})
    try:
        return response(200, build_analytics(load_data(), growth_range, location_range))
    except Exception:
        logging.exception("Unable to compute growth and location analytics")
        return response(500, {"error": "Unable to load analytics data"})


if __name__ == "__main__":
    growth_dates = {"start_date": "2026-01-01", "end_date": "2026-06-30"}
    location_dates = {"location_start_date": "2025-01-01", "location_end_date": "2025-12-31"}
    for sample in ({}, growth_dates, location_dates, {**growth_dates, **location_dates}):
        print(json.dumps({"event": sample, "response": lambda_handler(sample, None)}, indent=2))
