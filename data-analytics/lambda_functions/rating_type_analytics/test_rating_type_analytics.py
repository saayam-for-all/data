"""Tests for rating_type_analytics (issue #380).

Run from this folder:  python -m unittest -v test_rating_type_analytics
(or `pytest`). The CSVs are generated into a temp folder, nothing is read from or written
to the repository, and "now" is pinned so results are deterministic.
"""
import json
import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rating_type_analytics as rta  # noqa: E402

NOW = datetime(2026, 10, 5, 12, 0, 0)

ORG_HEADER = "org_id,org_rating,org_type,state_id,created_at\n"
ORG_ROWS = [
    "1,5,non_profit,S1,2024-08-10 09:00:00",
    "2,4,for_profit,S1,2025-03-15 10:00:00",
    "3,3,non_profit,S2,2025-03-20 11:00:00",
    "4,5,non_profit,S1,2025-10-10 12:00:00",
    "5,,for_profit,S2,2026-09-20 13:00:00",   # blank rating
    "6,4,non_profit,S1,2026-10-04 14:00:00",
    "7,1,for_profit,S1,2026-10-05 08:00:00",
    "8,2,non_profit,S2,2026-06-15 15:00:00",
]
STATES = "state_id,country_id\nS1,1\nS2,2\n"
COUNTRIES = "country_id,country_name,country_code\n1,UNITED_STATES,USA\n2,INDIA,IND\n"

BUCKET_KEYS = {"rating_distribution", "organization_mix_trend"}


