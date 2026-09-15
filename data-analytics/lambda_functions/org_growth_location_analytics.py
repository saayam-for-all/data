import json
import pandas as pd
import os
import unittest
from io import StringIO
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

    custom_growth = {"total_organizations": [], "collaborators": []}
    custom_location = []

    if trend_start is not None and trend_end is not None:
        trend_window = org_df[
            (org_df["created_at"] >= trend_start) & (org_df["created_at"] <= trend_end)
        ]
        custom_growth = build_growth_trend(org_df, trend_window, "day")

    if loc_start is not None and loc_end is not None:
        loc_window = org_df[
            (org_df["created_at"] >= loc_start) & (org_df["created_at"] <= loc_end)
        ]
        custom_location = build_orgs_by_location(loc_window, states_df, countries_df)

    response["Custom"] = {
        "growth_trend": custom_growth,
        "organizations_by_location": custom_location
    }

    return {"statusCode": 200, "body": response}


class TestGrowthLocationAPI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.org_df = pd.read_csv(StringIO(
            "org_id,org_name,street,city_name,state_id,zip_code,mission,web_url,phone,email,"
            "org_type,org_size,org_rating,is_collaborator,is_contributor,created_at,last_updated_at\n"
            "ORG001,Org A,1 Main,CityA,CA,90001,m,https://a.org,111,a@a.org,non_profit,small,5,TRUE,FALSE,2026-01-15 10:00:00,2026-01-15 10:00:00\n"
            "ORG002,Org B,2 Oak,CityB,TX,75001,m,https://b.org,222,b@b.org,for_profit,large,3,FALSE,TRUE,2026-02-10 10:00:00,2026-02-10 10:00:00\n"
            "ORG003,Org C,3 Elm,CityC,CA,90002,m,https://c.org,333,c@c.org,non_profit,medium,,TRUE,TRUE,2026-03-20 10:00:00,2026-03-20 10:00:00\n"
            "ORG004,Org D,4 Park,CityD,MH,40001,m,https://d.org,444,d@d.org,non_profit,small,4,TRUE,FALSE,2026-04-05 10:00:00,2026-04-05 10:00:00\n"
            "ORG005,Org E,5 Cedar,CityE,TX,75002,m,https://e.org,555,e@e.org,for_profit,large,2,FALSE,FALSE,2026-05-12 10:00:00,2026-05-12 10:00:00\n"
        ))
        cls.org_df["created_at"] = pd.to_datetime(cls.org_df["created_at"])
        cls.org_df["is_collaborator"] = cls.org_df["is_collaborator"].map(
            {"TRUE": True, "FALSE": False, True: True, False: False}
        )

        cls.states_df = pd.read_csv(StringIO(
            "state_id,country_id,state_name,state_code,last_updated_at\n"
            "CA,1,California,US-CA,2025-08-08\n"
            "TX,1,Texas,US-TX,2025-08-08\n"
            "MH,2,Maharashtra,IN-MH,2025-08-08\n"
        ))
        cls.states_df["country_id"] = pd.to_numeric(cls.states_df["country_id"])

        cls.countries_df = pd.read_csv(StringIO(
            "country_id,country_name,phone_code,country_code,last_updated_at,is_eu_member\n"
            "1,UNITED_STATES,1,USA,2025-08-08,False\n"
            "2,INDIA,91,IND,2025-08-08,False\n"
        ))
        cls.countries_df["country_id"] = pd.to_numeric(cls.countries_df["country_id"])

    def test_no_body(self):
        result = handler({}, self.org_df, self.states_df, self.countries_df)
        self.assertEqual(result["statusCode"], 200)
        body = result["body"]
        for key in ["7D", "30D", "1Y", "All", "Custom"]:
            self.assertIn(key, body)
            self.assertIn("growth_trend", body[key])
            self.assertIn("organizations_by_location", body[key])
            self.assertIn("total_organizations", body[key]["growth_trend"])
            self.assertIn("collaborators", body[key]["growth_trend"])

    def test_custom_empty_when_no_dates(self):
        result = handler({}, self.org_df, self.states_df, self.countries_df)
        custom = result["body"]["Custom"]
        self.assertEqual(custom["growth_trend"]["total_organizations"], [])
        self.assertEqual(custom["growth_trend"]["collaborators"], [])
        self.assertEqual(custom["organizations_by_location"], [])

    def test_custom_trend_only(self):
        result = handler(
            {"start_date": "2026-01-01", "end_date": "2026-03-31"},
            self.org_df, self.states_df, self.countries_df
        )
        custom = result["body"]["Custom"]
        self.assertGreater(len(custom["growth_trend"]["total_organizations"]), 0)
        self.assertEqual(custom["organizations_by_location"], [])

    def test_custom_location_only(self):
        result = handler(
            {"location_start_date": "2026-01-01", "location_end_date": "2026-03-31"},
            self.org_df, self.states_df, self.countries_df
        )
        custom = result["body"]["Custom"]
        self.assertEqual(custom["growth_trend"]["total_organizations"], [])
        self.assertGreater(len(custom["organizations_by_location"]), 0)

    def test_custom_both_ranges(self):
        result = handler(
            {
                "start_date": "2026-01-01", "end_date": "2026-05-31",
                "location_start_date": "2026-02-01", "location_end_date": "2026-04-30"
            },
            self.org_df, self.states_df, self.countries_df
        )
        custom = result["body"]["Custom"]
        self.assertGreater(len(custom["growth_trend"]["total_organizations"]), 0)
        self.assertGreater(len(custom["organizations_by_location"]), 0)

    def test_invalid_date_format(self):
        result = handler(
            {"start_date": "not-a-date", "end_date": "2026-03-31"},
            self.org_df, self.states_df, self.countries_df
        )
        self.assertEqual(result["statusCode"], 400)

    def test_start_after_end(self):
        result = handler(
            {"start_date": "2026-06-01", "end_date": "2026-01-01"},
            self.org_df, self.states_df, self.countries_df
        )
        self.assertEqual(result["statusCode"], 400)

    def test_total_orgs_not_reset_per_bucket(self):
        result = handler({}, self.org_df, self.states_df, self.countries_df)
        all_trend = result["body"]["All"]["growth_trend"]["total_organizations"]
        if len(all_trend) > 0:
            last_count = all_trend[-1]["count"]
            self.assertEqual(last_count, len(self.org_df))

    def test_collaborators_not_cumulative(self):
        result = handler({}, self.org_df, self.states_df, self.countries_df)
        all_collab = result["body"]["All"]["growth_trend"]["collaborators"]
        for entry in all_collab:
            self.assertLessEqual(entry["count"], len(self.org_df))

    def test_location_aggregates_by_country(self):
        result = handler({}, self.org_df, self.states_df, self.countries_df)
        all_loc = result["body"]["All"]["organizations_by_location"]
        countries = [r["country"] for r in all_loc]
        self.assertIn("USA", countries)
        self.assertIn("IND", countries)
        self.assertNotIn("CA", countries)
        self.assertNotIn("TX", countries)

    def test_location_max_4_rows(self):
        result = handler({}, self.org_df, self.states_df, self.countries_df)
        for key in ["7D", "30D", "1Y", "All", "Custom"]:
            loc = result["body"][key]["organizations_by_location"]
            self.assertLessEqual(len(loc), 4)

    def test_location_no_percentage(self):
        result = handler({}, self.org_df, self.states_df, self.countries_df)
        for key in ["7D", "30D", "1Y", "All"]:
            for row in result["body"][key]["organizations_by_location"]:
                self.assertNotIn("percentage", row)

    def test_grouping_7d_30d_by_day(self):
        result = handler({}, self.org_df, self.states_df, self.countries_df)
        for key in ["7D", "30D"]:
            trend = result["body"][key]["growth_trend"]["total_organizations"]
            for entry in trend:
                self.assertRegex(entry["period"], r"^\d{4}-\d{2}-\d{2}$")

    def test_grouping_1y_all_by_month(self):
        result = handler({}, self.org_df, self.states_df, self.countries_df)
        for key in ["1Y", "All"]:
            trend = result["body"][key]["growth_trend"]["total_organizations"]
            for entry in trend:
                self.assertRegex(entry["period"], r"^\d{4}-\d{2}$")

    def test_empty_org_df(self):
        empty_df = self.org_df.iloc[0:0].copy()
        result = handler({}, empty_df, self.states_df, self.countries_df)
        self.assertEqual(result["statusCode"], 200)
        for key in ["7D", "30D", "1Y", "All", "Custom"]:
            self.assertEqual(result["body"][key]["growth_trend"]["total_organizations"], [])
            self.assertEqual(result["body"][key]["organizations_by_location"], [])

    def test_single_row_org_df(self):
        single_df = self.org_df.iloc[0:1].copy()
        result = handler({}, single_df, self.states_df, self.countries_df)
        self.assertEqual(result["statusCode"], 200)

    def test_exactly_five_keys(self):
        result = handler({}, self.org_df, self.states_df, self.countries_df)
        self.assertEqual(set(result["body"].keys()), {"7D", "30D", "1Y", "All", "Custom"})

    def test_no_extra_keys_in_bucket(self):
        result = handler({}, self.org_df, self.states_df, self.countries_df)
        for key in ["7D", "30D", "1Y", "All", "Custom"]:
            self.assertEqual(set(result["body"][key].keys()), {"growth_trend", "organizations_by_location"})

    def test_invalid_location_dates(self):
        result = handler(
            {"location_start_date": "2026-12-01", "location_end_date": "2026-01-01"},
            self.org_df, self.states_df, self.countries_df
        )
        self.assertEqual(result["statusCode"], 400)


