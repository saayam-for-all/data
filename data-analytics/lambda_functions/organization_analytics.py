"""Organization Analytics API for the Organization Dashboard (issue #228).

Reads organization data from the local mock CSVs under data-analytics/sql/
(no AWS Parameter Store, no live AWS connection) and returns the KPI
summary, growth trend, location/size/rating breakdowns, and
collaborator-vs-contributor and for-profit-vs-non-profit distributions
needed by the three dashboard tabs.
"""

import json
import os

import pandas as pd

SQL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sql")

TIME_WINDOWS = {
    "7D": pd.Timedelta(days=7),
    "30D": pd.Timedelta(days=30),
}

BOOL_MAP = {"TRUE": True, "FALSE": False, True: True, False: False}


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": body,
    }


def load_organizations(sql_dir=SQL_DIR):
    orgs = pd.read_csv(os.path.join(sql_dir, "organizations.csv"))
    states = pd.read_csv(os.path.join(sql_dir, "state.csv"))

    orgs["created_at"] = pd.to_datetime(orgs["created_at"], errors="coerce")
    orgs["org_rating"] = pd.to_numeric(orgs["org_rating"], errors="coerce")
    orgs["is_collaborator"] = orgs["is_collaborator"].map(BOOL_MAP)

    # is_contributor was recently added to the schema and may not exist in
    # every environment yet (see issue #228) -- default to False if absent.
    if "is_contributor" in orgs.columns:
        orgs["is_contributor"] = orgs["is_contributor"].map(BOOL_MAP)
    else:
        orgs["is_contributor"] = False

    return orgs, states


def filter_by_time(orgs, time_filter, start_date=None, end_date=None):
    if time_filter in TIME_WINDOWS:
        cutoff = pd.Timestamp.now().normalize() - TIME_WINDOWS[time_filter]
        return orgs[orgs["created_at"] >= cutoff]

    if time_filter == "1Y":
        cutoff = pd.Timestamp.now().normalize() - pd.DateOffset(years=1)
        return orgs[orgs["created_at"] >= cutoff]

    if time_filter == "CUSTOM" and start_date and end_date:
        start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
        return orgs[(orgs["created_at"] >= start) & (orgs["created_at"] <= end)]

    # "ALL", unrecognized filters, or an incomplete CUSTOM range all fall
    # back to the full dataset rather than erroring out.
    return orgs


def filter_by_region_and_type(orgs, states, region=None, organization_type=None):
    if region and region != "ALL":
        state_ids = states.loc[
            states["state_name"].str.casefold() == region.casefold(), "state_id"
        ]
        if not state_ids.empty:
            orgs = orgs[orgs["state_id"].isin(state_ids)]
        else:
            orgs = orgs[orgs["state_id"].str.casefold() == region.casefold()]

    if organization_type and organization_type != "ALL":
        normalized_type = orgs["org_type"].str.casefold().str.replace("-", "_", regex=False)
        orgs = orgs[normalized_type == organization_type.casefold()]

    return orgs


def period_key(timestamps, group_by):
    if group_by == "daily":
        return timestamps.dt.strftime("%Y-%m-%d")
    if group_by == "weekly":
        return timestamps.dt.to_period("W-SUN").apply(lambda p: p.start_time.strftime("%Y-%m-%d"))
    if group_by == "yearly":
        return timestamps.dt.strftime("%Y")
    return timestamps.dt.strftime("%Y-%m")  # monthly (default)


def summary(orgs):
    rated = orgs["org_rating"].dropna()
    return {
        "total_organizations": int(len(orgs)),
        "total_collaborators": int(orgs["is_collaborator"].sum()),
        "total_contributors": int(orgs["is_contributor"].sum()),
        "average_org_rating": round(float(rated.mean()), 2) if not rated.empty else 0,
    }


def growth_trend(orgs, group_by):
    if orgs.empty:
        return []

    working = orgs.copy()
    working["period"] = period_key(working["created_at"], group_by)

    by_period = (
        working.groupby("period")
        .agg(new_orgs=("org_id", "count"), new_collaborators=("is_collaborator", "sum"))
        .sort_index()
    )
    running = by_period.cumsum()

    return [
        {
            "period": period,
            "total_organizations": int(row["new_orgs"]),
            "total_collaborators": int(row["new_collaborators"]),
        }
        for period, row in running.iterrows()
    ]


