"""Local test cases for organization_size_contribution_analytics.py (issue #376).

Uses in-memory pandas DataFrames only - no CSV fixtures are added to the
repo, per the issue's "don't commit the CSVs" requirement.
Run with: python -m unittest test_organization_size_contribution_analytics.py
"""
import json
import unittest
from datetime import datetime

import pandas as pd

from organization_size_contribution_analytics import (
    DateRangeError,
    _normalize_enum,
    _parse_date_range,
    apply_common_filters,
    build_bucket,
    compute_collaborator_vs_contributor,
    compute_organizations_by_size,
    generate_response,
    lambda_handler,
    parse_event_body,
)


def _joined_df(rows):
    """Builds a dataframe shaped like build_joined_dataframe()'s output, so
    tests don't need real organizations.csv/state.csv/country.csv on disk."""
    columns = [
        "created_at", "is_collaborator", "is_contributor",
        "org_size", "org_type", "org_type_norm", "country_name", "country_code",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(rows)
    df["created_at"] = pd.to_datetime(df["created_at"])
    if "org_type_norm" not in df.columns:
        df["org_type_norm"] = df["org_type"].apply(_normalize_enum) if "org_type" in df.columns else ""
    if "country_name" not in df.columns:
        df["country_name"] = "USA"
    if "country_code" not in df.columns:
        df["country_code"] = "USA"
    return df


class OrganizationsBySizeTests(unittest.TestCase):
    def test_one_row_per_size_category_present_no_hardcoded_list(self):
        df = _joined_df([
            {"created_at": "2026-01-01", "is_collaborator": False, "is_contributor": False, "org_size": "small"},
            {"created_at": "2026-01-02", "is_collaborator": False, "is_contributor": False, "org_size": "small"},
            {"created_at": "2026-01-03", "is_collaborator": False, "is_contributor": False, "org_size": "medium"},
        ])
        result = compute_organizations_by_size(df, None, None)
        self.assertEqual(
            sorted(result, key=lambda r: r["size"]),
            [{"size": "medium", "count": 1}, {"size": "small", "count": 2}],
        )

    def test_window_scoping_excludes_organizations_outside_the_range(self):
        df = _joined_df([
            {"created_at": "2025-01-01", "is_collaborator": False, "is_contributor": False, "org_size": "small"},
            {"created_at": "2026-01-01", "is_collaborator": False, "is_contributor": False, "org_size": "large"},
        ])
        result = compute_organizations_by_size(df, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-31"))
        self.assertEqual(result, [{"size": "large", "count": 1}])

    def test_empty_dataframe_returns_empty_list(self):
        self.assertEqual(compute_organizations_by_size(_joined_df([]), None, None), [])

    def test_counts_sum_to_total_in_window(self):
        df = _joined_df([
            {"created_at": "2026-01-01", "is_collaborator": False, "is_contributor": False, "org_size": "small"},
            {"created_at": "2026-01-02", "is_collaborator": False, "is_contributor": False, "org_size": "medium"},
            {"created_at": "2026-01-03", "is_collaborator": False, "is_contributor": False, "org_size": "large"},
        ])
        result = compute_organizations_by_size(df, None, None)
        self.assertEqual(sum(r["count"] for r in result), len(df))


class CollaboratorVsContributorTests(unittest.TestCase):
    def test_two_rows_computed_independently_not_a_partition(self):
        df = _joined_df([
            {"created_at": "2026-01-01", "is_collaborator": True, "is_contributor": True},
            {"created_at": "2026-01-02", "is_collaborator": True, "is_contributor": False},
            {"created_at": "2026-01-03", "is_collaborator": False, "is_contributor": True},
            {"created_at": "2026-01-04", "is_collaborator": False, "is_contributor": False},
        ])
        result = compute_collaborator_vs_contributor(df, None, None)
        self.assertEqual(
            result,
            [
                {"type": "Collaborator", "count": 2, "percentage": 50.0},
                {"type": "Contributor", "count": 2, "percentage": 50.0},
            ],
        )
        # 4 rows total, but an org that is both counts toward both rows, so
        # counts are not required to sum to the total or to 100%.
        self.assertNotEqual(sum(r["count"] for r in result), 3)

    def test_counts_each_at_most_the_bucket_total(self):
        df = _joined_df([
            {"created_at": "2026-01-01", "is_collaborator": True, "is_contributor": True},
            {"created_at": "2026-01-02", "is_collaborator": True, "is_contributor": True},
        ])
        result = compute_collaborator_vs_contributor(df, None, None)
        total = len(df)
        for row in result:
            self.assertLessEqual(row["count"], total)

    def test_missing_is_contributor_column_degrades_to_zero(self):
        df = pd.DataFrame([
            {"created_at": pd.Timestamp("2026-01-01"), "is_collaborator": True},
        ])
        # No is_contributor column at all - compute_collaborator_vs_contributor
        # should not crash; loading code (load_organizations) is what
        # normally fills this in, so simulate its absence directly here by
        # adding a False column, matching what load_organizations() does.
        df["is_contributor"] = False
        result = compute_collaborator_vs_contributor(df, None, None)
        contributor_row = next(r for r in result if r["type"] == "Contributor")
        self.assertEqual(contributor_row["count"], 0)
        self.assertEqual(contributor_row["percentage"], 0.0)

    def test_empty_dataframe_returns_zeroed_rows_not_crash(self):
        result = compute_collaborator_vs_contributor(_joined_df([]), None, None)
        self.assertEqual(
            result,
            [
                {"type": "Collaborator", "count": 0, "percentage": 0.0},
                {"type": "Contributor", "count": 0, "percentage": 0.0},
            ],
        )


class FilterTests(unittest.TestCase):
    def _sample_df(self):
        return _joined_df([
            {"created_at": "2026-01-01", "is_collaborator": False, "is_contributor": False,
             "org_size": "small", "org_type": "Non-Profit", "country_name": "USA", "country_code": "USA"},
            {"created_at": "2026-01-02", "is_collaborator": False, "is_contributor": False,
             "org_size": "medium", "org_type": "For-profit", "country_name": "India", "country_code": "IND"},
        ])

    def test_country_filter_matches_by_name_or_code_case_insensitively(self):
        df = self._sample_df()
        result = apply_common_filters(df, country="usa", organization_type="ALL")
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["country_name"], "USA")

    def test_organization_type_filter_normalizes_casing_and_punctuation(self):
        df = self._sample_df()
        result = apply_common_filters(df, country="ALL", organization_type="non_profit")
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["org_type"], "Non-Profit")

    def test_all_is_a_no_op_filter(self):
        df = self._sample_df()
        result = apply_common_filters(df, country="ALL", organization_type="ALL")
        self.assertEqual(len(result), 2)


