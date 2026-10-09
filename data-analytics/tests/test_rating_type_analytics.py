"""
Tests for lambda_functions/rating_type_analytics.py.

Run from data-analytics/:  python -m unittest discover -s tests -v
Fixtures are written to temporary directories; the repo CSVs are never touched.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import pandas as pd

LAMBDA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "lambda_functions")
)
sys.path.insert(0, LAMBDA_DIR)

import rating_type_analytics as rta  # noqa: E402

TODAY = "2026-03-15"  # 7D starts 2026-03-09, 30D 2026-02-14, 1Y 2025-03-15

ORG_HEADER = "org_id,org_name,state_id,org_type,org_rating,created_at\n"
ORG_ROWS = [
    # id, rating, type, state, created_at
    ("O1", 5, "Non-Profit", "AA", "2025-01-10 08:00:00"),
    ("O2", 4, "For-profit", "AA", "2025-06-15 10:30:00"),
    ("O3", 4, "Non-Profit", "BB", "2026-03-10 09:00:00"),
    ("O4", 1, "For-profit", "AA", "2026-03-10 23:59:59"),
    ("O5", 5, "Non-Profit", "AA", "2026-03-14 00:00:00"),
    ("O6", 2, "For-profit", "BB", "2026-02-01 12:00:00"),
]
STATE_CSV = "state_id,country_id,state_name\nAA,1,Alpha\nBB,2,Beta\n"
COUNTRY_CSV = (
    '"country_id","country_name","country_code"\n'
    '1,"UNITED_STATES_OF_AMERICA","USA"\n'
    '2,"CANADA","CAN"\n'
)


def write_mock_dir(directory, rows=ORG_ROWS, state_name="state.csv", country_name="country.csv"):
    with open(os.path.join(directory, "organizations.csv"), "w") as f:
        f.write(ORG_HEADER)
        for org_id, rating, org_type, state, created in rows:
            f.write(f"{org_id},Org {org_id},{state},{org_type},{rating},{created}\n")
    with open(os.path.join(directory, state_name), "w") as f:
        f.write(STATE_CSV)
    with open(os.path.join(directory, country_name), "w") as f:
        f.write(COUNTRY_CSV)


class AnalyticsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        write_mock_dir(self._tmp.name)
        self.df = rta.load_mock_data(self._tmp.name)

    def analytics(self, **kwargs):
        kwargs.setdefault("today", TODAY)
        return rta.build_analytics(self.df, **kwargs)

    @staticmethod
    def custom(start, end):
        return pd.Timestamp(start), pd.Timestamp(end)

    def invoke(self, event):
        env = {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": self._tmp.name}
        with mock.patch.dict(os.environ, env):
            return rta.lambda_handler(event, None)


class FixedResponseTests(AnalyticsTestCase):
    def test_fixed_response_has_exact_keys(self):
        body = self.analytics()
        self.assertEqual(list(body), ["7D", "30D", "1Y", "All", "Custom"])
        for key, charts in body.items():
            self.assertEqual(set(charts), {"rating_distribution", "organization_mix_trend"}, key)
            self.assertEqual(set(charts["organization_mix_trend"]), {"non_profit", "for_profit"})

    def test_fixed_custom_bucket_is_empty(self):
        self.assertEqual(self.analytics()["Custom"], rta.empty_charts())

    def test_fixed_rating_windows(self):
        body = self.analytics()
        self.assertEqual(body["7D"]["rating_distribution"],
                         [{"rating": 1, "count": 1}, {"rating": 4, "count": 1}, {"rating": 5, "count": 1}])
        self.assertEqual(body["30D"]["rating_distribution"], body["7D"]["rating_distribution"])
        self.assertEqual(body["1Y"]["rating_distribution"],
                         [{"rating": 1, "count": 1}, {"rating": 2, "count": 1},
                          {"rating": 4, "count": 2}, {"rating": 5, "count": 1}])
        self.assertEqual(body["All"]["rating_distribution"],
                         [{"rating": 1, "count": 1}, {"rating": 2, "count": 1},
                          {"rating": 4, "count": 2}, {"rating": 5, "count": 2}])

    def test_no_zero_filled_ratings(self):
        for key in ("7D", "1Y", "All"):
            ratings = [r["rating"] for r in self.analytics()[key]["rating_distribution"]]
            self.assertNotIn(3, ratings)
            self.assertTrue(all(r["count"] > 0 for r in self.analytics()[key]["rating_distribution"]))

    def test_ratings_ascending(self):
        ratings = [r["rating"] for r in self.analytics()["All"]["rating_distribution"]]
        self.assertEqual(ratings, sorted(ratings))

    def test_daily_vs_monthly_grouping_and_baseline(self):
        body = self.analytics()
        self.assertEqual(body["7D"]["organization_mix_trend"], {
            "non_profit": [{"period": "2026-03-10", "count": 2}, {"period": "2026-03-14", "count": 3}],
            "for_profit": [{"period": "2026-03-10", "count": 3}],
        })
        self.assertEqual(body["1Y"]["organization_mix_trend"], {
            "non_profit": [{"period": "2026-03", "count": 3}],
            "for_profit": [{"period": "2025-06", "count": 1}, {"period": "2026-02", "count": 2},
                           {"period": "2026-03", "count": 3}],
        })
        self.assertEqual(body["All"]["organization_mix_trend"]["non_profit"],
                         [{"period": "2025-01", "count": 1}, {"period": "2026-03", "count": 3}])

    def test_sparse_periods_not_zero_filled(self):
        periods = [p["period"] for p in self.analytics()["All"]["organization_mix_trend"]["for_profit"]]
        self.assertEqual(periods, ["2025-06", "2026-02", "2026-03"])  # no 2025-07 .. 2026-01

    def test_cumulative_counts_non_decreasing_and_chronological(self):
        for key in ("7D", "30D", "1Y", "All"):
            for series in self.analytics()[key]["organization_mix_trend"].values():
                counts = [p["count"] for p in series]
                periods = [p["period"] for p in series]
                self.assertEqual(counts, sorted(counts))
                self.assertEqual(periods, sorted(periods))


class CountryFilterTests(AnalyticsTestCase):
    def test_country_code_and_name_are_equivalent(self):
        by_code = self.analytics(country="USA")
        self.assertEqual(by_code, self.analytics(country="united states of america"))
        self.assertEqual(by_code, self.analytics(country="UNITED_STATES_OF_AMERICA"))

    def test_country_filters_ratings(self):
        # CAN owns O3 (4, 2026-03-10) and O6 (2, 2026-02-01)
        can = self.analytics(country="CAN")
        self.assertEqual(can["All"]["rating_distribution"],
                         [{"rating": 2, "count": 1}, {"rating": 4, "count": 1}])
        self.assertEqual(can["7D"]["rating_distribution"], [{"rating": 4, "count": 1}])

    def test_country_filters_historical_baseline(self):
        # USA 7D for_profit baseline is O2 only (O6 is CAN); CAN has no 7D for_profit activity.
        usa = self.analytics(country="USA")["7D"]["organization_mix_trend"]
        self.assertEqual(usa["for_profit"], [{"period": "2026-03-10", "count": 2}])
        self.assertEqual(usa["non_profit"], [{"period": "2026-03-14", "count": 2}])
        can = self.analytics(country="CAN")["7D"]["organization_mix_trend"]
        self.assertEqual(can["non_profit"], [{"period": "2026-03-10", "count": 1}])
        self.assertEqual(can["for_profit"], [])

    def test_all_and_default_match(self):
        self.assertEqual(self.analytics(country="ALL"), self.analytics())
        self.assertEqual(self.analytics(country="all"), self.analytics(country=None))

    def test_unknown_country_returns_empty_charts(self):
        for key in ("7D", "All"):
            self.assertEqual(self.analytics(country="Atlantis")[key], rta.empty_charts())


class CustomRangeTests(AnalyticsTestCase):
    def test_rating_only_custom(self):
        body = self.analytics(rating_range=self.custom("2026-03-01", "2026-03-31"))
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"],
                         [{"rating": 1, "count": 1}, {"rating": 4, "count": 1}, {"rating": 5, "count": 1}])
        self.assertEqual(body["Custom"]["organization_mix_trend"], {"non_profit": [], "for_profit": []})

    def test_type_only_custom(self):
        body = self.analytics(type_range=self.custom("2026-03-01", "2026-03-31"))
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"], [])
        self.assertEqual(body["Custom"]["organization_mix_trend"], {
            "non_profit": [{"period": "2026-03-10", "count": 2}, {"period": "2026-03-14", "count": 3}],
            "for_profit": [{"period": "2026-03-10", "count": 3}],
        })

    def test_both_custom_use_independent_ranges(self):
        body = self.analytics(rating_range=self.custom("2025-06-15", "2025-06-15"),
                              type_range=self.custom("2026-03-10", "2026-03-10"))
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"], [{"rating": 4, "count": 1}])
        self.assertEqual(body["Custom"]["organization_mix_trend"], {
            "non_profit": [{"period": "2026-03-10", "count": 2}],
            "for_profit": [{"period": "2026-03-10", "count": 3}],
        })

    def test_boundaries_are_inclusive(self):
        # O2 has a 10:30 timestamp on the start day; O3/O4 fall on the end day (O4 at 23:59:59).
        dist = rta.build_rating_distribution(self.df, *self.custom("2025-06-15", "2025-06-15"))
        self.assertEqual(dist, [{"rating": 4, "count": 1}])
        dist = rta.build_rating_distribution(self.df, *self.custom("2026-03-09", "2026-03-10"))
        self.assertEqual(dist, [{"rating": 1, "count": 1}, {"rating": 4, "count": 1}])
        dist = rta.build_rating_distribution(self.df, *self.custom("2026-03-11", "2026-03-14"))
        self.assertEqual(dist, [{"rating": 5, "count": 1}])
        dist = rta.build_rating_distribution(self.df, *self.custom("2026-03-11", "2026-03-13"))
        self.assertEqual(dist, [])

    def test_custom_trend_baseline_excludes_day_before_start_only(self):
        trend = rta.build_organization_mix_trend(self.df, *self.custom("2026-03-14", "2026-03-14"))
        self.assertEqual(trend["non_profit"], [{"period": "2026-03-14", "count": 3}])
        self.assertEqual(trend["for_profit"], [])


class ValidationTests(AnalyticsTestCase):
    def assert_error(self, event, *fragments):
        result = self.invoke(event)
        self.assertEqual(result["statusCode"], 400)
        message = json.loads(result["body"])["error"]
        for fragment in fragments:
            self.assertIn(fragment, message)

    def test_incomplete_pairs(self):
        self.assert_error({"rating_start_date": "2026-01-01"}, "rating_end_date")
        self.assert_error({"rating_end_date": "2026-01-01"}, "rating_start_date")
        self.assert_error({"type_start_date": "2026-01-01"}, "type_end_date")
        self.assert_error({"type_end_date": "2026-01-01"}, "type_start_date")

    def test_incomplete_pair_not_masked_by_valid_other_pair(self):
        self.assert_error({"rating_start_date": "2026-01-01", "rating_end_date": "2026-01-31",
                           "type_start_date": "2026-01-01"}, "type_end_date")

    def test_malformed_dates(self):
        for bad in ("01/02/2026", "2026-13-01", "2026-02-30", "not-a-date", "2026-1-1x", 20260101):
            self.assert_error({"rating_start_date": bad, "rating_end_date": "2026-03-01"}, "rating_start_date")
            self.assert_error({"type_start_date": "2026-03-01", "type_end_date": bad}, "type_end_date")

    def test_start_after_end(self):
        self.assert_error({"rating_start_date": "2026-03-02", "rating_end_date": "2026-03-01"}, "rating_start_date")
        self.assert_error({"type_start_date": "2026-03-02", "type_end_date": "2026-03-01"}, "type_start_date")

    def test_same_day_range_is_valid(self):
        result = self.invoke({"rating_start_date": "2026-03-10", "rating_end_date": "2026-03-10"})
        self.assertEqual(result["statusCode"], 200)

    def test_invalid_json_body(self):
        self.assert_error({"body": "{not json"}, "JSON")

    def test_unsupported_body_type_is_rejected(self):
        for body in (123, [1, 2], True):
            self.assert_error({"body": body}, "Request body must be a JSON object.")

    def test_body_string_is_parsed(self):
        event = {"body": json.dumps({"rating_start_date": "2026-03-10", "rating_end_date": "2026-03-10"})}
        result = self.invoke(event)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(list(json.loads(result["body"])), ["Custom"])


class WindowBoundaryTests(unittest.TestCase):
    """today=2026-03-15: 7D = 03-09..03-15, 30D = 02-14..03-15 (both include today)."""

    def build(self, dates):
        rows = [(f"O{i}", 3, "Non-Profit", "AA", d) for i, d in enumerate(dates)]
        with tempfile.TemporaryDirectory() as tmp:
            write_mock_dir(tmp, rows=rows)
            df = rta.load_mock_data(tmp)
        return rta.build_analytics(df, today=TODAY)

    def periods(self, body, key):
        return [p["period"] for p in body[key]["organization_mix_trend"]["non_profit"]]

    def test_windows_are_exact_calendar_spans(self):
        today = pd.Timestamp(TODAY)
        for key, days in (("7D", 7), ("30D", 30)):
            start, end = rta._window(key, today)
            self.assertEqual(end, today)
            self.assertEqual((end - start).days + 1, days)

    def test_7d_boundaries(self):
        body = self.build(["2026-03-08 23:59:59", "2026-03-09 00:00:00", "2026-03-15 23:59:59",
                           "2026-03-16 00:00:00"])
        self.assertEqual(self.periods(body, "7D"), ["2026-03-09", "2026-03-15"])
        # Only the two in-window orgs are counted as rating rows; baseline keeps the older one.
        self.assertEqual(body["7D"]["rating_distribution"], [{"rating": 3, "count": 2}])
        self.assertEqual(body["7D"]["organization_mix_trend"]["non_profit"],
                         [{"period": "2026-03-09", "count": 2}, {"period": "2026-03-15", "count": 3}])

    def test_30d_boundaries(self):
        body = self.build(["2026-02-13", "2026-02-14", "2026-03-15", "2026-03-16"])
        self.assertEqual(self.periods(body, "30D"), ["2026-02-14", "2026-03-15"])
        self.assertEqual(body["30D"]["rating_distribution"], [{"rating": 3, "count": 2}])
        self.assertEqual(body["30D"]["organization_mix_trend"]["non_profit"],
                         [{"period": "2026-02-14", "count": 2}, {"period": "2026-03-15", "count": 3}])

    def test_all_includes_everything(self):
        body = self.build(["2019-01-01", "2026-03-16"])
        self.assertEqual(body["All"]["rating_distribution"], [{"rating": 3, "count": 2}])


class SqlPathTests(unittest.TestCase):
    """The DB path is exercised with a fake psycopg2; no database is contacted."""

    def run_with_fake_db(self, env):
        captured = {}

        class Cursor:
            description = [(c,) for c in ("org_id", "org_rating", "org_type", "created_at",
                                          "country_code", "country_name")]

            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, query, *args): captured["query"] = query
            def fetchall(self): return [("O1", 4, "Non-Profit", "2026-03-10 09:00:00+00", "USA", "UNITED_STATES_OF_AMERICA")]

        class Conn:
            def cursor(self): return Cursor()
            def close(self): captured["closed"] = True

        fake = mock.Mock()
        fake.connect.side_effect = lambda **kw: captured.update(connect=kw) or Conn()
        base = {"USE_MOCK_DATA": "false", "DB_HOST": "h", "DB_NAME": "n", "DB_USER": "u", "DB_PASSWORD": "p"}
        with mock.patch.dict(os.environ, {**base, **env}), mock.patch.object(rta, "psycopg2", fake):
            return rta.lambda_handler({"country": "'; DROP TABLE x; --"}, None), captured

    def test_query_joins_and_columns(self):
        result, captured = self.run_with_fake_db({})
        self.assertEqual(result["statusCode"], 200)
        query = " ".join(captured["query"].split())
        self.assertIn("o.org_id, o.org_rating, o.org_type, o.created_at, c.country_code, c.country_name", query)
        self.assertIn("FROM virginia_dev_saayam_rdbms.organizations o", query)
        self.assertIn("LEFT JOIN virginia_dev_saayam_rdbms.state s ON o.state_id = s.state_id", query)
        self.assertIn("LEFT JOIN virginia_dev_saayam_rdbms.country c ON s.country_id = c.country_id", query)
        self.assertTrue(captured["closed"])
        self.assertEqual(captured["connect"]["host"], "h")

    def test_request_input_never_reaches_sql(self):
        _, captured = self.run_with_fake_db({})
        self.assertNotIn("DROP", captured["query"])

    def test_schema_comes_from_env_and_is_validated(self):
        _, captured = self.run_with_fake_db({"DB_SCHEMA": "ireland_dev_saayam_rdbms"})
        self.assertIn("ireland_dev_saayam_rdbms.organizations", captured["query"])
        for bad in ("x; DROP TABLE y", "a.b", "1abc", "", "sch ema"):
            result, captured = self.run_with_fake_db({"DB_SCHEMA": bad})
            self.assertEqual(result["statusCode"], 500, bad)
            self.assertNotIn("query", captured, bad)


class DatasetShapeTests(unittest.TestCase):
    def build(self, rows, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            write_mock_dir(tmp, rows=rows)
            df = rta.load_mock_data(tmp)
        return rta.build_analytics(df, today=TODAY, **kwargs)

    def test_empty_dataset(self):
        body = self.build([])
        self.assertEqual(list(body), ["7D", "30D", "1Y", "All", "Custom"])
        for charts in body.values():
            self.assertEqual(charts, rta.empty_charts())
        custom = self.build([], rating_range=(pd.Timestamp("2026-01-01"), pd.Timestamp("2026-12-31")),
                            type_range=(pd.Timestamp("2026-01-01"), pd.Timestamp("2026-12-31")))
        self.assertEqual(custom, {"Custom": rta.empty_charts()})

    def test_single_row_dataset(self):
        body = self.build([("O1", 3, "For-profit", "AA", "2026-03-12 00:00:00")])
        self.assertEqual(body["All"]["rating_distribution"], [{"rating": 3, "count": 1}])
        self.assertEqual(body["7D"]["organization_mix_trend"],
                         {"non_profit": [], "for_profit": [{"period": "2026-03-12", "count": 1}]})
        self.assertEqual(body["All"]["organization_mix_trend"]["for_profit"],
                         [{"period": "2026-03", "count": 1}])

    def test_org_outside_window_is_baseline_only(self):
        body = self.build([("O1", 3, "Non-Profit", "AA", "2020-01-01 00:00:00")])
        self.assertEqual(body["7D"]["rating_distribution"], [])
        self.assertEqual(body["7D"]["organization_mix_trend"], {"non_profit": [], "for_profit": []})
        self.assertEqual(body["All"]["rating_distribution"], [{"rating": 3, "count": 1}])

    def test_invalid_ratings_and_types_are_ignored(self):
        body = self.build([
            ("O1", 9, "Non-Profit", "AA", "2026-03-12 00:00:00"),
            ("O2", "", "Government", "AA", "2026-03-12 00:00:00"),
            ("O3", 2, "For-profit", "AA", "not-a-date"),
        ])
        self.assertEqual(body["All"]["rating_distribution"], [])
        self.assertEqual(body["All"]["organization_mix_trend"]["non_profit"], [{"period": "2026-03", "count": 1}])
        self.assertEqual(body["All"]["organization_mix_trend"]["for_profit"], [])

    def test_org_type_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_mock_dir(tmp)
            df = rta.load_mock_data(tmp)
        self.assertEqual(set(df["org_type_key"]), {"non_profit", "for_profit"})

    def test_normalize_type_accepts_all_representations(self):
        for value in ("Non-Profit", "non_profit", "non profit", " NON_PROFIT ", "Non  Profit"):
            self.assertEqual(rta._normalize_type(value), "non_profit", value)
        for value in ("For-profit", "for_profit", "for profit", "FOR_PROFIT"):
            self.assertEqual(rta._normalize_type(value), "for_profit", value)
        for value in ("Government", "", "nonprofit", None, float("nan")):
            self.assertIsNone(rta._normalize_type(value), value)

    def test_hyphenated_mock_and_underscored_db_types_give_same_result(self):
        dates = ["2026-03-10 09:00:00", "2026-03-12 09:00:00"]
        mock_style = [("O1", 3, "Non-Profit", "AA", dates[0]), ("O2", 4, "For-profit", "AA", dates[1])]
        db_style = [("O1", 3, "non_profit", "AA", dates[0]), ("O2", 4, "for_profit", "AA", dates[1])]
        self.assertEqual(self.build(mock_style), self.build(db_style))
        self.assertEqual(self.build(db_style)["All"]["organization_mix_trend"], {
            "non_profit": [{"period": "2026-03", "count": 1}],
            "for_profit": [{"period": "2026-03", "count": 1}],
        })


class MockLoadingTests(unittest.TestCase):
    def test_plural_filename_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_mock_dir(tmp, state_name="states.csv", country_name="countries.csv")
            df = rta.load_mock_data(tmp)
        self.assertEqual(sorted(df["country_code"].unique()), ["CAN", "USA"])

    def test_mock_data_dir_env_controls_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_mock_dir(tmp)
            with mock.patch.dict(os.environ, {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": tmp}):
                result = rta.lambda_handler({}, None)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(list(json.loads(result["body"])), ["7D", "30D", "1Y", "All", "Custom"])
        self.assertEqual(result["headers"]["Content-Type"], "application/json")

    def test_missing_mock_dir_returns_500_not_crash(self):
        with mock.patch.dict(os.environ, {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": "/nonexistent-dir"}):
            self.assertEqual(rta.lambda_handler({}, None)["statusCode"], 500)

    def test_db_mode_without_psycopg2_returns_500(self):
        with mock.patch.dict(os.environ, {"USE_MOCK_DATA": "false"}), \
                mock.patch.object(rta, "psycopg2", None):
            self.assertEqual(rta.lambda_handler({}, None)["statusCode"], 500)

    def test_mock_mode_works_without_psycopg2(self):
        """Fresh interpreter where importing psycopg2 raises ImportError."""
        with tempfile.TemporaryDirectory() as tmp:
            write_mock_dir(tmp)
            script = (
                "import sys; sys.modules['psycopg2'] = None\n"
                f"sys.path.insert(0, {LAMBDA_DIR!r})\n"
                "import rating_type_analytics as m\n"
                "assert m.psycopg2 is None\n"
                "r = m.lambda_handler({'country': 'USA'}, None)\n"
                "assert r['statusCode'] == 200, r\n"
                "print(','.join(__import__('json').loads(r['body'])))\n"
            )
            env = dict(os.environ, USE_MOCK_DATA="true", MOCK_DATA_DIR=tmp)
            out = subprocess.run([sys.executable, "-c", script], env=env,
                                 capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "7D,30D,1Y,All,Custom")


if __name__ == "__main__":
    unittest.main()
