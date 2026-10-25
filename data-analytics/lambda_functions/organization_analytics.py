"""
Organization Analytics API (mock-data version)

Provides the data backing the Saayam "Organization Dashboard":
  1. Organization Overview Dashboard    -> get_organization_overview()
  2. Organization Performance Dashboard -> get_organization_performance()

--------------------------------------------------------------------------
Why this doesn't connect to a database
--------------------------------------------------------------------------
Per review feedback on issue #228, this implementation never touches AWS,
SSM, or the real Postgres database. It loads the sample data provided for
this task (data-analytics/sql/organizations.csv) and computes every
metric locally with pandas, reproducing the same filters and response
shape the real SQL-backed version will eventually produce.

Mock data schema (data-analytics/sql/organizations.csv):
  org_id, org_name, street, city_name, state_id, zip_code, mission,
  web_url, phone, email, org_type, org_size, org_rating, is_collaborator,
  is_contributor, created_at, last_updated_at

Notes on real values seen in the mock file:
  - org_type:  "Non-Profit" | "For-profit"
  - org_size:  "Small" | "Medium" | "Large"
  - org_rating: 1-5 (may be null on the real table; handled defensively)
  - is_collaborator / is_contributor: TRUE / FALSE
  - There is no separate state reference table in the current mock data
    set, so "state" in the location breakdown is simply the org's own
    state_id (a 2-letter code) rather than a joined state_name.
"""

import json
import os

import pandas as pd

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MOCK_DATA_DIR = os.environ.get("MOCK_DATA_DIR", os.path.join(BASE_DIR, "..", "sql"))
ORGANIZATIONS_CSV = os.path.join(MOCK_DATA_DIR, "organizations.csv")

VALID_TIME_FILTERS = {"7D", "30D", "1Y", "ALL", "CUSTOM"}
GROUP_BY_PANDAS_FREQ = {
    "daily": "D",
    "weekly": "W",
    "monthly": "MS",
    "yearly": "YS",
}
GROUP_BY_FORMAT = {
    "daily": "%Y-%m-%d",
    "weekly": "%Y-%m-%d",
    "monthly": "%Y-%m",
    "yearly": "%Y",
}

TOP_N_DEFAULT = 10


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def parse_event_body(event):
    if not event:
        return {}
    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body, dict):
        return body
    return {}


def get_default_overview_response():
    return {
        "organization_overview": {
            "summary": {
                "total_organizations": 0,
                "non_profit_organizations": 0,
                "for_profit_organizations": 0,
                "collaborator_organizations": 0,
                "non_collaborator_organizations": 0,
                "contributor_organizations": 0,
                "non_contributor_organizations": 0,
            },
            "organization_activity_trend": [],
            "organizations_by_type": [],
            "organizations_by_size": [],
            "organizations_by_location": [],
            "collaborator_distribution": [],
            "contributor_distribution": [],
        }
    }


def get_default_performance_response():
    return {
        "organization_performance": {
            "summary": {
                "average_rating": 0,
                "rated_organizations": 0,
                "unrated_organizations": 0,
                "five_star_organizations": 0,
            },
            "rating_distribution": [],
            "top_rated_organizations": [],
            "top_collaborator_organizations": [],
            "top_contributor_organizations": [],
            "ratings_by_organization_type": [],
            "ratings_by_organization_size": [],
        }
    }


# ---------------------------------------------------------------------------
# Mock data loading
# ---------------------------------------------------------------------------

def load_mock_data(organizations_csv=ORGANIZATIONS_CSV):
    """
    Loads the mock organizations table from CSV into a DataFrame, doing the
    light type coercion that would otherwise come "for free" from Postgres
    column types (created_at -> datetime, org_rating -> nullable numeric,
    is_collaborator/is_contributor -> bool).
    """
    df = pd.read_csv(organizations_csv)

    df["created_at"] = pd.to_datetime(df["created_at"])
    df["org_rating"] = pd.to_numeric(df["org_rating"], errors="coerce")

    for bool_col in ("is_collaborator", "is_contributor"):
        if bool_col in df.columns:
            df[bool_col] = df[bool_col].map(
                lambda v: v if isinstance(v, bool) else str(v).strip().upper() == "TRUE"
            )
        else:
            # Isolated fallback in case a future/real data source is missing
            # this column (e.g. is_contributor before its DB migration).
            df[bool_col] = pd.NA

    return df


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------

