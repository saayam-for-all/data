import json
import pandas as pd
import os
import unittest
from io import StringIO


def load_data(sql_dir):
    org_df = pd.read_csv(os.path.join(sql_dir, "organizations.csv"))
    state_df = pd.read_csv(os.path.join(sql_dir, "state.csv"))

    org_df["created_at"] = pd.to_datetime(org_df["created_at"])
    org_df["last_updated_at"] = pd.to_datetime(org_df["last_updated_at"])
    org_df["org_rating"] = pd.to_numeric(org_df["org_rating"], errors="coerce")
    org_df["is_collaborator"] = org_df["is_collaborator"].map(
        {"TRUE": True, "FALSE": False, True: True, False: False}
    )
    org_df["is_contributor"] = org_df["is_contributor"].map(
        {"TRUE": True, "FALSE": False, True: True, False: False}
    )

    return org_df, state_df


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


def apply_filters(df, state_df, region=None, organization_type=None):
    if region and region != "ALL":
        matching_states = state_df[state_df["state_name"].str.lower() == region.lower()]
        if not matching_states.empty:
            valid_state_ids = matching_states["state_id"].tolist()
            df = df[df["state_id"].isin(valid_state_ids)]
        else:
            df = df[df["state_id"].str.lower() == region.lower()]

    if organization_type and organization_type != "ALL":
        df = df[df["org_type"].str.lower().str.replace("-", "_") == organization_type.lower()]

    return df


def get_period(df, group_by):
    if group_by == "daily":
        return df["created_at"].dt.strftime("%Y-%m-%d")
    elif group_by == "weekly":
        return df["created_at"].dt.to_period("W").apply(lambda x: x.start_time.strftime("%Y-%m-%d"))
    elif group_by == "monthly":
        return df["created_at"].dt.strftime("%Y-%m")
    elif group_by == "yearly":
        return df["created_at"].dt.strftime("%Y")
    return df["created_at"].dt.strftime("%Y-%m")


def get_summary(df):
    rated = df[df["org_rating"].notna()]
    avg_rating = round(float(rated["org_rating"].mean()), 2) if len(rated) > 0 else 0

    return {
        "total_organizations": len(df),
        "total_collaborators": int((df["is_collaborator"] == True).sum()),
        "total_contributors": int((df["is_contributor"] == True).sum()),
        "average_org_rating": avg_rating
    }


def get_growth_trend(df, group_by):
    if len(df) == 0:
        return []

    df = df.copy()
    df["period"] = get_period(df, group_by)

    period_totals = df.groupby("period").agg(
        total_organizations=("org_id", "count"),
        total_collaborators=("is_collaborator", "sum")
    ).reset_index().sort_values("period")

    period_totals["total_organizations"] = period_totals["total_organizations"].cumsum()
    period_totals["total_collaborators"] = period_totals["total_collaborators"].cumsum().astype(int)

    return [
        {
            "period": r["period"],
            "total_organizations": int(r["total_organizations"]),
            "total_collaborators": int(r["total_collaborators"])
        }
        for _, r in period_totals.iterrows()
    ]


def get_organizations_by_location(df, state_df):
    if len(df) == 0:
        return []

    merged = df.merge(state_df[["state_id", "state_name"]], on="state_id", how="left")
    merged["state_name"] = merged["state_name"].fillna("Unknown")

    by_state = merged.groupby(["state_id", "state_name"]).size().reset_index(name="organization_count")
    total = len(df)
    by_state["percentage"] = round(by_state["organization_count"] / total * 100, 1)
    by_state = by_state.sort_values("organization_count", ascending=False)

    return [
        {
            "state_id": r["state_id"],
            "state_name": r["state_name"],
            "organization_count": int(r["organization_count"]),
            "percentage": float(r["percentage"])
        }
        for _, r in by_state.iterrows()
    ]


def get_organizations_by_size(df):
    if len(df) == 0:
        return []

    by_size = df.groupby("org_size").size().reset_index(name="organization_count")
    by_size = by_size.sort_values("organization_count", ascending=False)

    return [
        {"org_size": r["org_size"], "organization_count": int(r["organization_count"])}
        for _, r in by_size.iterrows()
    ]


def get_collaborator_vs_contributor(df):
    if len(df) == 0:
        return []

    total = len(df)
    collab_count = int((df["is_collaborator"] == True).sum())
    contrib_count = int((df["is_contributor"] == True).sum())

    return [
        {
            "type": "collaborator",
            "organization_count": collab_count,
            "percentage": round(collab_count / total * 100, 1) if total > 0 else 0
        },
        {
            "type": "contributor",
            "organization_count": contrib_count,
            "percentage": round(contrib_count / total * 100, 1) if total > 0 else 0
        }
    ]


def get_rating_distribution(df):
    if len(df) == 0:
        return []

    rated = df[df["org_rating"].notna()]
    if len(rated) == 0:
        return []

    dist = rated.groupby("org_rating").size().reset_index(name="organization_count")
    dist = dist.sort_values("org_rating")

    return [
        {"rating": int(r["org_rating"]), "organization_count": int(r["organization_count"])}
        for _, r in dist.iterrows()
    ]


