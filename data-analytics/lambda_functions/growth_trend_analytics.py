import json
import logging
import os
import re
from datetime import datetime

import pandas as pd


logger = logging.getLogger()
logger.setLevel(logging.INFO)

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "mock-data-generation",
)

FIXED_BUCKETS = ["7D", "30D", "1Y", "All"]


def load_data():
    org_df = pd.read_csv(
        os.path.join(DATA_DIR, "organizations.csv"),
        dtype={"state_id": str},
    )
    states_df = pd.read_csv(
        os.path.join(DATA_DIR, "states.csv"),
        dtype={"state_id": str},
    )
    countries_df = pd.read_csv(
        os.path.join(DATA_DIR, "countries.csv")
    )

    org_df["created_at"] = pd.to_datetime(
        org_df["created_at"], utc=True, errors="coerce"
    ).dt.tz_localize(None)
    org_df = org_df.dropna(subset=["created_at"]).copy()

    org_df["is_collaborator"] = org_df["is_collaborator"].map(
        {
            "TRUE": True,
            "FALSE": False,
            True: True,
            False: False,
        }
    )

    states_df["country_id"] = pd.to_numeric(
        states_df["country_id"], errors="coerce"
    )
    countries_df["country_id"] = pd.to_numeric(
        countries_df["country_id"], errors="coerce"
    )

    return org_df, states_df, countries_df


def _normalize_country(value):
    return re.sub(r"\s+", " ", str(value).strip().replace("_", " ")).upper()


def apply_country_filter(org_df, states_df, countries_df, country):
    """Filter organizations by country name or code."""
    if country is not None and not isinstance(country, str):
        raise ValueError("country must be a string")

    if country is None or country.strip() == "" or country.strip().upper() == "ALL":
        return org_df.copy()

    target = _normalize_country(country)

    country_matches = countries_df[
        countries_df["country_code"].fillna("").map(_normalize_country).eq(target)
        | countries_df["country_name"].fillna("").map(_normalize_country).eq(target)
    ]

    if country_matches.empty:
        raise LookupError("Unknown country")

    country_ids = country_matches["country_id"].dropna().unique()
    state_ids = states_df.loc[
        states_df["country_id"].isin(country_ids), "state_id"
    ]

    return org_df[org_df["state_id"].isin(state_ids)].copy()


def _is_blank(value):
    return value is None or (
        isinstance(value, str) and value.strip() == ""
    )


def _parse_date(value):
    if not isinstance(value, str):
        return None

    value = value.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None

    try:
        return pd.Timestamp(datetime.strptime(value, "%Y-%m-%d"))
    except ValueError:
        return None


def validate_date_pair(start, end):
    """Return validity and parsed dates; blank/null pairs mean no custom range."""
    start_blank = _is_blank(start)
    end_blank = _is_blank(end)

    if start_blank and end_blank:
        return True, None, None

    if start_blank or end_blank:
        return False, None, None

    start_dt = _parse_date(start)
    end_dt = _parse_date(end)

    if start_dt is None or end_dt is None or start_dt > end_dt:
        return False, None, None

    return True, start_dt, end_dt


def filter_by_range(df, start, end):
    """Include both the start date and the entire end date."""
    return df[
        (df["created_at"] >= start)
        & (df["created_at"] < end + pd.Timedelta(days=1))
    ]


def filter_by_window(df, time_key):
    today = pd.Timestamp.now().normalize()

    if time_key == "7D":
        start = today - pd.Timedelta(days=6)
        return df[df["created_at"] >= start]
    if time_key == "30D":
        start = today - pd.Timedelta(days=29)
        return df[df["created_at"] >= start]
    if time_key == "1Y":
        start = (today - pd.DateOffset(months=11)).replace(day=1)
        return df[df["created_at"] >= start]
    if time_key == "All":
        return df

    return df


def get_grouping_format(time_key):
    return "day" if time_key in ("7D", "30D", "Custom") else "month"


def apply_period(df, grouping):
    df = df.copy()
    date_format = "%Y-%m-%d" if grouping == "day" else "%Y-%m"
    df["period"] = df["created_at"].dt.strftime(date_format)
    return df