def apply_date_filter(df, time_filter, start_date=None, end_date=None, column="created_at"):
    time_filter = (time_filter or "ALL").upper()
    now = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)  # end of "today"

    if time_filter == "CUSTOM" and start_date and end_date:
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        return df[(df[column] >= start) & (df[column] <= end)]
    elif time_filter == "7D":
        return df[df[column] >= now - pd.Timedelta(days=7)]
    elif time_filter == "30D":
        return df[df[column] >= now - pd.Timedelta(days=30)]
    elif time_filter == "1Y":
        return df[df[column] >= now - pd.DateOffset(years=1)]
    else:
        # "ALL" or unrecognized -> no date filter
        return df


def apply_common_filters(df, filters):
    """
    org_type, org_size, state_id, city_name, org_rating, is_collaborator,
    time_filter/start_date/end_date.

    `is_contributor` is intentionally left out here and applied only
    inside the isolated contributor fetch functions below, so a data
    source missing that column only degrades the contributor-specific
    pieces instead of failing every metric.
    """
    result = df

    org_type = filters.get("org_type")
    if org_type:
        result = result[result["org_type"] == org_type]

    org_size = filters.get("org_size")
    if org_size:
        result = result[result["org_size"] == org_size]

    state_id = filters.get("state_id")
    if state_id:
        result = result[result["state_id"] == state_id]

    city_name = filters.get("city_name")
    if city_name:
        result = result[result["city_name"] == city_name]

    org_rating = filters.get("org_rating")
    if org_rating is not None:
        result = result[result["org_rating"] == org_rating]

    is_collaborator = filters.get("is_collaborator")
    if is_collaborator is not None:
        result = result[result["is_collaborator"] == bool(is_collaborator)]

    result = apply_date_filter(
        result,
        filters.get("time_filter", "ALL"),
        filters.get("start_date"),
        filters.get("end_date"),
    )

    return result


def get_group_by_unit(group_by):
    group_by = (group_by or "daily").lower()
    if group_by not in GROUP_BY_PANDAS_FREQ:
        group_by = "daily"
    return GROUP_BY_PANDAS_FREQ[group_by], GROUP_BY_FORMAT[group_by]


# ---------------------------------------------------------------------------
# Dashboard 1: Organization Overview
# ---------------------------------------------------------------------------

def fetch_overview_summary(df, filters):
    filtered = apply_common_filters(df, filters)
    return {
        "total_organizations": int(len(filtered)),
        "non_profit_organizations": int((filtered["org_type"] == "Non-Profit").sum()),
        "for_profit_organizations": int((filtered["org_type"] == "For-profit").sum()),
        "collaborator_organizations": int((filtered["is_collaborator"] == True).sum()),  # noqa: E712
        "non_collaborator_organizations": int((filtered["is_collaborator"] != True).sum()),  # noqa: E712
    }


def fetch_contributor_summary(df, filters):
    """Isolated so a data source missing is_contributor just zeroes this out."""
    filtered = apply_common_filters(df, filters)
    if "is_contributor" not in filtered.columns or filtered["is_contributor"].isna().all():
        return {"contributor_organizations": 0, "non_contributor_organizations": 0}
    return {
        "contributor_organizations": int((filtered["is_contributor"] == True).sum()),  # noqa: E712
        "non_contributor_organizations": int((filtered["is_contributor"] != True).sum()),  # noqa: E712
    }


def fetch_organization_activity_trend(df, filters):
    filtered = apply_common_filters(df, filters)
    freq, fmt = get_group_by_unit(filters.get("group_by"))

    if filtered.empty:
        return []

    grouped = (
        filtered.set_index("created_at")
        .resample(freq)
        .size()
        .reset_index(name="count")
    )
    grouped = grouped[grouped["count"] > 0]
    return [
        {"period": row["created_at"].strftime(fmt), "count": int(row["count"])}
        for _, row in grouped.iterrows()
    ]


def fetch_organizations_by_type(df, filters):
    filtered = apply_common_filters(df, filters)
    counts = filtered["org_type"].fillna("unknown").value_counts()
    return [
        {"org_type": org_type, "count": int(count)}
        for org_type, count in counts.sort_values(ascending=False).items()
    ]


def fetch_organizations_by_size(df, filters):
    filtered = apply_common_filters(df, filters)
    counts = filtered["org_size"].fillna("unknown").value_counts()
    return [
        {"org_size": org_size, "count": int(count)}
        for org_size, count in counts.sort_values(ascending=False).items()
    ]


