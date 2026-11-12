import json
import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd

import organization_rating_type_analytics as mod

TODAY = datetime(2026, 9, 30)
US = ("UNITED_STATES_OF_AMERICA", "USA")
IN = ("INDIA", "IND")
COLUMNS = [
    "org_id", "org_rating", "org_type", "state_id",
    "created_at", "country_name", "country_code",
]


def row(org_id, rating, org_type, created_at, country=US):
    return (org_id, rating, org_type, "XX", created_at, country[0], country[1])


def make_df(rows):
    return mod.normalize_orgs(pd.DataFrame(rows, columns=COLUMNS))


SAMPLE = [
    row("O1", 5, "non_profit", "2026-09-28 10:00:00"),
    row("O2", 4, "for_profit", "2026-09-10 10:00:00"),
    row("O3", 3, "Non-Profit", "2026-03-15 10:00:00"),
    row("O4", 1, "For-profit", "2024-05-20 10:00:00"),
    row("O5", 5, "non_profit", "2025-12-31 15:30:00", IN),
]


def call(event, rows=SAMPLE):
    with patch.object(mod, "get_today", return_value=TODAY), \
         patch.object(mod, "load_data", return_value=make_df(rows)):
        res = mod.lambda_handler(event, None)
    res["body"] = json.loads(res["body"])
    return res


class NoCustomParams(unittest.TestCase):
    def test_top_level_keys_and_bucket_keys(self):
        res = call({})
        self.assertEqual(res["statusCode"], 200)
        self.assertEqual(list(res["body"].keys()), ["7D", "30D", "1Y", "All", "Custom"])
        for bucket in res["body"].values():
            self.assertEqual(set(bucket.keys()), {"rating_distribution", "organization_mix_trend"})
            self.assertEqual(set(bucket["organization_mix_trend"].keys()), {"non_profit", "for_profit"})
    def test_body_is_a_json_string(self):
        with patch.object(mod, "get_today", return_value=TODAY), \
             patch.object(mod, "load_data", return_value=make_df(SAMPLE)):
            res = mod.lambda_handler({}, None)
        self.assertIsInstance(res["body"], str)
        self.assertEqual(list(json.loads(res["body"]).keys()), ["7D", "30D", "1Y", "All", "Custom"])

    def test_custom_is_empty(self):
        custom = call({})["body"]["Custom"]
        self.assertEqual(custom["rating_distribution"], [])
        self.assertEqual(custom["organization_mix_trend"], {"non_profit": [], "for_profit": []})

    def test_rating_distribution_per_bucket_and_no_zero_fill(self):
        body = call({})["body"]
        self.assertEqual(body["7D"]["rating_distribution"], [{"rating": 5, "count": 1}])
        self.assertEqual(body["30D"]["rating_distribution"],
                         [{"rating": 4, "count": 1}, {"rating": 5, "count": 1}])
        self.assertEqual(body["1Y"]["rating_distribution"],
                         [{"rating": 3, "count": 1}, {"rating": 4, "count": 1}, {"rating": 5, "count": 2}])
        self.assertEqual(body["All"]["rating_distribution"],
                         [{"rating": 1, "count": 1}, {"rating": 3, "count": 1},
                          {"rating": 4, "count": 1}, {"rating": 5, "count": 2}])

    def test_trend_grouping_daily_and_monthly(self):
        body = call({})["body"]
        self.assertEqual(body["7D"]["organization_mix_trend"],
                         {"non_profit": [{"period": "2026-09-28", "count": 1}], "for_profit": []})
        self.assertEqual(body["30D"]["organization_mix_trend"],
                         {"non_profit": [{"period": "2026-09-28", "count": 1}],
                          "for_profit": [{"period": "2026-09-10", "count": 1}]})
        self.assertEqual(body["All"]["organization_mix_trend"],
                         {"non_profit": [{"period": "2025-12", "count": 1},
                                         {"period": "2026-03", "count": 2},
                                         {"period": "2026-09", "count": 3}],
                          "for_profit": [{"period": "2024-05", "count": 1},
                                         {"period": "2026-09", "count": 2}]})

    def test_org_type_values_are_normalised(self):
        trend = call({})["body"]["All"]["organization_mix_trend"]
        self.assertEqual(trend["non_profit"][-1]["count"], 3)
        self.assertEqual(trend["for_profit"][-1]["count"], 2)


class CountryFilter(unittest.TestCase):
    def test_country_by_name_and_code(self):
        for country in ("India", "IND", "india"):
            body = call({"country": country})["body"]
            self.assertEqual(body["All"]["rating_distribution"], [{"rating": 5, "count": 1}])
            self.assertEqual(body["7D"]["rating_distribution"], [])

    def test_country_applies_to_custom_only_response(self):
        body = call({"country": "IND", "rating_start_date": "2020-01-01",
                     "rating_end_date": "2026-12-31"})["body"]
        self.assertEqual(body["Custom"]["rating_distribution"], [{"rating": 5, "count": 1}])

    def test_all_and_unknown_country(self):
        self.assertEqual(call({"country": "ALL"})["body"]["All"]["rating_distribution"][-1]["count"], 2)
        self.assertEqual(call({"country": "Atlantis"})["body"]["All"]["rating_distribution"], [])

    def test_org_without_state_kept_for_all(self):
        rows = SAMPLE + [("O6", 2, "non_profit", None, "2026-01-01 10:00:00", None, None)]
        ratings = call({}, rows)["body"]["All"]["rating_distribution"]
        self.assertIn({"rating": 2, "count": 1}, ratings)


