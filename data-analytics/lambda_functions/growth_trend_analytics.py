import json
import logging
import os
import re
from datetime import datetime

import pandas as pd

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "mock-data-generation")

def load_data():
    org_df = pd.read_csv(os.path.join(DATA_DIR, "organizations.csv"))
    states_df = pd.read_csv(os.path.join(DATA_DIR, "states.csv"))
    countries_df = pd.read_csv(os.path.join(DATA_DIR, "countries.csv"))

    org_df["created_at"] = pd.to_datetime(
        org_df["created_at"], utc=True, errors="coerce"
    ).dt.tz_localize(None)
    org_df = org_df.dropna(subset=["created_at"])
    org_df["is_collaborator"] = org_df["is_collaborator"].map(
        {"TRUE": True, "FALSE": False, True: True, False: False}
    )

    states_df["country_id"] = pd.to_numeric(
        states_df["country_id"], errors="coerce"
    )
    countries_df["country_id"] = pd.to_numeric(
        countries_df["country_id"], errors="coerce"
    )

    return org_df, states_df, countries_df

def _is_blank(value):
    return value is None or (isinstance(value, str) and value.strip() == "")

def _parse_date(value):
    # Strict YYYY-MM-DD only: rejects ints, other formats and timezone strings.
    if not isinstance(value, str):
        return None
    try:
        return pd.Timestamp(datetime.strptime(value.strip(), "%Y-%m-%d"))
    except ValueError:
        return None

def validate_date_pair(start, end):
    # null / "" means "not supplied"; a half pair or a bad value is invalid.
    start_blank, end_blank = _is_blank(start), _is_blank(end)
    if start_blank and end_blank:
        return True, None, None
    if start_blank or end_blank:
        return False, None, None
    s = _parse_date(start)
    e = _parse_date(end)
    if s is None or e is None or s > e:
        return False, None, None
    return True, s, e

def _normalize_name(value):
    # "United States", "united_states" and "UNITED-STATES" all match.
    return re.sub(r"[_\-\s]+", " ", str(value).strip()).upper()

def resolve_country(country, countries_df):
    # Returns (status, country_id); status is "none", "ok", "invalid_type"
    # or "unknown". Blank, null and "ALL" mean no filter.
    if _is_blank(country):
        return "none", None
    if not isinstance(country, str):
        return "invalid_type", None
    if country.strip().upper() == "ALL":
        return "none", None

    key = _normalize_name(country)
    codes = countries_df["country_code"].astype(str).str.strip().str.upper()
    match = countries_df[codes == key]
    if match.empty:
        names = countries_df["country_name"].map(_normalize_name)
        match = countries_df[names == key]
    if match.empty:
        return "unknown", None
    return "ok", match.iloc[0]["country_id"]

def filter_by_country(org_df, states_df, country_id):
    state_ids = states_df.loc[states_df["country_id"] == country_id, "state_id"]
    return org_df[org_df["state_id"].isin(state_ids)]

def filter_by_range(df, start, end):
    # end is a date at midnight; include that whole day.
    return df[
        (df["created_at"] >= start)
        & (df["created_at"] < end + pd.Timedelta(days=1))
    ]

def filter_by_window(df, time_key):
    today = pd.Timestamp.now().normalize()
    if time_key == "7D":
        return df[df["created_at"] >= today - pd.Timedelta(days=6)]
    elif time_key == "30D":
        return df[df["created_at"] >= today - pd.Timedelta(days=29)]
    elif time_key == "1Y":
        # last 12 calendar months incl. current, from the 1st of the month,
        # so the first monthly bucket is not partial
        start = (today - pd.DateOffset(months=11)).replace(day=1)
        return df[df["created_at"] >= start]
    elif time_key == "All":
        return df
    return df

def get_grouping_format(time_key):
    if time_key in ("7D", "30D", "Custom"):
        return "day"
    return "month"

def apply_period(df, grouping):
    df = df.copy()
    if grouping == "day":
        df["period"] = df["created_at"].dt.strftime("%Y-%m-%d")
    else:
        df["period"] = df["created_at"].dt.strftime("%Y-%m")
    return df

