import json
import logging
import os
from datetime import datetime

import pandas as pd


logger = logging.getLogger()
logger.setLevel(logging.INFO)

DATA_DIR = os.path.join(os.path.dirname(__file__), "mock_data")
# Use the repository dataset locally and the packaged CSVs in Lambda.
if not os.path.isdir(DATA_DIR):
    DATA_DIR = os.path.join(
        os.path.dirname(__file__), "..", "mock-data-generation"
    )


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
    value = value.strip()
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
        if parsed.strftime("%Y-%m-%d") != value:
            return None
        return pd.Timestamp(parsed)
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


def _normalize_country(value):
    return " ".join(value.replace("_", " ").casefold().split())


def resolve_country(country, countries_df):
    if _is_blank(country):
        return None
    if not isinstance(country, str):
        raise ValueError("country must be a string")

    normalized = _normalize_country(country)
    if normalized == "all":
        return None

    matches = countries_df[
        (countries_df["country_code"].map(_normalize_country) == normalized)
        | (countries_df["country_name"].map(_normalize_country) == normalized)
    ]
    if matches.empty:
        raise ValueError("Unknown country")
    return matches.iloc[0]["country_id"]


def build_orgs_by_location(window_df, country_filtered=False):
    if len(window_df) == 0:
        return []

    column = "state_name" if country_filtered else "country_code"
    key = "state" if country_filtered else "country"
    by_location = (
        window_df[column].fillna("Unknown")
        .value_counts()
        .rename_axis(column)
        .reset_index(name="count")
    )
    by_location = by_location.sort_values(
        ["count", column], ascending=[False, True]
    )

    return [
        {key: r[column], "count": int(r["count"])}
        for _, r in by_location.iterrows()
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

        start_date = body.get("start_date")
        end_date = body.get("end_date")

        valid_dates, start, end = validate_date_pair(
            start_date, end_date
        )

        if not valid_dates:
            return _response(
                400,
                {"error": "Invalid date format or start_date after end_date"},
            )

        org_df, states_df, countries_df = load_data()
        try:
            country_id = resolve_country(body.get("country"), countries_df)
        except ValueError as e:
            return _response(400, {"error": str(e)})

        org_df = org_df.merge(
            states_df[["state_id", "country_id", "state_name"]],
            on="state_id", how="left",
        ).merge(
            countries_df[["country_id", "country_code"]],
            on="country_id", how="left",
        )
        country_filtered = country_id is not None
        if country_filtered:
            org_df = org_df[org_df["country_id"] == country_id]

        # Keep the country's full history for cumulative totals; window both charts.
        time_keys = (
            ["Custom"] if start is not None else ["7D", "30D", "1Y", "All"]
        )
        response = {}
        for time_key in time_keys:
            if time_key == "Custom":
                window_df = filter_by_range(org_df, start, end)
            else:
                window_df = filter_by_window(org_df, time_key)

            response[time_key] = {
                "growth_trend": build_growth_trend(
                    org_df, window_df, get_grouping_format(time_key)
                ),
                "organizations_by_location": build_orgs_by_location(
                    window_df, country_filtered
                ),
            }

        return _response(200, response)

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
