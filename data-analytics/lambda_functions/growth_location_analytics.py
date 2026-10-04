import json
import os
from datetime import datetime

import pandas as pd


DATA_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "mock-data-generation",
    )
)


def parse_event(event):
    if not event:
        return {}

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, dict):
        return body

    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}

    return {}


def response(status, data):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(data),
    }


def load_data():
    organizations = pd.read_csv(
        os.path.join(DATA_DIR, "organizations.csv")
    )
    states = pd.read_csv(
        os.path.join(DATA_DIR, "states.csv")
    )
    countries = pd.read_csv(
        os.path.join(DATA_DIR, "countries.csv")
    )

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"],
        errors="coerce",
    )

    organizations = organizations.dropna(
        subset=["created_at"]
    ).copy()

    organizations["is_collaborator"] = (
        organizations["is_collaborator"]
        .astype(str)
        .str.lower()
        .str.strip()
        .isin(["true", "1", "yes", "y"])
    )

    location_data = organizations.merge(
        states[["state_id", "country_id"]],
        on="state_id",
        how="left",
    )

    location_data = location_data.merge(
        countries[["country_id", "country_code"]],
        on="country_id",
        how="left",
    )

    return organizations, location_data


def validate_range(start, end, name):
    if start is None and end is None:
        return None, None

    if not start or not end:
        raise ValueError(
            f"Both {name} start and end dates are required"
        )

    try:
        start = pd.Timestamp(
            datetime.strptime(start, "%Y-%m-%d")
        )
        end = pd.Timestamp(
            datetime.strptime(end, "%Y-%m-%d")
        )
    except (TypeError, ValueError):
        raise ValueError(
            f"{name} dates must use YYYY-MM-DD format"
        )

    if start > end:
        raise ValueError(
            f"{name} start date cannot be after end date"
        )

    return start, end


def filter_dates(data, start=None, end=None):
    result = data

    if start is not None:
        result = result[result["created_at"] >= start]

    if end is not None:
        result = result[
            result["created_at"]
            < end + pd.Timedelta(days=1)
        ]

    return result.copy()


def growth_trend(
    organizations,
    start=None,
    end=None,
    grouping="day",
):
    current = filter_dates(
        organizations,
        start,
        end,
    )

    if current.empty:
        return {
            "total_organizations": [],
            "collaborators": [],
        }

    if grouping == "day":
        current["period"] = (
            current["created_at"]
            .dt.strftime("%Y-%m-%d")
        )
    else:
        current["period"] = (
            current["created_at"]
            .dt.strftime("%Y-%m")
        )

    counts = (
        current.groupby("period")
        .size()
        .sort_index()
    )

    # Organizations created before this range still count toward
    # the absolute running total.
    before_range = 0

    if start is not None:
        before_range = int(
            (
                organizations["created_at"] < start
            ).sum()
        )

    running = before_range
    totals = []

    for period, count in counts.items():
        running += int(count)

        totals.append({
            "period": period,
            "count": running,
        })

    collaborator_counts = (
        current[current["is_collaborator"]]
        .groupby("period")
        .size()
        .to_dict()
    )

    collaborators = [
        {
            "period": period,
            "count": int(
                collaborator_counts.get(period, 0)
            ),
        }
        for period in counts.index
    ]

    return {
        "total_organizations": totals,
        "collaborators": collaborators,
    }


def location_counts(
    location_data,
    start=None,
    end=None,
):
    current = filter_dates(
        location_data,
        start,
        end,
    )

    current = current.dropna(
        subset=["country_code"]
    )

    if current.empty:
        return []

    counts = (
        current.groupby("country_code")
        .size()
        .reset_index(name="count")
        .sort_values(
            ["count", "country_code"],
            ascending=[False, True],
        )
        .head(4)
    )

    return [
        {
            "country": row["country_code"],
            "count": int(row["count"]),
        }
        for _, row in counts.iterrows()
    ]


def fixed_range(name, today):
    if name == "7D":
        return (
            today - pd.Timedelta(days=6),
            today,
            "day",
        )

    if name == "30D":
        return (
            today - pd.Timedelta(days=29),
            today,
            "day",
        )

    if name == "1Y":
        return (
            today - pd.DateOffset(years=1),
            today,
            "month",
        )

    return None, today, "month"


def build_bucket(
    organizations,
    location_data,
    start,
    end,
    grouping,
):
    return {
        "growth_trend": growth_trend(
            organizations,
            start,
            end,
            grouping,
        ),
        "organizations_by_location": location_counts(
            location_data,
            start,
            end,
        ),
    }


def lambda_handler(event, context):
    try:
        body = parse_event(event)

        growth_start, growth_end = validate_range(
            body.get("start_date"),
            body.get("end_date"),
            "Growth Custom",
        )

        location_start, location_end = validate_range(
            body.get("location_start_date"),
            body.get("location_end_date"),
            "Location Custom",
        )

        organizations, location_data = load_data()

        today = pd.Timestamp.today().normalize()

        result = {}

        for name in ["7D", "30D", "1Y", "All"]:
            start, end, grouping = fixed_range(
                name,
                today,
            )

            result[name] = build_bucket(
                organizations,
                location_data,
                start,
                end,
                grouping,
            )

        result["Custom"] = {
            "growth_trend": {
                "total_organizations": [],
                "collaborators": [],
            },
            "organizations_by_location": [],
        }

        if growth_start is not None:
            result["Custom"]["growth_trend"] = (
                growth_trend(
                    organizations,
                    growth_start,
                    growth_end,
                    "day",
                )
            )

        if location_start is not None:
            result["Custom"][
                "organizations_by_location"
            ] = location_counts(
                location_data,
                location_start,
                location_end,
            )

        return response(200, result)

    except ValueError as error:
        return response(
            400,
            {"error": str(error)},
        )

    except Exception as error:
        print("ERROR:", error)

        return response(
            500,
            {"error": str(error)},
        )


if __name__ == "__main__":
    tests = [
        ("No custom dates", {}),
        (
            "Growth custom",
            {
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
            },
        ),
        (
            "Location custom",
            {
                "location_start_date": "2025-01-01",
                "location_end_date": "2025-12-31",
            },
        ),
        (
            "Both custom ranges",
            {
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "location_start_date": "2025-01-01",
                "location_end_date": "2025-12-31",
            },
        ),
        (
            "Invalid date",
            {
                "start_date": "bad-date",
                "end_date": "2026-06-30",
            },
        ),
        (
            "Start after end",
            {
                "start_date": "2026-06-30",
                "end_date": "2026-01-01",
            },
        ),
    ]

    for name, event in tests:
        print("\n" + "=" * 60)
        print(name)

        result = lambda_handler(event, None)

        print("Status:", result["statusCode"])
        print(
            json.dumps(
                json.loads(result["body"]),
                indent=2,
            )
        )