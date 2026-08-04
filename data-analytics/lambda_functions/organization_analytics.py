import json
import pandas as pd
from datetime import datetime, timedelta
import os


def apply_date_filter(df, time_filter, start_date=None, end_date=None):
    today = pd.Timestamp.now().normalize()
    if time_filter == "7D":
        return df[df["created_at"] >= today - pd.Timedelta(days=7)]
    elif time_filter == "30D":
        return df[df["created_at"] >= today - pd.Timedelta(days=30)]
    elif time_filter == "1Y":
        return df[df["created_at"] >= today - pd.DateOffset(years=1)]
    elif time_filter == "ALL":
        return df
    elif time_filter == "CUSTOM":
        if start_date and end_date:
            return df[
                (df["created_at"] >= pd.Timestamp(start_date))
                & (df["created_at"] <= pd.Timestamp(end_date))
            ]
    return df


def apply_optional_filters(df, filters):
    if filters.get("org_type"):
        df = df[df["org_type"] == filters["org_type"]]
    if filters.get("org_size"):
        df = df[df["org_size"] == filters["org_size"]]
    if filters.get("state_id"):
        df = df[df["state_id"] == filters["state_id"]]
    if filters.get("city_name"):
        df = df[df["city_name"].str.lower() == filters["city_name"].lower()]
    if filters.get("org_rating"):
        df = df[df["org_rating"] == filters["org_rating"]]
    if filters.get("is_collaborator") is not None:
        df = df[df["is_collaborator"] == filters["is_collaborator"]]
    if filters.get("is_contributor") is not None:
        df = df[df["is_contributor"] == filters["is_contributor"]]
    return df


def get_grouping(group_by):
    if group_by == "daily":
        return "%Y-%m-%d"
    elif group_by == "weekly":
        return "week"
    elif group_by == "monthly":
        return "%Y-%m"
    elif group_by == "yearly":
        return "%Y"
    return "%Y-%m"


def get_organization_overview(df, state_df, group_by):
    summary = {
        "total_organizations": len(df),
        "non_profit_organizations": int((df["org_type"] == "non_profit").sum()),
        "for_profit_organizations": int((df["org_type"] == "for_profit").sum()),
        "collaborator_organizations": int((df["is_collaborator"] == True).sum()),
        "non_collaborator_organizations": int((df["is_collaborator"] != True).sum()),
        "contributor_organizations": int((df["is_contributor"] == True).sum()),
        "non_contributor_organizations": int((df["is_contributor"] != True).sum()),
    }

    fmt = get_grouping(group_by)
    if fmt == "week":
        df["period"] = df["created_at"].dt.to_period("W").apply(lambda x: x.start_time.strftime("%Y-%m-%d"))
    else:
        df["period"] = df["created_at"].dt.strftime(fmt)

    trend = df.groupby("period").size().reset_index(name="count").sort_values("period")
    activity_trend = [{"period": r["period"], "count": int(r["count"])} for _, r in trend.iterrows()]

    by_type = df.groupby("org_type").size().reset_index(name="count").sort_values("count", ascending=False)
    organizations_by_type = [{"org_type": r["org_type"], "count": int(r["count"])} for _, r in by_type.iterrows()]

    by_size = df.groupby("org_size").size().reset_index(name="count").sort_values("count", ascending=False)
    organizations_by_size = [{"org_size": r["org_size"], "count": int(r["count"])} for _, r in by_size.iterrows()]

    merged_loc = df.merge(state_df[["state_id", "state_name"]], on="state_id", how="left")
    merged_loc["state_name"] = merged_loc["state_name"].fillna("Unknown")
    by_loc = merged_loc.groupby(["state_name", "city_name"]).size().reset_index(name="count").sort_values("count", ascending=False)
    organizations_by_location = [
        {"state": r["state_name"], "city": r["city_name"], "count": int(r["count"])}
        for _, r in by_loc.iterrows()
    ]

    collab_count = int((df["is_collaborator"] == True).sum())
    non_collab_count = int((df["is_collaborator"] != True).sum())
    collaborator_distribution = [
        {"type": "collaborator", "count": collab_count},
        {"type": "non_collaborator", "count": non_collab_count}
    ]

    contrib_count = int((df["is_contributor"] == True).sum())
    non_contrib_count = int((df["is_contributor"] != True).sum())
    contributor_distribution = [
        {"type": "contributor", "count": contrib_count},
        {"type": "non_contributor", "count": non_contrib_count}
    ]

    return {
        "summary": summary,
        "organization_activity_trend": activity_trend,
        "organizations_by_type": organizations_by_type,
        "organizations_by_size": organizations_by_size,
        "organizations_by_location": organizations_by_location,
        "collaborator_distribution": collaborator_distribution,
        "contributor_distribution": contributor_distribution
    }