class RatingTypeBase(unittest.TestCase):
    org_text = ORG_HEADER + "\n".join(ORG_ROWS) + "\n"

    def setUp(self):
        logging.disable(logging.CRITICAL)  # the 500-path tests log expected tracebacks
        self.addCleanup(logging.disable, logging.NOTSET)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.write("organizations.csv", self.org_text)
        self.write("states.csv", STATES)
        self.write("countries.csv", COUNTRIES)

        env = mock.patch.dict(os.environ, {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        clock = mock.patch.object(rta, "_now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def write(self, name, text):
        with open(os.path.join(self.tmp.name, name), "w") as handle:
            handle.write(text)

    def call(self, event):
        result = rta.lambda_handler(event, None)
        return result["statusCode"], json.loads(result["body"])

    def ok(self, event):
        status, body = self.call(event)
        self.assertEqual(status, 200, body)
        return body


class TestFixedBuckets(RatingTypeBase):
    def test_no_body_returns_exactly_five_keys(self):
        body = self.ok({})
        self.assertEqual(list(body.keys()), ["7D", "30D", "1Y", "All", "Custom"])
        for bucket in body.values():
            self.assertEqual(set(bucket.keys()), BUCKET_KEYS)
            self.assertEqual(set(bucket["organization_mix_trend"].keys()), {"non_profit", "for_profit"})

    def test_custom_is_empty_without_custom_params(self):
        self.assertEqual(self.ok({})["Custom"], {
            "rating_distribution": [],
            "organization_mix_trend": {"non_profit": [], "for_profit": []},
        })

    def test_7d(self):
        bucket = self.ok({})["7D"]
        self.assertEqual(bucket["rating_distribution"], [{"rating": 1, "count": 1}, {"rating": 4, "count": 1}])
        self.assertEqual(bucket["organization_mix_trend"], {
            "non_profit": [{"period": "2026-10-04", "count": 5}],
            "for_profit": [{"period": "2026-10-05", "count": 3}],
        })

    def test_30d_skips_blank_rating_and_is_cumulative(self):
        bucket = self.ok({})["30D"]
        self.assertEqual(bucket["rating_distribution"], [{"rating": 1, "count": 1}, {"rating": 4, "count": 1}])
        self.assertEqual(bucket["organization_mix_trend"]["for_profit"], [
            {"period": "2026-09-20", "count": 2},
            {"period": "2026-10-05", "count": 3},
        ])

    def test_1y_groups_by_month(self):
        trend = self.ok({})["1Y"]["organization_mix_trend"]
        self.assertEqual(trend["non_profit"], [
            {"period": "2025-10", "count": 3},
            {"period": "2026-06", "count": 4},
            {"period": "2026-10", "count": 5},
        ])
        self.assertEqual(trend["for_profit"], [
            {"period": "2026-09", "count": 2},
            {"period": "2026-10", "count": 3},
        ])

    def test_all_counts_and_no_zero_filled_ratings(self):
        bucket = self.ok({})["All"]
        self.assertEqual(bucket["rating_distribution"], [
            {"rating": 1, "count": 1},
            {"rating": 2, "count": 1},
            {"rating": 3, "count": 1},
            {"rating": 4, "count": 2},
            {"rating": 5, "count": 2},
        ])
        self.assertEqual(bucket["organization_mix_trend"]["non_profit"][0], {"period": "2024-08", "count": 1})

    def test_unrated_orgs_never_appear(self):
        # org 5 has no rating, so the total across ratings is 7 of the 8 orgs
        counts = sum(row["count"] for row in self.ok({})["All"]["rating_distribution"])
        self.assertEqual(counts, 7)


class TestCountryFilter(RatingTypeBase):
    def test_country_code(self):
        body = self.ok({"country": "IND"})
        self.assertEqual(body["All"]["rating_distribution"], [{"rating": 2, "count": 1}, {"rating": 3, "count": 1}])

    def test_country_name_any_case_or_spacing(self):
        for value in ("India", "india", "  IND  "):
            self.assertEqual(self.ok({"country": value})["All"]["rating_distribution"],
                             [{"rating": 2, "count": 1}, {"rating": 3, "count": 1}], value)
        usa = self.ok({"country": "united states"})["All"]["rating_distribution"]
        self.assertEqual(sum(row["count"] for row in usa), 5)

    def test_all_and_empty_mean_no_filter(self):
        everything = self.ok({})
        for value in ("ALL", "all", "", None):
            self.assertEqual(self.ok({"country": value}), everything, value)

    def test_unknown_country_returns_empty_arrays(self):
        body = self.ok({"country": "ATLANTIS"})
        for bucket in body.values():
            self.assertEqual(bucket["rating_distribution"], [])
            self.assertEqual(bucket["organization_mix_trend"], {"non_profit": [], "for_profit": []})

    def test_country_applies_to_custom_only_shape(self):
        body = self.ok({"country": "IND", "rating_start_date": "2025-01-01", "rating_end_date": "2026-12-31"})
        self.assertEqual(list(body.keys()), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"], [{"rating": 2, "count": 1}, {"rating": 3, "count": 1}])

    def test_non_string_country_is_400(self):
        self.assertEqual(self.call({"country": 5})[0], 400)


class TestCustomRanges(RatingTypeBase):
    def test_rating_only(self):
        body = self.ok({"rating_start_date": "2025-03-01", "rating_end_date": "2025-03-31"})
        self.assertEqual(list(body.keys()), ["Custom"])
        self.assertEqual(set(body["Custom"].keys()), BUCKET_KEYS)
        self.assertEqual(body["Custom"]["rating_distribution"], [{"rating": 3, "count": 1}, {"rating": 4, "count": 1}])
        self.assertEqual(body["Custom"]["organization_mix_trend"], {"non_profit": [], "for_profit": []})

    def test_type_only(self):
        body = self.ok({"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"})
        self.assertEqual(list(body.keys()), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"], [])
        self.assertEqual(body["Custom"]["organization_mix_trend"], {
            "non_profit": [{"period": "2025-03-20", "count": 2}, {"period": "2025-10-10", "count": 3}],
            "for_profit": [{"period": "2025-03-15", "count": 1}],
        })

    def test_both_pairs_are_independent(self):
        body = self.ok({
            "rating_start_date": "2025-03-01", "rating_end_date": "2025-03-31",
            "type_start_date": "2025-01-01", "type_end_date": "2025-12-31",
        })
        self.assertEqual(list(body.keys()), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"], [{"rating": 3, "count": 1}, {"rating": 4, "count": 1}])
        self.assertEqual(body["Custom"]["organization_mix_trend"]["non_profit"][-1], {"period": "2025-10-10", "count": 3})

    def test_end_date_is_inclusive_for_the_whole_day(self):
        body = self.ok({"rating_start_date": "2026-10-05", "rating_end_date": "2026-10-05"})
        self.assertEqual(body["Custom"]["rating_distribution"], [{"rating": 1, "count": 1}])

    def test_custom_range_with_no_orgs_is_empty_not_a_crash(self):
        body = self.ok({
            "rating_start_date": "2000-01-01", "rating_end_date": "2000-01-31",
            "type_start_date": "2000-01-01", "type_end_date": "2000-01-31",
        })
        self.assertEqual(body["Custom"], {
            "rating_distribution": [],
            "organization_mix_trend": {"non_profit": [], "for_profit": []},
        })

    def test_type_trend_is_cumulative_from_before_the_window(self):
        # window starts after org 1 (2024-08); the running total still includes it
        body = self.ok({"type_start_date": "2025-03-01", "type_end_date": "2025-03-31"})
        self.assertEqual(body["Custom"]["organization_mix_trend"]["non_profit"], [{"period": "2025-03-20", "count": 2}])


class TestValidation(RatingTypeBase):
    BAD_EVENTS = {
        "rating start after end": {"rating_start_date": "2026-06-30", "rating_end_date": "2026-01-01"},
        "type start after end": {"type_start_date": "2026-06-30", "type_end_date": "2026-01-01"},
        "rating start only": {"rating_start_date": "2026-01-01"},
        "rating end only": {"rating_end_date": "2026-01-01"},
        "type start only": {"type_start_date": "2026-01-01"},
        "type end only": {"type_end_date": "2026-01-01"},
        "rating bad format": {"rating_start_date": "01/01/2026", "rating_end_date": "2026-06-30"},
        "type bad format": {"type_start_date": "2026-01-01", "type_end_date": "June 30"},
        "impossible date": {"rating_start_date": "2026-02-30", "rating_end_date": "2026-03-30"},
        "empty string date": {"rating_start_date": "", "rating_end_date": ""},
        "non-string date": {"type_start_date": 20260101, "type_end_date": 20260630},
        "good rating pair + bad type pair": {
            "rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30", "type_end_date": "2026-06-30",
        },
        "bad rating pair + good type pair": {
            "rating_start_date": "2026-06-30", "rating_end_date": "2026-01-01",
            "type_start_date": "2025-01-01", "type_end_date": "2025-12-31",
        },
    }

    def test_bad_input_is_a_clear_400_with_no_partial_result(self):
        for label, event in self.BAD_EVENTS.items():
            with self.subTest(label):
                status, body = self.call(event)
                self.assertEqual(status, 400)
                self.assertEqual(list(body.keys()), ["error"])
                self.assertTrue(body["error"])

    def test_same_day_range_is_valid(self):
        self.assertEqual(self.call({"rating_start_date": "2026-01-01", "rating_end_date": "2026-01-01"})[0], 200)

    def test_api_gateway_body_string(self):
        event = {"body": json.dumps({"rating_start_date": "2025-03-01", "rating_end_date": "2025-03-31"})}
        self.assertEqual(list(self.ok(event).keys()), ["Custom"])

    def test_api_gateway_missing_body_returns_full_response(self):
        self.assertEqual(list(self.ok({"body": None, "httpMethod": "GET"}).keys()), ["7D", "30D", "1Y", "All", "Custom"])

    def test_invalid_json_body_is_400(self):
        self.assertEqual(self.call({"body": "{not json"})[0], 400)
        self.assertEqual(self.call({"body": "[1, 2]"})[0], 400)

    def test_none_event_is_treated_as_empty(self):
        self.assertEqual(list(self.ok(None).keys()), ["7D", "30D", "1Y", "All", "Custom"])


class TestCumulativeCounts(RatingTypeBase):
    def assert_non_decreasing(self, trend):
        for org_type, series in trend.items():
            counts = [point["count"] for point in series]
            periods = [point["period"] for point in series]
            self.assertEqual(counts, sorted(counts), org_type)
            self.assertEqual(periods, sorted(set(periods)), org_type)
            self.assertTrue(all(count > 0 for count in counts), org_type)

    def test_every_bucket_is_cumulative_and_sparse(self):
        rows = [f"{i},{(i % 5) + 1},{'non_profit' if i % 3 else 'for_profit'},S{(i % 2) + 1},"
                f"2024-{1 + (i % 12):02d}-{1 + (i % 28):02d} 10:00:00"
                for i in range(1, 200)]
        self.write("organizations.csv", ORG_HEADER + "\n".join(rows) + "\n")
        body = self.ok({})
        for name, bucket in body.items():
            with self.subTest(name):
                self.assert_non_decreasing(bucket["organization_mix_trend"])

        custom = self.ok({"type_start_date": "2024-01-01", "type_end_date": "2024-12-31"})["Custom"]
        self.assert_non_decreasing(custom["organization_mix_trend"])


class TestEmptyAndTinyData(RatingTypeBase):
    EMPTY = {"rating_distribution": [], "organization_mix_trend": {"non_profit": [], "for_profit": []}}

    def test_header_only_organizations(self):
        self.write("organizations.csv", ORG_HEADER)
        body = self.ok({})
        self.assertEqual(list(body.keys()), ["7D", "30D", "1Y", "All", "Custom"])
        for bucket in body.values():
            self.assertEqual(bucket, self.EMPTY)
        custom = self.ok({
            "rating_start_date": "2025-01-01", "rating_end_date": "2025-12-31",
            "type_start_date": "2025-01-01", "type_end_date": "2025-12-31",
        })
        self.assertEqual(custom, {"Custom": self.EMPTY})

    def test_completely_empty_organizations_file(self):
        self.write("organizations.csv", "")
        self.assertEqual(self.ok({})["All"], self.EMPTY)

    def test_one_row_organizations(self):
        self.write("organizations.csv", ORG_HEADER + "1,5,non_profit,S1,2026-10-01 10:00:00\n")
        body = self.ok({})
        self.assertEqual(body["7D"]["rating_distribution"], [{"rating": 5, "count": 1}])
        self.assertEqual(body["All"]["organization_mix_trend"], {
            "non_profit": [{"period": "2026-10", "count": 1}],
            "for_profit": [],
        })
        self.assertEqual(self.ok({"country": "USA"})["30D"]["rating_distribution"], [{"rating": 5, "count": 1}])
        self.assertEqual(self.ok({"country": "IND"})["30D"], self.EMPTY)

    def test_org_with_unknown_state_has_no_country_but_still_counts_for_all(self):
        self.write("organizations.csv", ORG_HEADER + "1,5,non_profit,ZZ,2026-10-01 10:00:00\n")
        self.assertEqual(self.ok({})["All"]["rating_distribution"], [{"rating": 5, "count": 1}])
        self.assertEqual(self.ok({"country": "USA"})["All"], self.EMPTY)

    def test_out_of_range_and_non_integer_ratings_are_ignored(self):
        self.write("organizations.csv", ORG_HEADER + "\n".join([
            "1,0,non_profit,S1,2026-10-01 10:00:00",
            "2,6,non_profit,S1,2026-10-01 10:00:00",
            "3,4.5,non_profit,S1,2026-10-01 10:00:00",
            "4,abc,non_profit,S1,2026-10-01 10:00:00",
            "5,3,non_profit,S1,2026-10-01 10:00:00",
        ]) + "\n")
        self.assertEqual(self.ok({})["All"]["rating_distribution"], [{"rating": 3, "count": 1}])

    def test_unparseable_created_at_rows_are_dropped(self):
        self.write("organizations.csv", ORG_HEADER + "1,5,non_profit,S1,not-a-date\n2,4,non_profit,S1,2026-10-01 10:00:00\n")
        self.assertEqual(self.ok({})["All"]["rating_distribution"], [{"rating": 4, "count": 1}])


class TestFailures(RatingTypeBase):
    def test_missing_required_column_is_500(self):
        self.write("organizations.csv", "org_id,org_type,state_id,created_at\n1,non_profit,S1,2026-10-01\n")
        status, body = self.call({})
        self.assertEqual(status, 500)
        self.assertIn("error", body)

    def test_missing_csv_is_500_not_a_crash(self):
        os.remove(os.path.join(self.tmp.name, "states.csv"))
        self.assertEqual(self.call({})[0], 500)

    def test_real_db_path_without_psycopg2_is_500(self):
        with mock.patch.dict(os.environ, {"USE_MOCK_DATA": "false"}), mock.patch.object(rta, "psycopg2", None):
            self.assertEqual(self.call({})[0], 500)

    def test_bad_input_is_rejected_before_any_data_is_loaded(self):
        with mock.patch.object(rta, "load_data", side_effect=AssertionError("should not load")):
            self.assertEqual(self.call({"rating_start_date": "nope", "rating_end_date": "nope"})[0], 400)


class TestBucketRange(unittest.TestCase):
    def test_leap_day_does_not_crash_1y(self):
        start, end = rta.get_bucket_range("1Y", datetime(2028, 2, 29, 10, 0))
        self.assertEqual(start, datetime(2027, 3, 1))
        self.assertEqual(end, datetime(2028, 2, 29, 10, 0))

    def test_windows(self):
        now = datetime(2026, 10, 5, 12, 0)
        self.assertEqual(rta.get_bucket_range("7D", now)[0], datetime(2026, 9, 29))
        self.assertEqual(rta.get_bucket_range("30D", now)[0], datetime(2026, 9, 6))
        self.assertEqual(rta.get_bucket_range("1Y", now)[0], datetime(2025, 10, 6))
        self.assertIsNone(rta.get_bucket_range("All", now)[0])

    def test_unknown_bucket(self):
        with self.assertRaises(ValueError):
            rta.get_bucket_range("Custom")


if __name__ == "__main__":
    unittest.main()
