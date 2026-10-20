import json
import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd


sys.path.append(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

import organization_rating_type_analytics as analytics


class TestOrganizationRatingTypeAnalytics(unittest.TestCase):

    def setUp(self):
        self.sample_data = pd.DataFrame(
            [
                {
                    "org_id": "ORG-1",
                    "org_rating": 5,
                    "org_type": "non_profit",
                    "state_id": "CA",
                    "created_at": pd.Timestamp("2025-12-15"),
                    "country_code": "USA",
                    "country_name": "United States",
                },
                {
                    "org_id": "ORG-2",
                    "org_rating": 4,
                    "org_type": "for_profit",
                    "state_id": "CA",
                    "created_at": pd.Timestamp("2026-01-05"),
                    "country_code": "USA",
                    "country_name": "United States",
                },
                {
                    "org_id": "ORG-3",
                    "org_rating": 4,
                    "org_type": "non_profit",
                    "state_id": "TX",
                    "created_at": pd.Timestamp("2026-01-10"),
                    "country_code": "USA",
                    "country_name": "United States",
                },
                {
                    "org_id": "ORG-4",
                    "org_rating": 3,
                    "org_type": "for_profit",
                    "state_id": "ON",
                    "created_at": pd.Timestamp("2026-02-10"),
                    "country_code": "CAN",
                    "country_name": "Canada",
                },
                {
                    "org_id": "ORG-5",
                    "org_rating": None,
                    "org_type": "non_profit",
                    "state_id": "ON",
                    "created_at": pd.Timestamp("2026-02-15"),
                    "country_code": "CAN",
                    "country_name": "Canada",
                },
            ]
        )

    def test_validate_filters_accepts_empty_payload(self):
        valid, error = analytics.validate_filters({})

        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_missing_rating_end_date_returns_error(self):
        filters = {
            "rating_start_date": "2026-01-01",
        }

        valid, error = analytics.validate_filters(filters)

        self.assertFalse(valid)
        self.assertIn(
            "must be provided together",
            error,
        )

    def test_missing_type_start_date_returns_error(self):
        filters = {
            "type_end_date": "2026-01-31",
        }

        valid, error = analytics.validate_filters(filters)

        self.assertFalse(valid)
        self.assertIn(
            "must be provided together",
            error,
        )

    def test_invalid_rating_date_format_returns_error(self):
        filters = {
            "rating_start_date": "01-01-2026",
            "rating_end_date": "2026-01-31",
        }

        valid, error = analytics.validate_filters(filters)

        self.assertFalse(valid)
        self.assertIn(
            "YYYY-MM-DD",
            error,
        )

    def test_invalid_type_date_format_returns_error(self):
        filters = {
            "type_start_date": "2026/01/01",
            "type_end_date": "2026-01-31",
        }

        valid, error = analytics.validate_filters(filters)

        self.assertFalse(valid)
        self.assertIn(
            "YYYY-MM-DD",
            error,
        )

    def test_rating_start_after_end_returns_error(self):
        filters = {
            "rating_start_date": "2026-02-01",
            "rating_end_date": "2026-01-01",
        }

        valid, error = analytics.validate_filters(filters)

        self.assertFalse(valid)
        self.assertIn(
            "cannot be after",
            error,
        )

    def test_type_start_after_end_returns_error(self):
        filters = {
            "type_start_date": "2026-02-01",
            "type_end_date": "2026-01-01",
        }

        valid, error = analytics.validate_filters(filters)

        self.assertFalse(valid)
        self.assertIn(
            "cannot be after",
            error,
        )

    def test_apply_country_filter_all_returns_all_rows(self):
        result = analytics.apply_country_filter(
            self.sample_data,
            "ALL",
        )

        self.assertEqual(
            len(result),
            len(self.sample_data),
        )

    def test_apply_country_filter_by_code(self):
        result = analytics.apply_country_filter(
            self.sample_data,
            "USA",
        )

        self.assertEqual(
            len(result),
            3,
        )

    def test_apply_country_filter_by_name(self):
        result = analytics.apply_country_filter(
            self.sample_data,
            "Canada",
        )

        self.assertEqual(
            len(result),
            2,
        )

    def test_rating_distribution_groups_actual_values_only(self):
        result = analytics.build_rating_distribution(
            self.sample_data
        )

        self.assertEqual(
            result,
            [
                {
                    "rating": 3,
                    "count": 1,
                },
                {
                    "rating": 4,
                    "count": 2,
                },
                {
                    "rating": 5,
                    "count": 1,
                },
            ],
        )

    def test_rating_distribution_does_not_zero_fill(self):
        data = pd.DataFrame(
            [
                {
                    "org_rating": 5,
                },
                {
                    "org_rating": 5,
                },
            ]
        )

        result = analytics.build_rating_distribution(
            data
        )

        self.assertEqual(
            result,
            [
                {
                    "rating": 5,
                    "count": 2,
                }
            ],
        )

    def test_rating_distribution_empty_data(self):
        data = pd.DataFrame(
            columns=["org_rating"]
        )

        result = analytics.build_rating_distribution(
            data
        )

        self.assertEqual(
            result,
            [],
        )

    def test_filter_date_range_inclusive_end_date(self):
        result = analytics.filter_date_range(
            self.sample_data,
            "2026-01-05",
            "2026-01-10",
        )

        self.assertEqual(
            len(result),
            2,
        )

    def test_mix_trend_is_cumulative(self):
        visible_data = analytics.filter_date_range(
            self.sample_data,
            "2026-01-01",
            "2026-12-31",
        )

        result = analytics.build_organization_mix_trend(
            self.sample_data,
            visible_data,
            "daily",
            "2026-01-01",
        )

        non_profit_counts = [
            item["count"]
            for item in result["non_profit"]
        ]

        for_profit_counts = [
            item["count"]
            for item in result["for_profit"]
        ]

        self.assertEqual(
            non_profit_counts,
            sorted(non_profit_counts),
        )

        self.assertEqual(
            for_profit_counts,
            sorted(for_profit_counts),
        )

    def test_mix_trend_preserves_pre_range_baseline(self):
        visible_data = analytics.filter_date_range(
            self.sample_data,
            "2026-01-01",
            "2026-12-31",
        )

        result = analytics.build_organization_mix_trend(
            self.sample_data,
            visible_data,
            "daily",
            "2026-01-01",
        )

        non_profit = result["non_profit"]

        self.assertTrue(
            len(non_profit) > 0
        )

        self.assertGreaterEqual(
            non_profit[0]["count"],
            2,
        )

    def test_mix_trend_daily_format(self):
        visible_data = analytics.filter_date_range(
            self.sample_data,
            "2026-01-01",
            "2026-12-31",
        )

        result = analytics.build_organization_mix_trend(
            self.sample_data,
            visible_data,
            "daily",
            "2026-01-01",
        )

        all_points = (
            result["non_profit"]
            + result["for_profit"]
        )

        for item in all_points:
            self.assertRegex(
                item["period"],
                r"^\d{4}-\d{2}-\d{2}$",
            )

    def test_mix_trend_monthly_format(self):
        result = analytics.build_organization_mix_trend(
            self.sample_data,
            self.sample_data,
            "monthly",
            None,
        )

        all_points = (
            result["non_profit"]
            + result["for_profit"]
        )

        for item in all_points:
            self.assertRegex(
                item["period"],
                r"^\d{4}-\d{2}$",
            )

    def test_mix_trend_sparse_periods(self):
        data = pd.DataFrame(
            [
                {
                    "org_type": "non_profit",
                    "created_at": pd.Timestamp("2026-01-01"),
                },
                {
                    "org_type": "non_profit",
                    "created_at": pd.Timestamp("2026-01-05"),
                },
            ]
        )

        result = analytics.build_organization_mix_trend(
            data,
            data,
            "daily",
            None,
        )

        periods = [
            item["period"]
            for item in result["non_profit"]
        ]

        self.assertEqual(
            periods,
            [
                "2026-01-01",
                "2026-01-05",
            ],
        )

    def test_no_custom_returns_exactly_five_keys(self):
        with patch.object(
            analytics,
            "load_mock_data",
            return_value=self.sample_data,
        ):
            result = analytics.build_mock_response(
                {}
            )

        self.assertEqual(
            list(result.keys()),
            [
                "7D",
                "30D",
                "1Y",
                "All",
                "Custom",
            ],
        )

    def test_no_custom_has_empty_custom(self):
        with patch.object(
            analytics,
            "load_mock_data",
            return_value=self.sample_data,
        ):
            result = analytics.build_mock_response(
                {}
            )

        self.assertEqual(
            result["Custom"],
            {
                "rating_distribution": [],
                "organization_mix_trend": {
                    "non_profit": [],
                    "for_profit": [],
                },
            },
        )

    def test_rating_custom_only_returns_custom_only(self):
        filters = {
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-12-31",
        }

        with patch.object(
            analytics,
            "load_mock_data",
            return_value=self.sample_data,
        ):
            result = analytics.build_mock_response(
                filters
            )

        self.assertEqual(
            list(result.keys()),
            ["Custom"],
        )

        self.assertGreater(
            len(
                result["Custom"][
                    "rating_distribution"
                ]
            ),
            0,
        )

        self.assertEqual(
            result["Custom"][
                "organization_mix_trend"
            ],
            {
                "non_profit": [],
                "for_profit": [],
            },
        )

    def test_type_custom_only_returns_custom_only(self):
        filters = {
            "type_start_date": "2026-01-01",
            "type_end_date": "2026-12-31",
        }

        with patch.object(
            analytics,
            "load_mock_data",
            return_value=self.sample_data,
        ):
            result = analytics.build_mock_response(
                filters
            )

        self.assertEqual(
            list(result.keys()),
            ["Custom"],
        )

        self.assertEqual(
            result["Custom"][
                "rating_distribution"
            ],
            [],
        )

        self.assertGreater(
            len(
                result["Custom"][
                    "organization_mix_trend"
                ]["non_profit"]
            ),
            0,
        )

    def test_both_custom_pairs_populate_both(self):
        filters = {
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-12-31",
            "type_start_date": "2026-01-01",
            "type_end_date": "2026-12-31",
        }

        with patch.object(
            analytics,
            "load_mock_data",
            return_value=self.sample_data,
        ):
            result = analytics.build_mock_response(
                filters
            )

        self.assertEqual(
            list(result.keys()),
            ["Custom"],
        )

        self.assertGreater(
            len(
                result["Custom"][
                    "rating_distribution"
                ]
            ),
            0,
        )

        self.assertGreater(
            len(
                result["Custom"][
                    "organization_mix_trend"
                ]["non_profit"]
            ),
            0,
        )

    def test_custom_rating_and_type_ranges_are_independent(self):
        filters = {
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-01-31",
            "type_start_date": "2026-02-01",
            "type_end_date": "2026-02-28",
        }

        result = analytics.build_custom_response(
            self.sample_data,
            filters,
        )

        ratings = result["Custom"][
            "rating_distribution"
        ]

        mix = result["Custom"][
            "organization_mix_trend"
        ]

        self.assertEqual(
            ratings,
            [
                {
                    "rating": 4,
                    "count": 2,
                }
            ],
        )

        self.assertTrue(
            len(mix["non_profit"]) > 0
            or len(mix["for_profit"]) > 0
        )

    def test_country_filter_applies_to_custom_rating(self):
        filters = {
            "country": "CAN",
            "rating_start_date": "2026-01-01",
            "rating_end_date": "2026-12-31",
        }

        with patch.object(
            analytics,
            "load_mock_data",
            return_value=self.sample_data,
        ):
            result = analytics.build_mock_response(
                filters
            )

        ratings = result["Custom"][
            "rating_distribution"
        ]

        self.assertEqual(
            ratings,
            [
                {
                    "rating": 3,
                    "count": 1,
                }
            ],
        )

    def test_custom_empty_range_returns_empty_arrays(self):
        filters = {
            "rating_start_date": "2030-01-01",
            "rating_end_date": "2030-01-31",
            "type_start_date": "2030-01-01",
            "type_end_date": "2030-01-31",
        }

        result = analytics.build_custom_response(
            self.sample_data,
            filters,
        )

        self.assertEqual(
            result["Custom"][
                "rating_distribution"
            ],
            [],
        )

        self.assertEqual(
            result["Custom"][
                "organization_mix_trend"
            ],
            {
                "non_profit": [],
                "for_profit": [],
            },
        )

    def test_one_row_data_does_not_crash(self):
        data = pd.DataFrame(
            [
                {
                    "org_id": "ORG-1",
                    "org_rating": 5,
                    "org_type": "non_profit",
                    "created_at": pd.Timestamp("2026-01-01"),
                    "country_code": "USA",
                    "country_name": "United States",
                }
            ]
        )

        ratings = analytics.build_rating_distribution(
            data
        )

        trend = analytics.build_organization_mix_trend(
            data,
            data,
            "daily",
            None,
        )

        self.assertEqual(
            ratings,
            [
                {
                    "rating": 5,
                    "count": 1,
                }
            ],
        )

        self.assertEqual(
            trend["non_profit"][0]["count"],
            1,
        )

    def test_lambda_missing_rating_end_returns_400(self):
        event = {
            "rating_start_date": "2026-01-01",
        }

        response = analytics.lambda_handler(
            event,
            None,
        )

        self.assertEqual(
            response["statusCode"],
            400,
        )

        body = json.loads(
            response["body"]
        )

        self.assertIn(
            "error",
            body,
        )

    def test_lambda_bad_date_returns_400(self):
        event = {
            "type_start_date": "bad-date",
            "type_end_date": "2026-01-31",
        }

        response = analytics.lambda_handler(
            event,
            None,
        )

        self.assertEqual(
            response["statusCode"],
            400,
        )

    def test_lambda_success_mock_mode(self):
        with patch.object(
            analytics,
            "USE_MOCK_DATA",
            True,
        ), patch.object(
            analytics,
            "build_mock_response",
            return_value={
                "7D": analytics.empty_chart_payload(),
                "30D": analytics.empty_chart_payload(),
                "1Y": analytics.empty_chart_payload(),
                "All": analytics.empty_chart_payload(),
                "Custom": analytics.empty_chart_payload(),
            },
        ):
            response = analytics.lambda_handler(
                {},
                None,
            )

        self.assertEqual(
            response["statusCode"],
            200,
        )

        body = json.loads(
            response["body"]
        )

        self.assertEqual(
            list(body.keys()),
            [
                "7D",
                "30D",
                "1Y",
                "All",
                "Custom",
            ],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)