def fetch_organizations_by_location(df, filters):
    filtered = apply_common_filters(df, filters).copy()
    filtered["state_id"] = filtered["state_id"].fillna("Unknown")
    filtered["city_name"] = filtered["city_name"].fillna("Unknown")
    grouped = (
        filtered.groupby(["state_id", "city_name"])
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    return [
        {"state": row["state_id"], "city": row["city_name"], "count": int(row["count"])}
        for _, row in grouped.iterrows()
    ]


def fetch_collaborator_distribution(df, filters):
    filtered = apply_common_filters(df, filters)
    category = filtered["is_collaborator"].map(
        lambda v: "collaborator" if v is True else "non_collaborator"
    )
    counts = category.value_counts()
    return [
        {"category": category, "count": int(count)}
        for category, count in counts.sort_index().items()
    ]


def fetch_contributor_distribution(df, filters):
    """Isolated for the same is_contributor reason as fetch_contributor_summary."""
    filtered = apply_common_filters(df, filters)
    if "is_contributor" not in filtered.columns or filtered["is_contributor"].isna().all():
        return []
    category = filtered["is_contributor"].map(
        lambda v: "contributor" if v is True else "non_contributor"
    )
    counts = category.value_counts()
    return [
        {"category": category, "count": int(count)}
        for category, count in counts.sort_index().items()
    ]


def get_organization_overview(df, filters):
    response = get_default_overview_response()["organization_overview"]

    try:
        response["summary"].update(fetch_overview_summary(df, filters))
    except Exception as error:
        print(f"[overview] summary computation failed: {error}")

    try:
        response["summary"].update(fetch_contributor_summary(df, filters))
    except Exception as error:
        print(f"[overview] contributor summary computation failed: {error}")

    try:
        response["organization_activity_trend"] = fetch_organization_activity_trend(df, filters)
    except Exception as error:
        print(f"[overview] activity trend computation failed: {error}")

    try:
        response["organizations_by_type"] = fetch_organizations_by_type(df, filters)
    except Exception as error:
        print(f"[overview] organizations_by_type computation failed: {error}")

    try:
        response["organizations_by_size"] = fetch_organizations_by_size(df, filters)
    except Exception as error:
        print(f"[overview] organizations_by_size computation failed: {error}")

    try:
        response["organizations_by_location"] = fetch_organizations_by_location(df, filters)
    except Exception as error:
        print(f"[overview] organizations_by_location computation failed: {error}")

    try:
        response["collaborator_distribution"] = fetch_collaborator_distribution(df, filters)
    except Exception as error:
        print(f"[overview] collaborator_distribution computation failed: {error}")

    try:
        response["contributor_distribution"] = fetch_contributor_distribution(df, filters)
    except Exception as error:
        print(f"[overview] contributor_distribution computation failed: {error}")

    return response


# ---------------------------------------------------------------------------
# Dashboard 2: Organization Performance
# ---------------------------------------------------------------------------

def fetch_performance_summary(df, filters):
    filtered = apply_common_filters(df, filters)
    rated = filtered["org_rating"].dropna()
    return {
        "average_rating": round(float(rated.mean()), 2) if not rated.empty else 0,
        "rated_organizations": int(rated.shape[0]),
        "unrated_organizations": int(filtered["org_rating"].isna().sum()),
        "five_star_organizations": int((filtered["org_rating"] == 5).sum()),
    }


def fetch_rating_distribution(df, filters):
    filtered = apply_common_filters(df, filters)
    counts = filtered["org_rating"].value_counts(dropna=False)
    items = sorted(counts.items(), key=lambda kv: (pd.isna(kv[0]), kv[0]))  # NULLS LAST
    return [
        {"rating": (None if pd.isna(rating) else int(rating)), "count": int(count)}
        for rating, count in items
    ]


def _row_to_org_dict(row):
    return {
        "org_id": row["org_id"],
        "org_name": row["org_name"],
        "org_type": row["org_type"],
        "org_size": row["org_size"],
        "org_rating": (None if pd.isna(row["org_rating"]) else float(row["org_rating"])),
        "city_name": row["city_name"],
        "state_id": row["state_id"],
    }


def fetch_top_rated_organizations(df, filters, limit=TOP_N_DEFAULT):
    filtered = apply_common_filters(df, filters)
    filtered = filtered[filtered["org_rating"].notna()]
    filtered = filtered.sort_values(["org_rating", "org_name"], ascending=[False, True])
    return [_row_to_org_dict(row) for _, row in filtered.head(limit).iterrows()]


def fetch_top_collaborator_organizations(df, filters, limit=TOP_N_DEFAULT):
    filtered = apply_common_filters(df, filters)
    filtered = filtered[filtered["is_collaborator"] == True]  # noqa: E712
    filtered = filtered.sort_values(
        ["org_rating", "org_name"], ascending=[False, True], na_position="last"
    )
    return [_row_to_org_dict(row) for _, row in filtered.head(limit).iterrows()]


def fetch_top_contributor_organizations(df, filters, limit=TOP_N_DEFAULT):
    """Isolated: relies on is_contributor, which may not exist on the real table yet."""
    filtered = apply_common_filters(df, filters)
    if "is_contributor" not in filtered.columns:
        return []
    filtered = filtered[filtered["is_contributor"] == True]  # noqa: E712
    filtered = filtered.sort_values(
        ["org_rating", "org_name"], ascending=[False, True], na_position="last"
    )
    return [_row_to_org_dict(row) for _, row in filtered.head(limit).iterrows()]


def fetch_ratings_by_organization_type(df, filters):
    filtered = apply_common_filters(df, filters)
    grouped = filtered.groupby(filtered["org_type"].fillna("unknown")).agg(
        average_rating=("org_rating", "mean"),
        rated_count=("org_rating", "count"),
    )
    grouped = grouped.sort_values("average_rating", ascending=False, na_position="last")
    return [
        {
            "org_type": org_type,
            "average_rating": round(float(row["average_rating"]), 2) if pd.notna(row["average_rating"]) else 0,
            "rated_count": int(row["rated_count"]),
        }
        for org_type, row in grouped.iterrows()
    ]


def fetch_ratings_by_organization_size(df, filters):
    filtered = apply_common_filters(df, filters)
    grouped = filtered.groupby(filtered["org_size"].fillna("unknown")).agg(
        average_rating=("org_rating", "mean"),
        rated_count=("org_rating", "count"),
    )
    grouped = grouped.sort_values("average_rating", ascending=False, na_position="last")
    return [
        {
            "org_size": org_size,
            "average_rating": round(float(row["average_rating"]), 2) if pd.notna(row["average_rating"]) else 0,
            "rated_count": int(row["rated_count"]),
        }
        for org_size, row in grouped.iterrows()
    ]


def get_organization_performance(df, filters):
    response = get_default_performance_response()["organization_performance"]

    try:
        response["summary"].update(fetch_performance_summary(df, filters))
    except Exception as error:
        print(f"[performance] summary computation failed: {error}")

    try:
        response["rating_distribution"] = fetch_rating_distribution(df, filters)
    except Exception as error:
        print(f"[performance] rating_distribution computation failed: {error}")

    try:
        response["top_rated_organizations"] = fetch_top_rated_organizations(df, filters)
    except Exception as error:
        print(f"[performance] top_rated_organizations computation failed: {error}")

    try:
        response["top_collaborator_organizations"] = fetch_top_collaborator_organizations(df, filters)
    except Exception as error:
        print(f"[performance] top_collaborator_organizations computation failed: {error}")

    try:
        response["top_contributor_organizations"] = fetch_top_contributor_organizations(df, filters)
    except Exception as error:
        print(f"[performance] top_contributor_organizations computation failed: {error}")

    try:
        response["ratings_by_organization_type"] = fetch_ratings_by_organization_type(df, filters)
    except Exception as error:
        print(f"[performance] ratings_by_organization_type computation failed: {error}")

    try:
        response["ratings_by_organization_size"] = fetch_ratings_by_organization_size(df, filters)
    except Exception as error:
        print(f"[performance] ratings_by_organization_size computation failed: {error}")

    return response


# ---------------------------------------------------------------------------
# Handlers
#
# These load the mock CSV on each call instead of connecting to AWS/SSM/
# Postgres. Swapping the data-loading layer back to a real DB connection
# later (once this is approved and a real DB is wired up) is a small,
# isolated change contained to load_mock_data().
# ---------------------------------------------------------------------------

def lambda_handler(event, context=None):
    filters = parse_event_body(event)
    dashboard_type = (filters.get("dashboard_type") or "overview").lower()

    response_body = {}
    if dashboard_type in ("overview", "both"):
        response_body.update(get_default_overview_response())
    if dashboard_type in ("performance", "both"):
        response_body.update(get_default_performance_response())
    if dashboard_type not in ("overview", "performance", "both"):
        return build_response(400, {
            "error": "Invalid dashboard_type. Expected 'overview', 'performance', or 'both'."
        })

    try:
        org_df = load_mock_data()

        if dashboard_type in ("overview", "both"):
            response_body["organization_overview"] = get_organization_overview(org_df, filters)

        if dashboard_type in ("performance", "both"):
            response_body["organization_performance"] = get_organization_performance(org_df, filters)

        return build_response(200, response_body)

    except Exception as error:
        print(f"Mock data load failed: {error}")
        return build_response(500, response_body)


def overview_lambda_handler(event, context=None):
    filters = parse_event_body(event)
    filters["dashboard_type"] = "overview"
    return lambda_handler({"body": json.dumps(filters, default=str)}, context)


def performance_lambda_handler(event, context=None):
    filters = parse_event_body(event)
    filters["dashboard_type"] = "performance"
    return lambda_handler({"body": json.dumps(filters, default=str)}, context)
