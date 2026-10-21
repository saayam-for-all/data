import json
import logging
import os
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
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
        if parsed.strftime("%Y-%m-%d") != value:
            return None
        return pd.Timestamp(parsed)
    except ValueError:
        return None


def validate_date_pair(start, end):
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


def resolve_country(country, countries_df):
    if country is None:
        return None
    if not isinstance(country, str):
        raise ValueError("country must be a string")
    normalized = country.strip().replace("_", " ").casefold()
    if normalized in ("", "all"):
        return None

    names = countries_df["country_name"].str.replace("_", " ").str.casefold()
    codes = countries_df["country_code"].str.casefold()
    matches = countries_df.loc[
        (names == normalized) | (codes == normalized), "country_id"
    ]
    if matches.empty:
        raise ValueError("Unknown country")
    return matches.iloc[0]


def build_orgs_by_location(window_df, states_df, countries_df, country_id=None):
    if window_df.empty:
        return []

    merged = window_df.merge(
        states_df[["state_id", "state_name", "country_id"]],
        on="state_id",
        how="left",
    )
    if country_id is None:
        merged = merged.merge(
            countries_df[["country_id", "country_code"]],
            on="country_id",
            how="left",
        )
        column, label = "country_code", "country"
        merged[column] = merged[column].fillna("Unknown")
    else:
        merged = merged[merged["country_id"] == country_id]
        column, label = "state_name", "state"

    counts = merged.groupby(column).size().reset_index(name="count")
    counts = counts.sort_values(["count", column], ascending=[False, True])
    return [
        {label: row[column], "count": int(row["count"])}
        for _, row in counts.iterrows()
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

        valid, start, end = validate_date_pair(
            body.get("start_date"), body.get("end_date")
        )
        if not valid:
            return _response(
                400, {"error": "Invalid date format or start_date after end_date"}
            )

        org_df, states_df, countries_df = load_data()
        try:
            country_id = resolve_country(body.get("country"), countries_df)
        except ValueError as exc:
            return _response(400, {"error": str(exc)})

        if country_id is not None:
            state_ids = states_df.loc[
                states_df["country_id"] == country_id, "state_id"
            ]
            org_df = org_df[org_df["state_id"].isin(state_ids)]

        time_keys = ["Custom"] if start is not None else ["7D", "30D", "1Y", "All"]
        response = {}
        for time_key in time_keys:
            window_df = (
                filter_by_range(org_df, start, end)
                if time_key == "Custom"
                else filter_by_window(org_df, time_key)
            )
            response[time_key] = {
                "growth_trend": build_growth_trend(
                    org_df, window_df, get_grouping_format(time_key)
                ),
                "organizations_by_location": build_orgs_by_location(
                    window_df, states_df, countries_df, country_id
                ),
            }

        return _response(200, response)

    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON in request body"})
    except Exception:
        logger.exception("org-growth-location-analytics error")
        return _response(500, {"error": "Internal server error"})