def run_local_tests():
    sql_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sql")

    try:
        org_df, states_df, countries_df = load_data(sql_dir)
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    test_events = [
        {"label": "No body", "event": {}},
        {"label": "Only start_date/end_date", "event": {"start_date": "2026-01-01", "end_date": "2026-06-30"}},
        {"label": "Only location dates", "event": {"location_start_date": "2026-01-01", "location_end_date": "2026-06-30"}},
        {"label": "Both date ranges", "event": {
            "start_date": "2026-01-01", "end_date": "2026-06-30",
            "location_start_date": "2026-03-01", "location_end_date": "2026-08-31"
        }},
    ]

    results = {}

    for test in test_events:
        label = test["label"]
        response = handler(test["event"], org_df, states_df, countries_df)
        results[label] = {"request": test["event"], "response": response}
        print(f"\n=== {label} ===")
        print(f"Request: {json.dumps(test['event'], indent=2)}")
        print(f"Response: {json.dumps(response, indent=2)}")

    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "org_growth_location_test_results.json"
    )
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nTest results saved to {output_path}")


def main():
    print("=" * 60)
    print("RUNNING UNIT TESTS")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestGrowthLocationAPI)
    runner = unittest.TextTestRunner(verbosity=2)
    test_result = runner.run(suite)

    print("\n" + "=" * 60)
    print("RUNNING LOCAL TESTS WITH MOCK DATA")
    print("=" * 60)

    run_local_tests()

    if test_result.wasSuccessful():
        print("\nAll unit tests passed.")
    else:
        print("\nSome unit tests failed.")


if __name__ == "__main__":
    main()