def get_organization_type_distribution(df, group_by):
    if len(df) == 0:
        return []

    df = df.copy()
    df["period"] = get_period(df, group_by)
    df["org_type_normalized"] = df["org_type"].str.lower().str.replace("-", "_")

    pivot = df.groupby(["period", "org_type_normalized"]).size().unstack(fill_value=0).reset_index()
    pivot = pivot.sort_values("period")

    result = []
    for _, r in pivot.iterrows():
        entry = {"period": r["period"]}
        entry["for_profit"] = int(r.get("for_profit", 0))
        entry["non_profit"] = int(r.get("non_profit", 0))
        entry["total"] = entry["for_profit"] + entry["non_profit"]
        result.append(entry)

    return result


def run_analytics(org_df, state_df, request_body):
    time_filter = request_body.get("time_filter", "ALL")
    start_date = request_body.get("start_date")
    end_date = request_body.get("end_date")
    group_by = request_body.get("group_by", "monthly")
    region = request_body.get("region", "ALL")
    organization_type = request_body.get("organization_type", "ALL")

    filtered = apply_date_filter(org_df.copy(), time_filter, start_date, end_date)
    filtered = apply_filters(filtered, state_df, region, organization_type)

    return {
        "summary": get_summary(filtered),
        "growth_trend": get_growth_trend(filtered, group_by),
        "organizations_by_location": get_organizations_by_location(filtered, state_df),
        "organizations_by_size": get_organizations_by_size(filtered),
        "collaborator_vs_contributor": get_collaborator_vs_contributor(filtered),
        "rating_distribution": get_rating_distribution(filtered),
        "organization_type_distribution": get_organization_type_distribution(filtered, group_by)
    }


