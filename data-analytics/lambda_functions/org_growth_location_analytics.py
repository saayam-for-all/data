import json
import pandas as pd
import os
from datetime import datetime


def load_data(sql_dir):
    org_df = pd.read_csv(os.path.join(sql_dir, "organizations.csv"))
    states_df = pd.read_csv(os.path.join(sql_dir, "states.csv"))
    countries_df = pd.read_csv(os.path.join(sql_dir, "countries.csv"))

    org_df["created_at"] = pd.to_datetime(org_df["created_at"])
    org_df["is_collaborator"] = org_df["is_collaborator"].map(
        {"TRUE": True, "FALSE": False, True: True, False: False}
    )

    states_df["country_id"] = pd.to_numeric(states_df["country_id"], errors="coerce")
    countries_df["country_id"] = pd.to_numeric(countries_df["country_id"], errors="coerce")

    return org_df, states_df, countries_df


def validate_date_pair(start, end):
    if start is None and end is None:
        return True, None, None
    if start is None or end is None:
        return False, None, None
    try:
        s = pd.Timestamp(start)
        e = pd.Timestamp(end)
    except Exception:
        return False, None, None
    if s > e:
        return False, None, None
    return True, s, e


def filter_by_window(df, time_key):
    today = pd.Timestamp.now().normalize()
    if time_key == "7D":
        return df[df["created_at"] >= today - pd.Timedelta(days=7)]
    elif time_key == "30D":
        return df[df["created_at"] >= today - pd.Timedelta(days=30)]
    elif time_key == "1Y":
        return df[df["created_at"] >= today - pd.DateOffset(years=1)]
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

    full_cumulative = full_sorted.groupby("period").size().reset_index(name="count")
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
        collab_list = [{"period": p, "count": 0} for p in sorted(window_periods)]
    else:
        collab_grouped = collab_window.groupby("period").size().reset_index(name="count")
        collab_dict = dict(zip(collab_grouped["period"], collab_grouped["count"]))
        collab_list = [
            {"period": p, "count": int(collab_dict.get(p, 0))}
            for p in sorted(window_periods)
        ]

    return {"total_organizations": total_orgs, "collaborators": collab_list}


def build_orgs_by_location(window_df, states_df, countries_df):
    if len(window_df) == 0:
        return []

    merged = window_df.merge(states_df[["state_id", "country_id"]], on="state_id", how="left")
    merged = merged.merge(countries_df[["country_id", "country_code"]], on="country_id", how="left")
    merged["country_code"] = merged["country_code"].fillna("Unknown")

    by_country = merged.groupby("country_code").size().reset_index(name="count")
    by_country = by_country.sort_values("count", ascending=False).head(4)

    return [
        {"country": r["country_code"], "count": int(r["count"])}
        for _, r in by_country.iterrows()
    ]


def handler(event, org_df, states_df, countries_df):
    body = event if event else {}

    start_date = body.get("start_date")
    end_date = body.get("end_date")
    location_start_date = body.get("location_start_date")
    location_end_date = body.get("location_end_date")

    valid_trend, trend_start, trend_end = validate_date_pair(start_date, end_date)
    valid_loc, loc_start, loc_end = validate_date_pair(location_start_date, location_end_date)

    if not valid_trend or not valid_loc:
        return {"statusCode": 400, "body": {"error": "Invalid date format or start_date after end_date"}}

    has_trend_custom = trend_start is not None and trend_end is not None
    has_loc_custom = loc_start is not None and loc_end is not None
    is_custom = has_trend_custom or has_loc_custom

    if is_custom:
        custom_growth = {"total_organizations": [], "collaborators": []}
        custom_location = []

        if has_trend_custom:
            trend_window = org_df[
                (org_df["created_at"] >= trend_start) & (org_df["created_at"] <= trend_end)
            ]
            custom_growth = build_growth_trend(org_df, trend_window, "day")

        if has_loc_custom:
            loc_window = org_df[
                (org_df["created_at"] >= loc_start) & (org_df["created_at"] <= loc_end)
            ]
            custom_location = build_orgs_by_location(loc_window, states_df, countries_df)

        response = {
            "Custom": {
                "growth_trend": custom_growth,
                "organizations_by_location": custom_location
            }
        }
    else:
        response = {}
        for time_key in ["7D", "30D", "1Y", "All"]:
            window_df = filter_by_window(org_df, time_key)
            grouping = get_grouping_format(time_key)

            growth = build_growth_trend(org_df, window_df, grouping)
            location = build_orgs_by_location(window_df, states_df, countries_df)

            response[time_key] = {
                "growth_trend": growth,
                "organizations_by_location": location
            }

    return {"statusCode": 200, "body": response}