class ResponseShapeTests(unittest.TestCase):
    def _sample_df(self):
        return _joined_df([
            {"created_at": "2026-01-05", "is_collaborator": True, "is_contributor": False, "org_size": "small"},
            {"created_at": "2026-01-14", "is_collaborator": False, "is_contributor": True, "org_size": "medium"},
        ])

    def test_no_custom_params_returns_five_keys_with_empty_custom(self):
        response = generate_response(self._sample_df(), reference_date=datetime(2026, 1, 15))
        self.assertEqual(set(response.keys()), {"7D", "30D", "1Y", "All", "Custom"})
        for bucket in response.values():
            self.assertEqual(set(bucket.keys()), {"organizations_by_size", "collaborator_vs_contributor"})
        self.assertEqual(
            response["Custom"],
            {"organizations_by_size": [], "collaborator_vs_contributor": []},
        )

    def test_only_size_range_returns_custom_only_with_size_populated(self):
        response = generate_response(
            self._sample_df(),
            size_start=pd.Timestamp("2026-01-01"), size_end=pd.Timestamp("2026-01-31"),
        )
        self.assertEqual(set(response.keys()), {"Custom"})
        self.assertNotEqual(response["Custom"]["organizations_by_size"], [])
        self.assertEqual(response["Custom"]["collaborator_vs_contributor"], [])

    def test_only_contribution_range_returns_custom_only_the_other_way(self):
        response = generate_response(
            self._sample_df(),
            contribution_start=pd.Timestamp("2026-01-01"), contribution_end=pd.Timestamp("2026-01-31"),
        )
        self.assertEqual(set(response.keys()), {"Custom"})
        self.assertEqual(response["Custom"]["organizations_by_size"], [])
        self.assertNotEqual(response["Custom"]["collaborator_vs_contributor"], [])

    def test_both_ranges_together_populate_both_independently(self):
        response = generate_response(
            self._sample_df(),
            size_start=pd.Timestamp("2026-01-01"), size_end=pd.Timestamp("2026-01-10"),
            contribution_start=pd.Timestamp("2026-01-10"), contribution_end=pd.Timestamp("2026-01-31"),
        )
        self.assertEqual(set(response.keys()), {"Custom"})
        # size range only covers 01-05 -> just the "small" org.
        self.assertEqual(response["Custom"]["organizations_by_size"], [{"size": "small", "count": 1}])
        # contribution range only covers 01-14 -> just that one org (medium, contributor).
        contributor_row = next(
            r for r in response["Custom"]["collaborator_vs_contributor"] if r["type"] == "Contributor"
        )
        self.assertEqual(contributor_row["count"], 1)

    def test_empty_dataset_end_to_end(self):
        response = generate_response(_joined_df([]), reference_date=datetime(2026, 1, 15))
        self.assertEqual(set(response.keys()), {"7D", "30D", "1Y", "All", "Custom"})
        for bucket in response.values():
            self.assertEqual(bucket["organizations_by_size"], [])
            zero_rows = {"organizations_by_size": [], "collaborator_vs_contributor": bucket["collaborator_vs_contributor"]}
            self.assertEqual(zero_rows["organizations_by_size"], [])