def get_organization_performance(df):
    rated = df[df["org_rating"].notna()]
    avg_rating = round(float(rated["org_rating"].mean()), 2) if len(rated) > 0 else 0

    summary = {
        "average_rating": avg_rating,
        "rated_organizations": len(rated),
        "unrated_organizations": int(df["org_rating"].isna().sum()),
        "five_star_organizations": int((df["org_rating"] == 5).sum())
    }

    rating_dist = rated.groupby("org_rating").size().reset_index(name="count").sort_values("org_rating")
    rating_distribution = [{"rating": int(r["org_rating"]), "count": int(r["count"])} for _, r in rating_dist.iterrows()]

    top_rated_df = rated.sort_values(["org_rating", "org_name"], ascending=[False, True]).head(10)
    top_rated = [
        {"org_id": r["org_id"], "org_name": r["org_name"], "rating": int(r["org_rating"]),
         "org_type": r["org_type"], "org_size": r["org_size"]}
        for _, r in top_rated_df.iterrows()
    ]

    collab_df = df[df["is_collaborator"] == True].copy()
    collab_df["rating_sort"] = collab_df["org_rating"].fillna(0)
    top_collab_df = collab_df.sort_values(["rating_sort", "org_name"], ascending=[False, True]).head(10)
    top_collaborators = [
        {"org_id": r["org_id"], "org_name": r["org_name"],
         "rating": int(r["org_rating"]) if pd.notna(r["org_rating"]) else None,
         "org_type": r["org_type"]}
        for _, r in top_collab_df.iterrows()
    ]

    contrib_df = df[df["is_contributor"] == True].copy()
    contrib_df["rating_sort"] = contrib_df["org_rating"].fillna(0)
    top_contrib_df = contrib_df.sort_values(["rating_sort", "org_name"], ascending=[False, True]).head(10)
    top_contributors = [
        {"org_id": r["org_id"], "org_name": r["org_name"],
         "rating": int(r["org_rating"]) if pd.notna(r["org_rating"]) else None,
         "org_type": r["org_type"]}
        for _, r in top_contrib_df.iterrows()
    ]

    rt = rated.groupby(["org_type", "org_rating"]).size().reset_index(name="count").sort_values(["org_type", "org_rating"])
    ratings_by_type = [
        {"org_type": r["org_type"], "rating": int(r["org_rating"]), "count": int(r["count"])}
        for _, r in rt.iterrows()
    ]

    rs = rated.groupby(["org_size", "org_rating"]).size().reset_index(name="count").sort_values(["org_size", "org_rating"])
    ratings_by_size = [
        {"org_size": r["org_size"], "rating": int(r["org_rating"]), "count": int(r["count"])}
        for _, r in rs.iterrows()
    ]

    return {
        "summary": summary,
        "rating_distribution": rating_distribution,
        "top_rated_organizations": top_rated,
        "top_collaborator_organizations": top_collaborators,
        "top_contributor_organizations": top_contributors,
        "ratings_by_organization_type": ratings_by_type,
        "ratings_by_organization_size": ratings_by_size
    }


def run_analytics(org_df, state_df, request_body):
    org_df["created_at"] = pd.to_datetime(org_df["created_at"])
    org_df["last_updated_at"] = pd.to_datetime(org_df["last_updated_at"])
    org_df["org_rating"] = pd.to_numeric(org_df["org_rating"], errors="coerce")
    org_df["is_collaborator"] = org_df["is_collaborator"].map({"TRUE": True, "FALSE": False, True: True, False: False})
    org_df["is_contributor"] = org_df["is_contributor"].map({"TRUE": True, "FALSE": False, True: True, False: False})

    time_filter = request_body.get("time_filter", "ALL")
    start_date = request_body.get("start_date", None)
    end_date = request_body.get("end_date", None)
    group_by = request_body.get("group_by", "monthly")

    filters = {
        "org_type": request_body.get("org_type"),
        "org_size": request_body.get("org_size"),
        "state_id": request_body.get("state_id"),
        "city_name": request_body.get("city_name"),
        "org_rating": request_body.get("org_rating"),
        "is_collaborator": request_body.get("is_collaborator"),
        "is_contributor": request_body.get("is_contributor"),
    }

    filtered = apply_date_filter(org_df.copy(), time_filter, start_date, end_date)
    filtered = apply_optional_filters(filtered, filters)

    overview = get_organization_overview(filtered.copy(), state_df, group_by)
    performance = get_organization_performance(filtered.copy())

    return {
        "organization_overview": overview,
        "organization_performance": performance
    }


def main():
    sql_dir = os.path.join(os.path.dirname(__file__), "..", "sql")

    org_df = pd.read_csv(os.path.join(sql_dir, "organizations.csv"))
    state_df = pd.read_csv(os.path.join(sql_dir, "state.csv"))

    test_cases = [
        {"time_filter": "7D", "group_by": "daily"},
        {"time_filter": "30D", "group_by": "daily"},
        {"time_filter": "1Y", "group_by": "monthly"},
        {"time_filter": "ALL", "group_by": "monthly"},
        {
            "time_filter": "CUSTOM",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "group_by": "monthly"
        },
    ]

    results = {}

    for test in test_cases:
        time_filter = test.get("time_filter", "ALL")
        group_by = test.get("group_by", "monthly")

        response = run_analytics(org_df.copy(), state_df, test)

        label = f"time_filter={time_filter}, group_by={group_by}"
        results[label] = response

        print(f"\n=== Test: {label} ===")
        print(json.dumps(response, indent=2))

    output_dir = os.path.join(os.path.dirname(__file__), "..", "sql")
    with open(os.path.join(output_dir, "organization_analytics_test_results.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nTest results saved to {output_dir}/organization_analytics_test_results.json")


if __name__ == "__main__":
    main()
