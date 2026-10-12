"""
Unit tests for rating_type_analytics.py (Issue #380).

Uses small in-memory CSVs written to a temp folder, so results are exact and
the tests don't depend on anyone's local mock data. "Today" is pinned.

Run:  python -m unittest test_rating_type_analytics -v
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import pandas as pd

import rating_type_analytics as rta

TODAY = pd.Timestamp("2026-09-01")

COUNTRIES = """country_id,country_name,country_code
1,UNITED_STATES,USA
2,INDIA,IND
"""

STATES = """state_id,country_id,state_name
CA,1,California
TX,1,Texas
MH,2,Maharashtra
"""

# created_at chosen so each bucket has a known answer relative to TODAY (2026-09-01):
#   7D  = 2026-08-26..2026-09-01   30D = 2026-08-03..2026-09-01
#   1Y  = 2025-09-02..2026-09-01   All = everything up to 2026-09-01
ORGS = """org_id,org_rating,org_type,state_id,created_at
O1,5,non_profit,CA,2024-08-10 09:00:00
O2,4,for_profit,TX,2024-08-15 09:00:00
O3,1,non_profit,MH,2025-06-01 09:00:00
O4,3,for_profit,CA,2025-10-05 09:00:00
O5,4,non_profit,CA,2025-10-20 09:00:00
O6,,non_profit,TX,2026-03-15 09:00:00
O7,4,non_profit,CA,2026-08-25 09:00:00
O8,5,non_profit,MH,2026-08-28 09:00:00
O9,4,for_profit,TX,2026-08-30 23:59:59
O10,5,for_profit,CA,2026-10-01 09:00:00
"""
# O10 is in the future relative to TODAY -> excluded from every fixed bucket.


def write_csvs(folder, orgs=ORGS, states=STATES, countries=COUNTRIES):
    for name, text in [("organizations.csv", orgs), ("states.csv", states), ("countries.csv", countries)]:
        with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
            fh.write(text)


class RatingTypeAnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        write_csvs(self.tmp)
        self.env = mock.patch.dict(os.environ, {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": self.tmp})
        self.env.start()
        self.today = mock.patch.object(rta, "get_today", return_value=TODAY)
        self.today.start()

    def tearDown(self):
        self.today.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, event):
        response = rta.lambda_handler(event, None)
        return response["statusCode"], json.loads(response["body"])

    def assert_bucket_shape(self, bucket):
        self.assertEqual(set(bucket), {"rating_distribution", "organization_mix_trend"})
        self.assertEqual(set(bucket["organization_mix_trend"]), {"non_profit", "for_profit"})

    # --- Test case: no body ------------------------------------------------
    def test_no_body_returns_exactly_five_keys(self):
        status, body = self.call({})
        self.assertEqual(status, 200)
        self.assertEqual(list(body), ["7D", "30D", "1Y", "All", "Custom"])
        for bucket in body.values():
            self.assert_bucket_shape(bucket)
        self.assertEqual(body["Custom"], rta.empty_bucket())

    def test_fixed_bucket_values(self):
        _, body = self.call({})
        self.assertEqual(body["7D"]["rating_distribution"],
                         [{"rating": 4, "count": 1}, {"rating": 5, "count": 1}])
        self.assertEqual(body["7D"]["organization_mix_trend"], {
            "non_profit": [{"period": "2026-08-28", "count": 6}],
            "for_profit": [{"period": "2026-08-30", "count": 3}],
        })
        self.assertEqual(body["30D"]["organization_mix_trend"]["non_profit"], [
            {"period": "2026-08-25", "count": 5},
            {"period": "2026-08-28", "count": 6},
        ])
        self.assertEqual(body["1Y"]["organization_mix_trend"], {
            "non_profit": [{"period": "2025-10", "count": 3},
                           {"period": "2026-03", "count": 4},
                           {"period": "2026-08", "count": 6}],
            "for_profit": [{"period": "2025-10", "count": 2},
                           {"period": "2026-08", "count": 3}],
        })
        # All: O6 unrated -> excluded from ratings; O10 is future -> excluded.
        self.assertEqual(body["All"]["rating_distribution"], [
            {"rating": 1, "count": 1}, {"rating": 3, "count": 1},
            {"rating": 4, "count": 4}, {"rating": 5, "count": 2},
        ])

    def test_no_zero_fill_of_missing_ratings(self):
        _, body = self.call({})
        ratings = [r["rating"] for r in body["All"]["rating_distribution"]]
        self.assertNotIn(2, ratings)

    # --- Test case: country filter -----------------------------------------
    def test_country_filter_by_code_and_name(self):
        _, by_code = self.call({"country": "IND"})
        _, by_name = self.call({"country": "india"})
        self.assertEqual(by_code, by_name)
        self.assertEqual(by_code["All"]["rating_distribution"],
                         [{"rating": 1, "count": 1}, {"rating": 5, "count": 1}])
        self.assertEqual(by_code["All"]["organization_mix_trend"]["for_profit"], [])

    def test_country_name_with_space_matches_underscore(self):
        _, body = self.call({"country": "United States"})
        total_rated = sum(r["count"] for r in body["All"]["rating_distribution"])
        self.assertEqual(total_rated, 6)  # O1,O2,O4,O5,O7,O9 (O6 unrated)

    def test_country_all_is_no_filter(self):
        self.assertEqual(self.call({"country": "ALL"}), self.call({}))

    def test_unknown_country_returns_empty_not_crash(self):
        status, body = self.call({"country": "Atlantis"})
        self.assertEqual(status, 200)
        for bucket in body.values():
            self.assertEqual(bucket, rta.empty_bucket())

    # --- Test case: rating Custom only -------------------------------------
    def test_rating_custom_only(self):
        status, body = self.call({"rating_start_date": "2025-10-01", "rating_end_date": "2025-10-31"})
        self.assertEqual(status, 200)
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"],
                         [{"rating": 3, "count": 1}, {"rating": 4, "count": 1}])
        self.assertEqual(body["Custom"]["organization_mix_trend"], rta.empty_mix_trend())

    # --- Test case: type Custom only ---------------------------------------
    def test_type_custom_only_is_daily_and_cumulative(self):
        status, body = self.call({"type_start_date": "2026-08-01", "type_end_date": "2026-08-31"})
        self.assertEqual(status, 200)
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"], [])
        self.assertEqual(body["Custom"]["organization_mix_trend"], {
            "non_profit": [{"period": "2026-08-25", "count": 5},
                           {"period": "2026-08-28", "count": 6}],
            "for_profit": [{"period": "2026-08-30", "count": 3}],
        })

    # --- Test case: both Custom pairs --------------------------------------
    def test_both_custom_pairs_each_use_own_range(self):
        status, body = self.call({
            "rating_start_date": "2025-10-01", "rating_end_date": "2025-10-31",
            "type_start_date": "2026-08-01", "type_end_date": "2026-08-31",
        })
        self.assertEqual(status, 200)
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"],
                         [{"rating": 3, "count": 1}, {"rating": 4, "count": 1}])
        self.assertEqual(body["Custom"]["organization_mix_trend"]["for_profit"],
                         [{"period": "2026-08-30", "count": 3}])

    def test_custom_range_end_date_is_inclusive(self):
        _, body = self.call({"type_start_date": "2026-08-30", "type_end_date": "2026-08-30"})
        self.assertEqual(body["Custom"]["organization_mix_trend"]["for_profit"],
                         [{"period": "2026-08-30", "count": 3}])

    # --- Test case: malformed / incomplete input ---------------------------
    def test_bad_inputs_return_400(self):
        bad_events = [
            {"rating_start_date": "2026-01-01"},
            {"rating_end_date": "2026-01-01"},
            {"type_start_date": "2026-01-01"},
            {"type_end_date": "2026-01-01"},
            {"rating_start_date": "2026/01/01", "rating_end_date": "2026-02-01"},
            {"type_start_date": "2026-02-30", "type_end_date": "2026-03-01"},
            {"rating_start_date": 20260101, "rating_end_date": "2026-02-01"},
            {"rating_start_date": "2026-06-30", "rating_end_date": "2026-01-01"},
            {"type_start_date": "2026-06-30", "type_end_date": "2026-01-01"},
            # one good pair + one bad pair -> still an error, no partial result
            {"rating_start_date": "2026-01-01", "rating_end_date": "2026-02-01",
             "type_start_date": "2026-01-01"},
            {"country": 123},
            {"body": "{not json"},
            {"body": "[1, 2]"},
        ]
        for event in bad_events:
            with self.subTest(event=event):
                status, body = self.call(event)
                self.assertEqual(status, 400)
                self.assertIn("error", body)
                self.assertNotIn("Custom", body)

    def test_api_gateway_body_string(self):
        event = {"body": json.dumps({"type_start_date": "2026-08-01", "type_end_date": "2026-08-31"})}
        status, body = self.call(event)
        self.assertEqual(status, 200)
        self.assertEqual(list(body), ["Custom"])

    # --- Test case: cumulative / non-decreasing ----------------------------
    def test_mix_trend_non_decreasing_everywhere(self):
        _, body = self.call({})
        for name, bucket in body.items():
            for org_type, series in bucket["organization_mix_trend"].items():
                counts = [p["count"] for p in series]
                with self.subTest(bucket=name, org_type=org_type):
                    self.assertEqual(counts, sorted(counts))

    def test_period_formats(self):
        _, body = self.call({})
        for name, length in [("7D", 10), ("30D", 10), ("1Y", 7), ("All", 7)]:
            for series in body[name]["organization_mix_trend"].values():
                for point in series:
                    self.assertEqual(len(point["period"]), length, f"{name}: {point}")

    # --- Test case: empty / 1-row data -------------------------------------
    def test_empty_organizations_csv(self):
        write_csvs(self.tmp, orgs="org_id,org_rating,org_type,state_id,created_at\n")
        for event in [{}, {"rating_start_date": "2026-01-01", "rating_end_date": "2026-02-01",
                           "type_start_date": "2026-01-01", "type_end_date": "2026-02-01"}]:
            status, body = self.call(event)
            self.assertEqual(status, 200)
            for bucket in body.values():
                self.assertEqual(bucket, rta.empty_bucket())

    def test_one_row_organizations_csv(self):
        write_csvs(self.tmp, orgs="org_id,org_rating,org_type,state_id,created_at\n"
                                  "O1,3,for_profit,CA,2026-08-31 10:00:00\n")
        status, body = self.call({})
        self.assertEqual(status, 200)
        self.assertEqual(body["7D"]["rating_distribution"], [{"rating": 3, "count": 1}])
        self.assertEqual(body["All"]["organization_mix_trend"],
                         {"non_profit": [], "for_profit": [{"period": "2026-08", "count": 1}]})

    # --- Server-side data problems -> 500, not a crash ---------------------
    def test_missing_csv_returns_500(self):
        os.remove(os.path.join(self.tmp, "countries.csv"))
        status, body = self.call({})
        self.assertEqual(status, 500)
        self.assertIn("error", body)

    def test_missing_required_column_returns_500(self):
        write_csvs(self.tmp, orgs="org_id,org_type,state_id,created_at\nO1,for_profit,CA,2026-08-31\n")
        status, _ = self.call({})
        self.assertEqual(status, 500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
