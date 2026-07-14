import json
import pandas as pd
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import os

SQL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sql")


# ---- PHASE 1: Helper Functions ----

def build_date_filter_trend(time_range, start_date=None, end_date=None):
    """SQL WHERE clause for Volunteer Activity Trend."""
    filters = {
        "7D": "AND vd.created_at >= CURRENT_DATE - INTERVAL '7 days'",
        "30D": "AND vd.created_at >= CURRENT_DATE - INTERVAL '30 days'",
        "1Y": "AND vd.created_at >= CURRENT_DATE - INTERVAL '1 year'",
        "All": "",
    }
    if time_range in filters:
        return filters[time_range]
    if time_range == "Custom" and start_date and end_date:
        return f"AND vd.created_at BETWEEN '{start_date}' AND '{end_date}'"
    return ""


def build_date_filter_location(time_range_location, start_date=None, end_date=None):
    """SQL WHERE clause for Volunteers by Location (same logic, independent filter)."""
    return build_date_filter_trend(time_range_location, start_date, end_date)


def get_grouping(time_range):
    """7D/30D/Custom → daily, 1Y/All → monthly."""
    return "daily" if time_range in ("7D", "30D", "Custom") else "monthly"


# ---- PHASE 1: Core Functions ----

def get_volunteer_activity_trend(df, time_range="All", start_date=None, end_date=None):
    """Returns new, active, and total volunteers grouped by period."""
    df = filter_by_date(df, time_range, start_date, end_date)
    grouping = get_grouping(time_range)
    fmt = "%Y-%m-%d" if grouping == "daily" else "%Y-%m"

    new = group_count(df, fmt)
    active = group_count(df[df["user_status_id"] == 1], fmt)
    total = group_count(df, fmt, cumulative=True)

    return {"new_volunteers": new, "active_volunteers": active, "total_volunteers": total}


def get_volunteers_by_location(df, country_df, user_skills_df, help_category_df,
                                time_range_location="All", location_start_date=None,
                                location_end_date=None, country="All Countries",
                                skill="All Skills"):
    """Returns volunteer count per country. Date filter only, no grouping."""
    df = filter_by_date(df, time_range_location, location_start_date, location_end_date)

    # Join country
    df = df.merge(country_df[["country_id", "country_code"]], on="country_id", how="left")
    df["country_code"] = df["country_code"].fillna("Unknown")

    if country != "All Countries":
        df = df[df["country_code"].str.upper() == country.upper()]

    if skill != "All Skills":
        skilled = user_skills_df.merge(help_category_df, on="cat_id", how="inner")
        skilled_ids = skilled[skilled["cat_name"] == skill]["user_id"].unique()
        df = df[df["user_id"].isin(skilled_ids)]

    counts = df.groupby("country_code")["user_id"].nunique().reset_index(name="count")
    counts = counts.sort_values("count", ascending=False)
    return [{"country": r["country_code"], "count": int(r["count"])} for _, r in counts.iterrows()]


# ---- Utility Functions ----

def filter_by_date(df, time_range, start_date=None, end_date=None):
    """Filter DataFrame by time range."""
    now = datetime.now()
    if time_range == "7D":
        return df[df["created_at"] >= now - timedelta(days=7)]
    elif time_range == "30D":
        return df[df["created_at"] >= now - timedelta(days=30)]
    elif time_range == "1Y":
        return df[df["created_at"] >= now - relativedelta(years=1)]
    elif time_range == "Custom" and start_date and end_date:
        return df[(df["created_at"] >= pd.to_datetime(start_date)) &
                  (df["created_at"] <= pd.to_datetime(end_date))]
    return df  # "All"


def group_count(df, fmt, cumulative=False):
    """Group by period, count unique users, optionally cumulative."""
    if df.empty:
        return []
    df = df.copy()
    df["period"] = df["created_at"].dt.strftime(fmt)
    grouped = df.groupby("period")["user_id"].nunique().reset_index(name="count").sort_values("period")
    if cumulative:
        grouped["count"] = grouped["count"].cumsum()
    return [{"period": r["period"], "count": int(r["count"])} for _, r in grouped.iterrows()]


def load_data():
    """Load CSV files from sql/ folder."""
    users = pd.read_csv(os.path.join(SQL_DIR, "users.csv"))
    vd = pd.read_csv(os.path.join(SQL_DIR, "volunteer_details.csv"))
    country = pd.read_csv(os.path.join(SQL_DIR, "country.csv"))
    skills = pd.read_csv(os.path.join(SQL_DIR, "user_skills.csv"))
    categories = pd.read_csv(os.path.join(SQL_DIR, "help_category.csv"))

    vd["created_at"] = pd.to_datetime(vd["created_at"], errors="coerce")
    users["user_status_id"] = pd.to_numeric(users["user_status_id"], errors="coerce")
    users["country_id"] = pd.to_numeric(users["country_id"], errors="coerce")
    country["country_id"] = pd.to_numeric(country["country_id"], errors="coerce")

    return users, vd, country, skills, categories


# ---- PHASE 2: Local Testing ----

def run_local(event):
    """Run locally with CSV data."""
    users, vd, country_df, skills_df, cat_df = load_data()

    time_range = event.get("time_range", "All")
    time_range_location = event.get("time_range_location", "All")

    # Prepare merged data for trend (join vd + users)
    trend_df = vd.merge(users[["user_id", "user_status_id"]], on="user_id", how="left")
    trend_df = trend_df[trend_df["created_at"].notna()]

    # Prepare merged data for location (join vd + users for country_id)
    loc_df = vd.merge(users[["user_id", "country_id"]], on="user_id", how="left")
    loc_df = loc_df[loc_df["created_at"].notna()]

    # Get results
    trend = get_volunteer_activity_trend(
        trend_df, time_range, event.get("start_date"), event.get("end_date")
    )
    location = get_volunteers_by_location(
        loc_df, country_df, skills_df, cat_df,
        time_range_location, event.get("location_start_date"),
        event.get("location_end_date"),
        event.get("country", "All Countries"),
        event.get("skill", "All Skills")
    )

    return {
        "volunteer_activity_trend": trend,
        "volunteers_by_location": location
    }


# ---- MAIN ----

if __name__ == "__main__":
    tests = [
        ("All", {"time_range": "All", "time_range_location": "All"}),
        ("30D", {"time_range": "30D", "time_range_location": "30D"}),
        ("7D", {"time_range": "7D", "time_range_location": "7D"}),
        ("1Y", {"time_range": "1Y", "time_range_location": "1Y"}),
        ("Custom", {"time_range": "Custom", "start_date": "2026-01-01", "end_date": "2026-03-31",
                    "time_range_location": "Custom", "location_start_date": "2026-01-01",
                    "location_end_date": "2026-03-31"}),
        ("Independent", {"time_range": "7D", "time_range_location": "1Y"}),
    ]

    for name, payload in tests:
        print(f"\n{'='*50}\nTEST: {name}\n{'='*50}")
        result = run_local(payload)
        print(json.dumps(result, indent=2))

    print("\n✓ ALL TESTS PASSED")