def build_growth_trend(full_df, window_df, grouping):
    if window_df.empty:
        return {"total_organizations": [], "collaborators": []}

    # Cumulative counts use all available history for the selected country.
    full_sorted = apply_period(
        full_df.sort_values("created_at"), grouping
    )
    full_cumulative = (
        full_sorted.groupby("period").size().reset_index(name="count")
    )
    full_cumulative["count"] = full_cumulative["count"].cumsum()

    window_sorted = apply_period(window_df, grouping)
    window_periods = set(window_sorted["period"].unique())

    total_orgs = [
        {"period": row["period"], "count": int(row["count"])}
        for _, row in full_cumulative.iterrows()
        if row["period"] in window_periods
    ]

    collaborators = window_sorted[
        window_sorted["is_collaborator"] == True
    ]
    collaborator_counts = collaborators.groupby("period").size().to_dict()

    collab_list = [
        {"period": period, "count": int(collaborator_counts.get(period, 0))}
        for period in sorted(window_periods)
    ]

    return {
        "total_organizations": total_orgs,
        "collaborators": collab_list,
    }


def build_orgs_by_location(window_df, states_df, countries_df, country=None):
    if window_df.empty:
        return []

    merged = window_df.merge(
        states_df[["state_id", "state_name", "country_id"]],
        on="state_id",
        how="left",
    )
    merged = merged.merge(
        countries_df[["country_id", "country_code"]],
        on="country_id",
        how="left",
    )

    if country is not None and country.strip() != "" and country.strip().upper() != "ALL":
        counts = (
            merged.dropna(subset=["state_name"])
            .groupby("state_name")
            .size()
            .reset_index(name="count")
            .rename(columns={"state_name": "state"})
        )
        counts["_sort_name"] = counts["state"].str.casefold()
        counts = counts.sort_values(
            ["count", "_sort_name"],
            ascending=[False, True],
        )
        return [
            {"state": row["state"], "count": int(row["count"])}
            for _, row in counts.iterrows()
        ]

    merged["country_code"] = merged["country_code"].fillna("Unknown")
    counts = (
        merged.groupby("country_code")
        .size()
        .reset_index(name="count")
    )
    counts["_sort_name"] = counts["country_code"].str.casefold()
    counts = counts.sort_values(
        ["count", "_sort_name"],
        ascending=[False, True],
    )

    return [
        {"country": row["country_code"], "count": int(row["count"])}
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


def _parse_event(event):
    """Accept a direct request dictionary or an API Gateway body."""
    if event is None:
        return {}, None
    if not isinstance(event, dict):
        return None, "Request body must be a JSON object"

    raw_body = event.get("body")

    if isinstance(raw_body, str):
        if not raw_body.strip():
            body = {}
        else:
            try:
                body = json.loads(raw_body)
            except json.JSONDecodeError:
                return None, "Invalid JSON in request body"
    elif isinstance(raw_body, dict):
        body = raw_body
    elif raw_body is None:
        body = event
    else:
        return None, "Request body must be a JSON object"

    if not isinstance(body, dict):
        return None, "Request body must be a JSON object"

    return body, None


def lambda_handler(event, context):
    try:
        body, parse_error = _parse_event(event)
        if parse_error:
            return _response(400, {"error": parse_error})

        country = body.get("country")
        if country is not None and not isinstance(country, str):
            return _response(400, {"error": "country must be a string"})

        valid_dates, start_date, end_date = validate_date_pair(
            body.get("start_date"), body.get("end_date")
        )
        if not valid_dates:
            return _response(
                400,
                {
                    "error": (
                        "Invalid date format or "
                        "start_date after end_date"
                    )
                },
            )

        org_df, states_df, countries_df = load_data()

        try:
            filtered_df = apply_country_filter(
                org_df, states_df, countries_df, country
            )
        except ValueError:
            return _response(400, {"error": "country must be a string"})
        except LookupError:
            return _response(400, {"error": "Unknown country"})

        has_custom_range = start_date is not None and end_date is not None

        if has_custom_range:
            window_df = filter_by_range(
                filtered_df, start_date, end_date
            )
            response = {
                "Custom": {
                    "growth_trend": build_growth_trend(
                        filtered_df, window_df, "day"
                    ),
                    "organizations_by_location": build_orgs_by_location(
                        window_df, states_df, countries_df, country
                    ),
                }
            }
        else:
            response = {}
            for time_key in FIXED_BUCKETS:
                window_df = filter_by_window(filtered_df, time_key)
                grouping = get_grouping_format(time_key)

                response[time_key] = {
                    "growth_trend": build_growth_trend(
                        filtered_df, window_df, grouping
                    ),
                    "organizations_by_location": build_orgs_by_location(
                        window_df, states_df, countries_df, country
                    ),
                }

        return _response(200, response)

    except Exception:
        logger.exception("org-growth-location-analytics error")
        return _response(500, {"error": "Internal server error"})


if __name__ == "__main__":
    result = lambda_handler({}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))
