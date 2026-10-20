import json
import logging
import os
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


def build_orgs_by_location(window_df, states_df, countries_df):
    if len(window_df) == 0:
        return []

    merged = window_df.merge(
        states_df[["state_id", "country_id"]], on="state_id", how="left"
    )
    merged = merged.merge(
        countries_df[["country_id", "country_code"]],
        on="country_id",
        how="left",
    )
    merged["country_code"] = merged["country_code"].fillna("Unknown")

    by_country = (
        merged.groupby("country_code").size().reset_index(name="count")
    )
    by_country = by_country.sort_values("count", ascending=False).head(4)

    return [
        {"country": r["country_code"], "count": int(r["count"])}
        for _, r in by_country.iterrows()
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
        location_start_date = body.get("location_start_date")
        location_end_date = body.get("location_end_date")

        valid_trend, trend_start, trend_end = validate_date_pair(
            start_date, end_date
        )
        valid_loc, loc_start, loc_end = validate_date_pair(
            location_start_date, location_end_date
        )

        if not valid_trend or not valid_loc:
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

        has_trend_custom = trend_start is not None and trend_end is not None
        has_loc_custom = loc_start is not None and loc_end is not None
        is_custom = has_trend_custom or has_loc_custom

        if is_custom:
            custom_growth = {
                "total_organizations": [],
                "collaborators": [],
            }
            custom_location = []

            if has_trend_custom:
                trend_window = filter_by_range(org_df, trend_start, trend_end)
                custom_growth = build_growth_trend(
                    org_df, trend_window, "day"
                )

            if has_loc_custom:
                loc_window = filter_by_range(org_df, loc_start, loc_end)
                custom_location = build_orgs_by_location(
                    loc_window, states_df, countries_df
                )

            response = {
                "Custom": {
                    "growth_trend": custom_growth,
                    "organizations_by_location": custom_location,
                }
            }
        else:
            response = {}
            for time_key in ["7D", "30D", "1Y", "All"]:
                window_df = filter_by_window(org_df, time_key)
                grouping = get_grouping_format(time_key)

                growth = build_growth_trend(org_df, window_df, grouping)
                location = build_orgs_by_location(
                    window_df, states_df, countries_df
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