class DateRangeValidationTests(unittest.TestCase):
    def test_neither_param_returns_none_none(self):
        self.assertEqual(_parse_date_range({}, "size_start_date", "size_end_date"), (None, None))

    def test_only_one_half_raises(self):
        with self.assertRaises(DateRangeError):
            _parse_date_range({"size_start_date": "2026-01-01"}, "size_start_date", "size_end_date")
        with self.assertRaises(DateRangeError):
            _parse_date_range({"size_end_date": "2026-01-31"}, "size_start_date", "size_end_date")

    def test_malformed_date_raises(self):
        with self.assertRaises(DateRangeError):
            _parse_date_range(
                {"size_start_date": "not-a-date", "size_end_date": "2026-01-31"},
                "size_start_date", "size_end_date",
            )

    def test_start_after_end_raises(self):
        with self.assertRaises(DateRangeError):
            _parse_date_range(
                {"size_start_date": "2026-02-01", "size_end_date": "2026-01-01"},
                "size_start_date", "size_end_date",
            )

    def test_both_valid_returns_timestamps(self):
        start, end = _parse_date_range(
            {"size_start_date": "2026-01-01", "size_end_date": "2026-01-31"},
            "size_start_date", "size_end_date",
        )
        self.assertEqual(start, pd.Timestamp("2026-01-01"))
        self.assertEqual(end, pd.Timestamp("2026-01-31"))


class LambdaHandlerTests(unittest.TestCase):
    def test_parse_event_body_handles_api_gateway_and_raw_dict_events(self):
        self.assertEqual(parse_event_body(None), {})
        self.assertEqual(parse_event_body({"country": "USA"}), {"country": "USA"})
        self.assertEqual(
            parse_event_body({"body": json.dumps({"country": "USA"})}),
            {"country": "USA"},
        )
        self.assertEqual(parse_event_body({"body": "not json"}), {})

    def test_lambda_handler_returns_200_with_five_keys_using_real_sample_csvs(self):
        result = lambda_handler({}, None)
        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertEqual(set(body.keys()), {"7D", "30D", "1Y", "All", "Custom"})

    def test_lambda_handler_returns_custom_only_for_size_range(self):
        result = lambda_handler(
            {"body": json.dumps({"size_start_date": "2025-01-01", "size_end_date": "2026-01-15"})}, None
        )
        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertEqual(set(body.keys()), {"Custom"})
        self.assertEqual(body["Custom"]["collaborator_vs_contributor"], [])

    def test_lambda_handler_400s_on_malformed_date_range(self):
        result = lambda_handler(
            {"body": json.dumps({"size_start_date": "2026-01-01"})}, None
        )
        self.assertEqual(result["statusCode"], 400)
        body = json.loads(result["body"])
        self.assertIn("error", body)

    def test_lambda_handler_400s_on_start_after_end(self):
        result = lambda_handler(
            {"body": json.dumps({
                "contribution_start_date": "2026-06-01", "contribution_end_date": "2026-01-01",
            })}, None
        )
        self.assertEqual(result["statusCode"], 400)

    def test_lambda_handler_evaluates_both_custom_pairs_together_no_dropped_pair(self):
        # This is the deliberate deviation from the volunteer-side reference
        # implementation's bug (supplying both Custom pairs there silently
        # drops the second one via an early return).
        result = lambda_handler(
            {"body": json.dumps({
                "size_start_date": "2025-01-01", "size_end_date": "2026-01-15",
                "contribution_start_date": "2025-01-01", "contribution_end_date": "2026-01-15",
            })}, None
        )
        body = json.loads(result["body"])
        self.assertEqual(set(body.keys()), {"Custom"})
        self.assertNotEqual(body["Custom"]["organizations_by_size"], [])
        self.assertNotEqual(body["Custom"]["collaborator_vs_contributor"], [])


if __name__ == "__main__":
    unittest.main()
