import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

import organization_rating_type_analytics as rta


ORG_CSV = """org_id,state_id,org_rating,org_type,created_at
ORG001,TX,5,for_profit,2025-01-05 10:00:00
ORG002,FL,4,non_profit,2025-03-20 09:30:00
ORG003,TX,3,for_profit,2025-06-03 11:15:00
ORG004,FL,5,non_profit,2025-09-14 14:00:00
ORG005,MH,2,for_profit,2025-12-25 08:45:00
ORG006,TX,4,non_profit,2026-01-10 16:20:00
ORG007,FL,5,for_profit,2026-01-15 12:00:00
ORG008,MH,1,non_profit,2026-02-22 13:30:00
ORG009,TX,4,for_profit,2026-03-18 10:10:00
ORG010,FL,5,non_profit,2026-06-01 09:00:00
"""

STATES_CSV = """state_id,state_name,country_id
TX,Texas,1
FL,Florida,1
MH,Maharashtra,2
"""

COUNTRIES_CSV = """country_id,country_code
1,USA
2,IND
"""

NOW = datetime(2026, 6, 15)


class RatingTypeAnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="rta_test_")
        for name, content in (("organizations.csv", ORG_CSV),
                              ("states.csv", STATES_CSV),
                              ("countries.csv", COUNTRIES_CSV)):
            with open(os.path.join(cls.tmpdir, name), "w") as fh:
                fh.write(content)
        cls.orgs = rta.load_organizations(cls.tmpdir)

    def build(self, rat=(None, None), typ=(None, None), country=None):
        return rta.build_response(
            self.orgs,
            {"rat_start": rat[0], "rat_end": rat[1], "typ_start": typ[0], "typ_end": typ[1]},
            country=country,
            now=NOW,
        )

    @staticmethod
    def _dt(value):
        return datetime.strptime(value, "%Y-%m-%d")

    # --- bucket structure -------------------------------------------------

    def test_no_params_returns_four_fixed_plus_empty_custom(self):
        resp = self.build()
        self.assertEqual(set(resp), {"7D", "30D", "1Y", "All", "Custom"})
        self.assertEqual(resp["Custom"]["rating_distribution"], [])
        self.assertEqual(resp["Custom"]["organization_mix_trend"],
                         {"for_profit": [], "non_profit": []})

    def test_all_bucket_rating_is_categorical_no_zero_fill(self):
        ratings = self.build()["All"]["rating_distribution"]
        self.assertEqual(ratings, [
            {"rating": 1, "count": 1},
            {"rating": 2, "count": 1},
            {"rating": 3, "count": 1},
            {"rating": 4, "count": 3},
            {"rating": 5, "count": 4},
        ])

    def test_mix_trend_is_cumulative_and_monthly_for_all(self):
        trend = self.build()["All"]["organization_mix_trend"]
        self.assertEqual(trend["for_profit"], [
            {"period": "2025-01", "count": 1},
            {"period": "2025-06", "count": 2},
            {"period": "2025-12", "count": 3},
            {"period": "2026-01", "count": 4},
            {"period": "2026-03", "count": 5},
        ])
        # counts never decrease (cumulative)
        counts = [p["count"] for p in trend["non_profit"]]
        self.assertEqual(counts, sorted(counts))

    def test_1y_window_omits_older_ratings(self):
        # ORG001 (rating 5, 2025-01) is outside the 1Y window from NOW=2026-06-15.
        ratings = self.build()["1Y"]["rating_distribution"]
        self.assertNotIn(3, [r["rating"] for r in ratings])

    # --- custom range independence ---------------------------------------

    def test_rating_range_only_populates_rating(self):
        resp = self.build(rat=(self._dt("2026-01-01"), self._dt("2026-06-30")))
        custom = resp["Custom"]
        self.assertTrue(custom["rating_distribution"])
        self.assertEqual(custom["organization_mix_trend"],
                         {"for_profit": [], "non_profit": []})

    def test_type_range_only_populates_trend_daily(self):
        resp = self.build(typ=(self._dt("2026-01-01"), self._dt("2026-06-30")))
        custom = resp["Custom"]
        self.assertEqual(custom["rating_distribution"], [])
        periods = [p["period"] for p in custom["organization_mix_trend"]["for_profit"]]
        self.assertTrue(all(len(p) == 10 for p in periods))  # YYYY-MM-DD -> daily

    def test_both_ranges_populate_both(self):
        resp = self.build(rat=(self._dt("2026-01-01"), self._dt("2026-06-30")),
                          typ=(self._dt("2025-01-01"), self._dt("2025-12-31")))
        custom = resp["Custom"]
        self.assertTrue(custom["rating_distribution"])
        self.assertTrue(custom["organization_mix_trend"]["for_profit"])

    # --- country filter ---------------------------------------------------

    def test_country_filter_applies_to_both_charts(self):
        resp = self.build(country="IND")
        ratings = resp["All"]["rating_distribution"]
        # Only MH orgs (ratings 2 and 1) are in IND.
        self.assertEqual({r["rating"] for r in ratings}, {1, 2})

    # --- handler validation ----------------------------------------------

    def test_handler_no_body_ok(self):
        os.environ["MOCK_DATA_DIR"] = self.tmpdir
        os.environ["USE_MOCK_DATA"] = "true"
        resp = rta.lambda_handler({})
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(set(json.loads(resp["body"])), {"7D", "30D", "1Y", "All", "Custom"})

    def test_handler_bad_date_returns_400(self):
        resp = rta.lambda_handler({"rating_start_date": "01-01-2026", "rating_end_date": "2026-06-30"})
        self.assertEqual(resp["statusCode"], 400)
        self.assertIn("error", json.loads(resp["body"]))

    def test_handler_incomplete_pair_returns_400(self):
        resp = rta.lambda_handler({"rating_start_date": "2026-01-01"})
        self.assertEqual(resp["statusCode"], 400)

    def test_handler_start_after_end_returns_400(self):
        resp = rta.lambda_handler({"type_start_date": "2026-06-30", "type_end_date": "2026-01-01"})
        self.assertEqual(resp["statusCode"], 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
