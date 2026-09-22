"""Local test cases for organization_growth_location_analytics.py (issue #336).

Uses in-memory pandas DataFrames only - no CSV fixtures are added to the
repo, per the issue's "No CSV files included in pull request" requirement.
Run with: python -m unittest test_organization_growth_location_analytics.py
"""
import json
import unittest
from datetime import datetime

import pandas as pd

from organization_growth_location_analytics import (
    build_bucket,
    compute_growth_trend,
    compute_organizations_by_location,
    generate_response,
    lambda_handler,
    parse_event_body,
)


def _joined_df(rows):
    """Builds a dataframe shaped like build_joined_dataframe()'s output
    (organizations already merged with country_name), so tests don't need
    real organizations.csv/state.csv/country.csv on disk."""
    if not rows:
        return pd.DataFrame(columns=["created_at", "is_collaborator", "country_name"])
    df = pd.DataFrame(rows)
    df["created_at"] = pd.to_datetime(df["created_at"])
    return df


class GrowthTrendTests(unittest.TestCase):
    def test_running_total_is_cumulative_across_the_whole_dataset(self):
        df = _joined_df([
            {"created_at": "2026-01-01", "is_collaborator": False, "country_name": "USA"},
            {"created_at": "2026-01-02", "is_collaborator": True, "country_name": "USA"},
            {"created_at": "2026-01-03", "is_collaborator": False, "country_name": "USA"},
        ])
        result = compute_growth_trend(df, "day", pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-03"))
        # total_organizations must reflect the ALL-TIME cumulative total, not
        # a total reset to 0 at the start of the window - so 2026-01-02
        # should read 2 (including the 01-01 organization), not 1.
        self.assertEqual(
            result["total_organizations"],
            [{"period": "2026-01-02", "count": 2}, {"period": "2026-01-03", "count": 3}],
        )
        # collaborators is per-period, not cumulative.
        self.assertEqual(result["collaborators"], [{"period": "2026-01-02", "count": 1}])

    def test_arrays_are_sparse_periods_with_no_activity_are_omitted(self):
        df = _joined_df([
            {"created_at": "2026-01-01", "is_collaborator": False, "country_name": "USA"},
            {"created_at": "2026-01-05", "is_collaborator": False, "country_name": "USA"},
        ])
        result = compute_growth_trend(df, "day", pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-05"))
        periods = [p["period"] for p in result["total_organizations"]]
        self.assertEqual(periods, ["2026-01-01", "2026-01-05"])  # not 01-02/03/04

    def test_monthly_granularity(self):
        df = _joined_df([
            {"created_at": "2026-01-15", "is_collaborator": False, "country_name": "USA"},
            {"created_at": "2026-02-03", "is_collaborator": True, "country_name": "USA"},
        ])
        result = compute_growth_trend(df, "month", pd.Timestamp("2026-01-01"), pd.Timestamp("2026-02-28"))
        self.assertEqual(
            result["total_organizations"],
            [{"period": "2026-01", "count": 1}, {"period": "2026-02", "count": 2}],
        )

    def test_empty_dataframe_returns_empty_arrays(self):
        df = _joined_df([])
        result = compute_growth_trend(df, "day", None, None)
        self.assertEqual(result, {"total_organizations": [], "collaborators": []})


class LocationTests(unittest.TestCase):
    def test_top_4_countries_by_count_no_other_no_percentage(self):
        rows = (
            [{"created_at": "2026-01-01", "is_collaborator": False, "country_name": "USA"}] * 10
            + [{"created_at": "2026-01-01", "is_collaborator": False, "country_name": "India"}] * 8
            + [{"created_at": "2026-01-01", "is_collaborator": False, "country_name": "Kenya"}] * 6
            + [{"created_at": "2026-01-01", "is_collaborator": False, "country_name": "Brazil"}] * 4
            + [{"created_at": "2026-01-01", "is_collaborator": False, "country_name": "Japan"}] * 2
        )
        df = _joined_df(rows)
        result = compute_organizations_by_location(df, None, None)
        self.assertEqual(len(result), 4)  # top 4 only, Japan (5th) excluded
        self.assertEqual(
            result,
            [
                {"country": "USA", "count": 10},
                {"country": "India", "count": 8},
                {"country": "Kenya", "count": 6},
                {"country": "Brazil", "count": 4},
            ],
        )
        for entry in result:
            self.assertEqual(set(entry.keys()), {"country", "count"})  # no percentage field
        self.assertNotIn("Other", [entry["country"] for entry in result])

    def test_single_country_scenario(self):
        df = _joined_df([
            {"created_at": "2026-01-01", "is_collaborator": False, "country_name": "USA"},
            {"created_at": "2026-01-02", "is_collaborator": True, "country_name": "USA"},
        ])
        result = compute_organizations_by_location(df, None, None)
        self.assertEqual(result, [{"country": "USA", "count": 2}])

    def test_window_scoping_excludes_organizations_outside_the_range(self):
        df = _joined_df([
            {"created_at": "2025-01-01", "is_collaborator": False, "country_name": "USA"},
            {"created_at": "2026-01-01", "is_collaborator": False, "country_name": "India"},
        ])
        result = compute_organizations_by_location(df, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-31"))
        self.assertEqual(result, [{"country": "India", "count": 1}])

    def test_empty_dataframe_returns_empty_list(self):
        self.assertEqual(compute_organizations_by_location(_joined_df([]), None, None), [])


class BucketAndResponseShapeTests(unittest.TestCase):
    def _sample_df(self):
        return _joined_df([
            {"created_at": "2025-06-01", "is_collaborator": False, "country_name": "USA"},
            {"created_at": "2025-12-15", "is_collaborator": True, "country_name": "India"},
            {"created_at": "2026-01-05", "is_collaborator": False, "country_name": "USA"},
            {"created_at": "2026-01-14", "is_collaborator": True, "country_name": "USA"},
        ])

    def test_response_has_exactly_five_top_level_keys(self):
        response = generate_response(self._sample_df(), reference_date=datetime(2026, 1, 15))
        self.assertEqual(set(response.keys()), {"7D", "30D", "1Y", "All", "Custom"})
        for bucket in response.values():
            self.assertEqual(set(bucket.keys()), {"growth_trend", "organizations_by_location"})
            self.assertEqual(set(bucket["growth_trend"].keys()), {"total_organizations", "collaborators"})

    def test_custom_bucket_daily_granularity_even_for_a_long_range(self):
        bucket = build_bucket(
            self._sample_df(), "Custom", datetime(2026, 1, 15),
            growth_start=pd.Timestamp("2025-01-01"), growth_end=pd.Timestamp("2026-01-15"),
        )
        for entry in bucket["growth_trend"]["total_organizations"]:
            self.assertRegex(entry["period"], r"^\d{4}-\d{2}-\d{2}$")  # daily, not monthly

    def test_1y_and_all_use_monthly_granularity(self):
        response = generate_response(self._sample_df(), reference_date=datetime(2026, 1, 15))
        for bucket_key in ["1Y", "All"]:
            for entry in response[bucket_key]["growth_trend"]["total_organizations"]:
                self.assertRegex(entry["period"], r"^\d{4}-\d{2}$")

    def test_growth_and_location_charts_filter_independently_in_custom_bucket(self):
        df = self._sample_df()
        bucket = build_bucket(
            df, "Custom", datetime(2026, 1, 15),
            growth_start=pd.Timestamp("2026-01-01"), growth_end=pd.Timestamp("2026-01-31"),
            location_start=pd.Timestamp("2025-01-01"), location_end=pd.Timestamp("2025-12-31"),
        )
        # Growth trend restricted to Jan 2026 -> only the two Jan 2026 orgs' periods.
        growth_periods = [p["period"] for p in bucket["growth_trend"]["total_organizations"]]
        self.assertEqual(growth_periods, ["2026-01-05", "2026-01-14"])
        # Location chart restricted to 2025 -> only the two 2025 orgs (USA,
        # India), tied at count=1 - ties break alphabetically by country
        # name (a side effect of groupby's default sort=True + a stable
        # sort_values), so India sorts before USA.
        self.assertEqual(
            bucket["organizations_by_location"],
            [{"country": "India", "count": 1}, {"country": "USA", "count": 1}],
        )

    def test_empty_dataset_end_to_end(self):
        response = generate_response(_joined_df([]), reference_date=datetime(2026, 1, 15))
        self.assertEqual(set(response.keys()), {"7D", "30D", "1Y", "All", "Custom"})
        for bucket in response.values():
            self.assertEqual(bucket["growth_trend"], {"total_organizations": [], "collaborators": []})
            self.assertEqual(bucket["organizations_by_location"], [])


class InvalidDateTests(unittest.TestCase):
    def test_unparseable_custom_dates_fall_back_gracefully_not_raise(self):
        df = _joined_df([{"created_at": "2026-01-01", "is_collaborator": False, "country_name": "USA"}])
        from organization_growth_location_analytics import _parse_date
        self.assertIsNone(_parse_date("not-a-real-date"))
        self.assertIsNone(_parse_date(None))
        self.assertIsNone(_parse_date(""))
        # A whole request with garbage Custom dates should still return a
        # well-formed 5-key response, not raise.
        response = generate_response(
            df, growth_start=_parse_date("garbage"), growth_end=_parse_date("garbage"),
            reference_date=datetime(2026, 1, 2),
        )
        self.assertEqual(set(response.keys()), {"7D", "30D", "1Y", "All", "Custom"})

    def test_end_before_start_does_not_crash(self):
        df = _joined_df([{"created_at": "2026-01-01", "is_collaborator": False, "country_name": "USA"}])
        result = compute_growth_trend(df, "day", pd.Timestamp("2026-01-10"), pd.Timestamp("2026-01-01"))
        self.assertEqual(result, {"total_organizations": [], "collaborators": []})


class LambdaHandlerTests(unittest.TestCase):
    def test_parse_event_body_handles_api_gateway_and_raw_dict_events(self):
        self.assertEqual(parse_event_body(None), {})
        self.assertEqual(parse_event_body({"start_date": "2026-01-01"}), {"start_date": "2026-01-01"})
        self.assertEqual(
            parse_event_body({"body": json.dumps({"start_date": "2026-01-01"})}),
            {"start_date": "2026-01-01"},
        )
        self.assertEqual(parse_event_body({"body": "not json"}), {})

    def test_lambda_handler_returns_200_with_five_keys_using_real_sample_csvs(self):
        # This is the one test that touches the real data-analytics/sql/*.csv
        # files (via lambda_handler's default CSV dir), confirming the full
        # load -> join -> aggregate -> serialize path works end to end.
        result = lambda_handler({}, None)
        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertEqual(set(body.keys()), {"7D", "30D", "1Y", "All", "Custom"})


if __name__ == "__main__":
    unittest.main()