class CustomRanges(unittest.TestCase):
    RATING = {"rating_start_date": "2025-01-01", "rating_end_date": "2025-12-31"}
    TYPE = {"type_start_date": "2026-01-01", "type_end_date": "2026-12-31"}
    TYPE_TREND = {"non_profit": [{"period": "2026-03-15", "count": 1},
                                 {"period": "2026-09-28", "count": 2}],
                  "for_profit": [{"period": "2026-09-10", "count": 1}]}

    def test_rating_pair_only(self):
        body = call(dict(self.RATING))["body"]
        self.assertEqual(list(body.keys()), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"], [{"rating": 5, "count": 1}])
        self.assertEqual(body["Custom"]["organization_mix_trend"], {"non_profit": [], "for_profit": []})

    def test_type_pair_only(self):
        body = call(dict(self.TYPE))["body"]
        self.assertEqual(list(body.keys()), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"], [])
        self.assertEqual(body["Custom"]["organization_mix_trend"], self.TYPE_TREND)

    def test_both_pairs_each_from_own_range(self):
        body = call({**self.RATING, **self.TYPE})["body"]
        self.assertEqual(list(body.keys()), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"], [{"rating": 5, "count": 1}])
        self.assertEqual(body["Custom"]["organization_mix_trend"], self.TYPE_TREND)

    def test_end_date_is_inclusive_for_whole_day(self):
        body = call({"rating_start_date": "2025-12-31", "rating_end_date": "2025-12-31"})["body"]
        self.assertEqual(body["Custom"]["rating_distribution"], [{"rating": 5, "count": 1}])


class BadInput(unittest.TestCase):
    def test_bad_pairs_return_400(self):
        for prefix in ("rating", "type"):
            s, e = f"{prefix}_start_date", f"{prefix}_end_date"
            cases = {
                "missing end": {s: "2025-01-01"},
                "missing start": {e: "2025-01-01"},
                "bad format": {s: "01/01/2025", e: "2025-12-31"},
                "not a real date": {s: "2025-02-30", e: "2025-03-01"},
                "start after end": {s: "2025-12-31", e: "2025-01-01"},
            }
            for label, event in cases.items():
                with self.subTest(prefix=prefix, case=label):
                    res = call(event)
                    self.assertEqual(res["statusCode"], 400)
                    self.assertEqual(list(res["body"].keys()), ["error"])

    def test_one_bad_pair_fails_whole_request(self):
        event = {"rating_start_date": "2025-01-01", "rating_end_date": "2025-12-31",
                 "type_start_date": "2026-12-31", "type_end_date": "2026-01-01"}
        self.assertEqual(call(event)["statusCode"], 400)

    def test_broken_json_body_returns_400(self):
        self.assertEqual(call({"body": "{oops"})["statusCode"], 400)

    def test_load_failure_returns_generic_500(self):
        with patch.object(mod, "load_data", side_effect=RuntimeError("secret detail")):
            res = mod.lambda_handler({}, None)
        self.assertEqual(res["statusCode"], 500)
        self.assertNotIn("secret detail", str(res["body"]))


class Cumulative(unittest.TestCase):
    def test_counts_never_decrease_in_any_bucket(self):
        for bucket in call({})["body"].values():
            for series in bucket["organization_mix_trend"].values():
                counts = [p["count"] for p in series]
                self.assertEqual(counts, sorted(counts))

    def test_running_total_and_sparse_periods(self):
        rows = [
            row("A", 5, "non_profit", "2026-09-01 08:00:00"),
            row("B", 5, "non_profit", "2026-09-01 20:00:00"),
            row("C", 5, "non_profit", "2026-09-01 21:00:00"),
            row("D", 5, "non_profit", "2026-09-05 09:00:00"),
        ]
        trend = call({"type_start_date": "2026-09-01", "type_end_date": "2026-09-30"},
                     rows)["body"]["Custom"]["organization_mix_trend"]
        self.assertEqual(trend["non_profit"],
                         [{"period": "2026-09-01", "count": 3}, {"period": "2026-09-05", "count": 4}])
        self.assertEqual(trend["for_profit"], [])


class EmptyData(unittest.TestCase):
    def test_empty_and_single_row_data_do_not_crash(self):
        one_row = [row("O1", 5, "non_profit", "2026-09-28 10:00:00")]
        events = [
            {},
            {"country": "USA"},
            {"rating_start_date": "2026-01-01", "rating_end_date": "2026-12-31"},
            {"type_start_date": "2026-01-01", "type_end_date": "2026-12-31"},
        ]
        for rows in ([], one_row):
            for event in events:
                with self.subTest(rows=len(rows), event=event):
                    res = call(event, rows)
                    self.assertEqual(res["statusCode"], 200)
        res = call({}, [])
        for bucket in res["body"].values():
            self.assertEqual(bucket["rating_distribution"], [])
            self.assertEqual(bucket["organization_mix_trend"], {"non_profit": [], "for_profit": []})


if __name__ == "__main__":
    unittest.main(verbosity=2)