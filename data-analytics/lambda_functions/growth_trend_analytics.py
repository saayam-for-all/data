import json
import logging
import os
import re
from datetime import datetime

import pandas as pd


logger = logging.getLogger()
logger.setLevel(logging.INFO)

DATA_DIR = os.path.join(os.path.dirname(__file__), "mock_data")


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

def resolve_country(country, countries_df):
    """Return (country_code, error). (None, None) means no country filter."""
    if country is None:
        return None, None
    if not isinstance(country, str):
        return None, "country must be a string"
    key = re.sub(r"\s+", "_", country.strip().upper())
    if key in ("", "ALL"):
        return None, None
    codes = countries_df["country_code"].astype(str).str.upper()
    names = countries_df["country_name"].astype(str).str.upper()
    match = countries_df[(codes == key) | (names == key)]
    if match.empty:
        return None, "Unknown country"
    return str(match.iloc[0]["country_code"]), None


_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _parse_date(value):
    # Strict YYYY-MM-DD only: rejects ints, other formats and timezone strings.
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not _DATE_RE.fullmatch(value):
        return None
    try:
        return pd.Timestamp(datetime.strptime(value, "%Y-%m-%d"))
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

def filter_by_country(org_df, states_df, countries_df, country_code):
    if country_code is None:
        return org_df
    state_country = states_df.merge(
        countries_df[["country_id", "country_code"]], on="country_id", how="left"
    )
    state_ids = state_country.loc[
        state_country["country_code"] == country_code, "state_id"
    ]
    return org_df[org_df["state_id"].isin(state_ids)]

def build_orgs_by_location(window_df, states_df, countries_df, country_code=None):
    if len(window_df) == 0:
        return []

    merged = window_df.merge(
        states_df[["state_id", "country_id", "state_name"]],
        on="state_id",
        how="left",
    )
    merged = merged.merge(
        countries_df[["country_id", "country_code"]],
        on="country_id",
        how="left",
    )
    merged["country_code"] = merged["country_code"].fillna("Unknown")

    if country_code is None:
        counts = merged.groupby("country_code").size().reset_index(name="count")
        counts = counts.sort_values(
            ["count", "country_code"], ascending=[False, True]
        )
        return [
            {"country": r["country_code"], "count": int(r["count"])}
            for _, r in counts.iterrows()
        ]

    in_country = merged[merged["country_code"] == country_code]
    counts = in_country.groupby("state_name").size().reset_index(name="count")
    counts = counts.sort_values(["count", "state_name"], ascending=[False, True])
    return [
        {"state": r["state_name"], "count": int(r["count"])}
        for _, r in counts.iterrows()
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
        raw_body = event.get("body") if isinstance(event, dict) else None
        if raw_body and isinstance(raw_body, str):
            body = json.loads(raw_body)
        elif raw_body and isinstance(raw_body, dict):
            body = raw_body
        else:
            body = event if event else {}

        if not isinstance(body, dict):
            return _response(400, {"error": "Request body must be a JSON object"})

        valid, start, end = validate_date_pair(
            body.get("start_date"), body.get("end_date")
        )
        if not valid:
            return _response(
                400,
                {"error": "Invalid date format or start_date after end_date"},
            )

        org_df, states_df, countries_df = load_data()

        country_code, country_error = resolve_country(
            body.get("country"), countries_df
        )
        if country_error:
            return _response(400, {"error": country_error})

        org_df = filter_by_country(org_df, states_df, countries_df, country_code)

        if start is not None:
            window_df = filter_by_range(org_df, start, end)
            response = {
                "Custom": {
                    "growth_trend": build_growth_trend(org_df, window_df, "day"),
                    "organizations_by_location": build_orgs_by_location(
                        window_df, states_df, countries_df, country_code
                    ),
                }
            }
        else:
            response = {}
            for time_key in ["7D", "30D", "1Y", "All"]:
                window_df = filter_by_window(org_df, time_key)
                response[time_key] = {
                    "growth_trend": build_growth_trend(
                        org_df, window_df, get_grouping_format(time_key)
                    ),
                    "organizations_by_location": build_orgs_by_location(
                        window_df, states_df, countries_df, country_code
                    ),
                }

        return _response(200, response)

    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON in request body"})

    except Exception:
        logger.exception("growth-trend-analytics error")
        return _response(500, {"error": "Internal server error"})