class TestOrganizationAnalytics(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.org_csv = StringIO(
            "org_id,org_name,street,city_name,state_id,zip_code,mission,web_url,phone,email,"
            "org_type,org_size,org_rating,is_collaborator,is_contributor,created_at,last_updated_at\n"
            "ORG001,Test Org 1,123 Main,CityA,CA,90001,Mission A,https://a.org,111-111-1111,a@a.org,"
            "Non-Profit,Small,5,TRUE,FALSE,2026-07-01 10:00:00,2026-07-01 10:00:00\n"
            "ORG002,Test Org 2,456 Oak,CityB,TX,75001,Mission B,https://b.org,222-222-2222,b@b.org,"
            "For-profit,Large,3,FALSE,TRUE,2026-06-15 10:00:00,2026-06-15 10:00:00\n"
            "ORG003,Test Org 3,789 Elm,CityC,CA,90002,Mission C,https://c.org,333-333-3333,c@c.org,"
            "Non-Profit,Medium,,TRUE,TRUE,2026-05-01 10:00:00,2026-05-01 10:00:00\n"
        )
        cls.state_csv = StringIO(
            "state_id,country_id,state_name,state_code,last_update_date\n"
            "CA,1,California,US-CA,2025-08-08 00:00:00\n"
            "TX,1,Texas,US-TX,2025-08-08 00:00:00\n"
        )
        cls.org_df, cls.state_df = cls._load_test_data()

    @classmethod
    def _load_test_data(cls):
        org_df = pd.read_csv(cls.org_csv)
        state_df = pd.read_csv(cls.state_csv)
        org_df["created_at"] = pd.to_datetime(org_df["created_at"])
        org_df["last_updated_at"] = pd.to_datetime(org_df["last_updated_at"])
        org_df["org_rating"] = pd.to_numeric(org_df["org_rating"], errors="coerce")
        org_df["is_collaborator"] = org_df["is_collaborator"].map(
            {"TRUE": True, "FALSE": False, True: True, False: False}
        )
        org_df["is_contributor"] = org_df["is_contributor"].map(
            {"TRUE": True, "FALSE": False, True: True, False: False}
        )
        return org_df, state_df

    def test_valid_all_filter(self):
        result = run_analytics(self.org_df.copy(), self.state_df, {"time_filter": "ALL"})
        self.assertEqual(result["summary"]["total_organizations"], 3)
        self.assertEqual(result["summary"]["total_collaborators"], 2)
        self.assertEqual(result["summary"]["total_contributors"], 2)

    def test_valid_region_filter(self):
        result = run_analytics(self.org_df.copy(), self.state_df, {
            "time_filter": "ALL", "region": "California"
        })
        self.assertEqual(result["summary"]["total_organizations"], 2)

    def test_valid_org_type_filter(self):
        result = run_analytics(self.org_df.copy(), self.state_df, {
            "time_filter": "ALL", "organization_type": "non_profit"
        })
        self.assertEqual(result["summary"]["total_organizations"], 2)

    def test_custom_date_range(self):
        result = run_analytics(self.org_df.copy(), self.state_df, {
            "time_filter": "CUSTOM", "start_date": "2026-06-01", "end_date": "2026-07-31"
        })
        self.assertEqual(result["summary"]["total_organizations"], 2)

    def test_empty_result_set(self):
        result = run_analytics(self.org_df.copy(), self.state_df, {
            "time_filter": "CUSTOM", "start_date": "2020-01-01", "end_date": "2020-12-31"
        })
        self.assertEqual(result["summary"]["total_organizations"], 0)
        self.assertEqual(result["growth_trend"], [])
        self.assertEqual(result["rating_distribution"], [])

    def test_invalid_filter_returns_all(self):
        result = run_analytics(self.org_df.copy(), self.state_df, {
            "time_filter": "INVALID"
        })
        self.assertEqual(result["summary"]["total_organizations"], 3)

    def test_null_rating_handled(self):
        result = run_analytics(self.org_df.copy(), self.state_df, {"time_filter": "ALL"})
        self.assertIsNotNone(result["summary"]["average_org_rating"])
        self.assertIsInstance(result["rating_distribution"], list)

    def test_response_structure(self):
        result = run_analytics(self.org_df.copy(), self.state_df, {"time_filter": "ALL"})
        self.assertIn("summary", result)
        self.assertIn("growth_trend", result)
        self.assertIn("organizations_by_location", result)
        self.assertIn("organizations_by_size", result)
        self.assertIn("collaborator_vs_contributor", result)
        self.assertIn("rating_distribution", result)
        self.assertIn("organization_type_distribution", result)

    def test_summary_keys(self):
        result = run_analytics(self.org_df.copy(), self.state_df, {"time_filter": "ALL"})
        summary = result["summary"]
        self.assertIn("total_organizations", summary)
        self.assertIn("total_collaborators", summary)
        self.assertIn("total_contributors", summary)
        self.assertIn("average_org_rating", summary)

    def test_rating_distribution_excludes_null(self):
        result = run_analytics(self.org_df.copy(), self.state_df, {"time_filter": "ALL"})
        for entry in result["rating_distribution"]:
            self.assertIsNotNone(entry["rating"])

    def test_location_includes_percentage(self):
        result = run_analytics(self.org_df.copy(), self.state_df, {"time_filter": "ALL"})
        for entry in result["organizations_by_location"]:
            self.assertIn("percentage", entry)
            self.assertIn("state_name", entry)

    def test_collaborator_vs_contributor_percentage(self):
        result = run_analytics(self.org_df.copy(), self.state_df, {"time_filter": "ALL"})
        for entry in result["collaborator_vs_contributor"]:
            self.assertIn("percentage", entry)
            self.assertIn("organization_count", entry)


def run_test_cases():
    sql_dir = os.path.join(os.path.dirname(__file__), "..", "sql")
    org_df, state_df = load_data(sql_dir)

    test_payloads = [
        {
            "label": "Standard 30D Test",
            "payload": {
                "time_filter": "30D",
                "start_date": None,
                "end_date": None,
                "group_by": "daily",
                "region": "ALL",
                "organization_type": "ALL"
            }
        },
        {
            "label": "Last 12 Months",
            "payload": {
                "time_filter": "1Y",
                "start_date": None,
                "end_date": None,
                "group_by": "monthly",
                "region": "ALL",
                "organization_type": "ALL"
            }
        },
        {
            "label": "Filter by Region (Alaska)",
            "payload": {
                "time_filter": "1Y",
                "start_date": None,
                "end_date": None,
                "group_by": "monthly",
                "region": "Alaska",
                "organization_type": "ALL"
            }
        },
        {
            "label": "Filter by Organization Type (non_profit)",
            "payload": {
                "time_filter": "1Y",
                "start_date": None,
                "end_date": None,
                "group_by": "monthly",
                "region": "ALL",
                "organization_type": "non_profit"
            }
        },
        {
            "label": "Custom Date Range",
            "payload": {
                "time_filter": "CUSTOM",
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
                "group_by": "monthly",
                "region": "ALL",
                "organization_type": "ALL"
            }
        },
    ]

    results = {}

    for test in test_payloads:
        label = test["label"]
        payload = test["payload"]

        response = run_analytics(org_df.copy(), state_df, payload)
        results[label] = {"request": payload, "response": response}

        print(f"\n=== {label} ===")
        print(f"Request: {json.dumps(payload, indent=2)}")
        print(f"Response: {json.dumps(response, indent=2)}")

    output_path = os.path.join(sql_dir, "organization_analytics_test_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nTest results saved to {output_path}")


def main():
    print("=" * 60)
    print("RUNNING UNIT TESTS")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestOrganizationAnalytics)
    runner = unittest.TextTestRunner(verbosity=2)
    test_result = runner.run(suite)

    print("\n" + "=" * 60)
    print("RUNNING TEST CASES WITH MOCK DATA")
    print("=" * 60)

    run_test_cases()

    if test_result.wasSuccessful():
        print("\nAll unit tests passed.")
    else:
        print("\nSome unit tests failed.")


if __name__ == "__main__":
    main()