def organizations_by_location(orgs, states):
    if orgs.empty:
        return []

    merged = orgs.merge(states[["state_id", "state_name"]], on="state_id", how="left")
    merged["state_name"] = merged["state_name"].fillna("Unknown")

    counts = merged.groupby(["state_id", "state_name"]).size().sort_values(ascending=False)
    total = len(orgs)

    return [
        {
            "state_id": state_id,
            "state_name": state_name,
            "organization_count": int(count),
            "percentage": round(count / total * 100, 1),
        }
        for (state_id, state_name), count in counts.items()
    ]


def organizations_by_size(orgs):
    if orgs.empty:
        return []

    counts = orgs.groupby("org_size").size().sort_values(ascending=False)
    return [
        {"org_size": size, "organization_count": int(count)}
        for size, count in counts.items()
    ]


def collaborator_vs_contributor(orgs):
    if orgs.empty:
        return []

    total = len(orgs)
    collaborators = int(orgs["is_collaborator"].sum())
    contributors = int(orgs["is_contributor"].sum())

    return [
        {
            "type": "collaborator",
            "organization_count": collaborators,
            "percentage": round(collaborators / total * 100, 1),
        },
        {
            "type": "contributor",
            "organization_count": contributors,
            "percentage": round(contributors / total * 100, 1),
        },
    ]


def rating_distribution(orgs):
    rated = orgs[orgs["org_rating"].notna()]
    if rated.empty:
        return []

    counts = rated.groupby("org_rating").size().sort_index()
    return [
        {"rating": int(rating), "organization_count": int(count)}
        for rating, count in counts.items()
    ]


def organization_type_distribution(orgs, group_by):
    if orgs.empty:
        return []

    working = orgs.copy()
    working["period"] = period_key(working["created_at"], group_by)
    working["normalized_type"] = working["org_type"].str.casefold().str.replace("-", "_", regex=False)

    pivot = working.groupby(["period", "normalized_type"]).size().unstack(fill_value=0).sort_index()

    results = []
    for period, row in pivot.iterrows():
        for_profit = int(row.get("for_profit", 0))
        non_profit = int(row.get("non_profit", 0))
        results.append(
            {
                "period": period,
                "for_profit": for_profit,
                "non_profit": non_profit,
                "total": for_profit + non_profit,
            }
        )
    return results


def build_analytics(orgs, states, params):
    time_filter = params.get("time_filter", "ALL")
    start_date = params.get("start_date")
    end_date = params.get("end_date")
    group_by = params.get("group_by", "monthly")
    region = params.get("region", "ALL")
    organization_type = params.get("organization_type", "ALL")

    filtered = filter_by_time(orgs, time_filter, start_date, end_date)
    filtered = filter_by_region_and_type(filtered, states, region, organization_type)

    return {
        "summary": summary(filtered),
        "growth_trend": growth_trend(filtered, group_by),
        "organizations_by_location": organizations_by_location(filtered, states),
        "organizations_by_size": organizations_by_size(filtered),
        "collaborator_vs_contributor": collaborator_vs_contributor(filtered),
        "rating_distribution": rating_distribution(filtered),
        "organization_type_distribution": organization_type_distribution(filtered, group_by),
    }


def lambda_handler(event, context):
    params = event
    if isinstance(event.get("body"), str):
        params = json.loads(event["body"])

    try:
        orgs, states = load_organizations()
        return build_response(200, build_analytics(orgs, states, params))
    except Exception as e:  # noqa: BLE001 - surface any failure as a 500, don't crash the handler
        print(f"organization_analytics failed: {e}")
        return build_response(
            500,
            {
                "summary": {
                    "total_organizations": 0,
                    "total_collaborators": 0,
                    "total_contributors": 0,
                    "average_org_rating": 0,
                },
                "growth_trend": [],
                "organizations_by_location": [],
                "organizations_by_size": [],
                "collaborator_vs_contributor": [],
                "rating_distribution": [],
                "organization_type_distribution": [],
            },
        )


if __name__ == "__main__":
    print(json.dumps(lambda_handler({"time_filter": "ALL", "group_by": "monthly"}, None), indent=2))