def build_growth_trend(full_df, window_df, grouping):
    if len(window_df) == 0:
        return {"total_organizations": [], "collaborators": []}

    full_sorted = full_df.sort_values("created_at").copy()
    full_sorted = apply_period(full_sorted, grouping)

    full_cumulative = (
        full_sorted.groupby("period").size().reset_index(name="count")
    )
    full_cumulative["count"] = full_cumulative["count"].cumsum()

    window_sorted = apply_period(window_df, grouping)
    window_periods = set(window_sorted["period"].unique())

    total_orgs = [
        {"period": r["period"], "count": int(r["count"])}
        for _, r in full_cumulative.iterrows()
        if r["period"] in window_periods
    ]

    collab_window = window_sorted[window_sorted["is_collaborator"] == True]
    if len(collab_window) == 0:
        collab_list = [
            {"period": p, "count": 0} for p in sorted(window_periods)
        ]
    else:
        collab_grouped = (
            collab_window.groupby("period").size().reset_index(name="count")
        )
        collab_dict = dict(
            zip(collab_grouped["period"], collab_grouped["count"])
        )
        collab_list = [
            {"period": p, "count": int(collab_dict.get(p, 0))}
            for p in sorted(window_periods)
        ]

    return {"total_organizations": total_orgs, "collaborators": collab_list}

def _state_name_column(states_df):
    for col in ("state_name", "name", "state"):
        if col in states_df.columns:
            return col
    raise KeyError("states.csv has no state name column")

def build_orgs_by_location(window_df, states_df, countries_df, by_state=False):
    if len(window_df) == 0:
        return []

    if by_state:
        # a country is selected: list its states
        state_col = _state_name_column(states_df)
        merged = window_df.merge(
            states_df[["state_id", state_col]].drop_duplicates("state_id"),
            on="state_id",
            how="left",
        )
        merged[state_col] = merged[state_col].fillna("Unknown")
        key_col, out_key = state_col, "state"
    else:
        merged = window_df.merge(
            states_df[["state_id", "country_id"]].drop_duplicates("state_id"),
            on="state_id",
            how="left",
        )
        merged = merged.merge(
            countries_df[["country_id", "country_code"]],
            on="country_id",
            how="left",
        )
        merged["country_code"] = merged["country_code"].fillna("Unknown")
        key_col, out_key = "country_code", "country"

    grouped = merged.groupby(key_col).size().reset_index(name="count")
    # highest count first, then alphabetical; no limit, no "Other"
    grouped = grouped.sort_values(
        ["count", key_col], ascending=[False, True], kind="mergesort"
    )

    return [
        {out_key: r[key_col], "count": int(r["count"])}
        for _, r in grouped.iterrows()
    ]

def _response(status_code, payload):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(payload),
    }

def lambda_handler(event, context):
    try:
        raw_body = event.get("body")
        if raw_body and isinstance(raw_body, str):
            body = json.loads(raw_body)
        elif raw_body and isinstance(raw_body, dict):
            body = raw_body
        else:
            body = event if event else {}

        if not isinstance(body, dict):
            return _response(
                400, {"error": "Request body must be a JSON object"}
            )

        org_df, states_df, countries_df = load_data()

        start_date = body.get("start_date")
        end_date = body.get("end_date")

        valid, start, end = validate_date_pair(start_date, end_date)

        if not valid:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps(
                    {
                        "error": (
                            "Invalid date format or "
                            "start_date after end_date"
                        )
                    }
                ),
            }

        country_status, country_id = resolve_country(
            body.get("country"), countries_df
        )
        if country_status == "invalid_type":
            return _response(400, {"error": "country must be a string"})
        if country_status == "unknown":
            return _response(400, {"error": "Unknown country"})

        by_state = country_status == "ok"
        if by_state:
            # filter first so both charts (and the cumulative totals) use it
            org_df = filter_by_country(org_df, states_df, country_id)

        is_custom = start is not None and end is not None

        if is_custom:
            window_df = filter_by_range(org_df, start, end)
            response = {
                "Custom": {
                    "growth_trend": build_growth_trend(
                        org_df, window_df, "day"
                    ),
                    "organizations_by_location": build_orgs_by_location(
                        window_df, states_df, countries_df, by_state
                    ),
                }
            }
        else:
            response = {}
            for time_key in ["7D", "30D", "1Y", "All"]:
                window_df = filter_by_window(org_df, time_key)
                grouping = get_grouping_format(time_key)

                growth = build_growth_trend(org_df, window_df, grouping)
                location = build_orgs_by_location(
                    window_df, states_df, countries_df, by_state
                )

                response[time_key] = {
                    "growth_trend": growth,
                    "organizations_by_location": location,
                }

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(response),
        }

    except json.JSONDecodeError as e:
        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(
                {"error": "Invalid JSON in request body"}
            ),
        }

    except Exception as e:
        logger.exception("org-growth-location-analytics error")
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(
                {"error": "Internal server error"}
            ),
        }