import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(
    0,
    r".\data-analytics\lambda_functions"
)

import organization_analytics as analytics


class TestOrganizationAnalytics(unittest.TestCase):

    def test_7d_filter(self):
        condition, params = analytics.build_date_filter("7D")

        self.assertIn("7 days", condition)
        self.assertEqual(params, [])

    def test_30d_filter(self):
        condition, params = analytics.build_date_filter("30D")

        self.assertIn("30 days", condition)
        self.assertEqual(params, [])

    def test_1y_filter(self):
        condition, params = analytics.build_date_filter("1Y")

        self.assertIn("1 year", condition)
        self.assertEqual(params, [])

    def test_all_filter(self):
        condition, params = analytics.build_date_filter("ALL")

        self.assertEqual(condition, "")
        self.assertEqual(params, [])

    def test_custom_filter(self):
        condition, params = analytics.build_date_filter(
            "CUSTOM",
            "2026-07-01",
            "2026-07-31"
        )

        self.assertEqual(
            condition,
            "o.created_at BETWEEN %s AND %s"
        )

        self.assertEqual(
            params,
            ["2026-07-01", "2026-07-31"]
        )

    def test_custom_requires_dates(self):
        with self.assertRaises(ValueError):
            analytics.build_date_filter("CUSTOM")

    def test_invalid_time_filter(self):
        with self.assertRaises(ValueError):
            analytics.build_date_filter("INVALID")

    def test_combined_filters(self):
        where_clause, params = analytics.build_filters({
            "time_filter": "30D",
            "org_type": "Non-Profit",
            "org_size": "Small",
            "state_id": "NY",
            "city_name": "Buffalo",
            "org_rating": 5,
            "is_collaborator": True
        })

        self.assertIn("o.created_at", where_clause)
        self.assertIn("o.org_type = %s", where_clause)
        self.assertIn("o.org_size = %s", where_clause)
        self.assertIn("o.state_id = %s", where_clause)
        self.assertIn("o.city_name = %s", where_clause)
        self.assertIn("o.org_rating = %s", where_clause)
        self.assertIn("o.is_collaborator = %s", where_clause)

        self.assertEqual(
            params,
            [
                "Non-Profit",
                "Small",
                "NY",
                "Buffalo",
                5,
                True
            ]
        )

    def test_contributor_filter_not_available(self):
        with self.assertRaises(ValueError):
            analytics.build_filters({
                "time_filter": "ALL",
                "is_contributor": True
            })

    def test_total_organizations(self):
        cursor = MagicMock()

        cursor.fetchone.return_value = {
            "total": 120
        }

        result = analytics.get_total_organizations(
            cursor,
            {
                "time_filter": "ALL"
            }
        )

        self.assertEqual(result, 120)

    def test_rating_distribution_returns_1_to_5(self):
        cursor = MagicMock()

        cursor.fetchall.return_value = [
            {
                "rating": 1,
                "count": 3
            },
            {
                "rating": 3,
                "count": 7
            },
            {
                "rating": 5,
                "count": 4
            }
        ]

        result = analytics.get_rating_distribution(
            cursor,
            {
                "time_filter": "ALL"
            }
        )

        self.assertEqual(
            result,
            [
                {"rating": 1, "count": 3},
                {"rating": 2, "count": 0},
                {"rating": 3, "count": 7},
                {"rating": 4, "count": 0},
                {"rating": 5, "count": 4}
            ]
        )

    @patch.object(
        analytics,
        "get_organizations_by_location",
        return_value=[]
    )
    @patch.object(
        analytics,
        "get_organization_registration_trend",
        return_value=[]
    )
    @patch.object(
        analytics,
        "get_contributor_distribution",
        return_value=[]
    )
    @patch.object(
        analytics,
        "get_collaborator_distribution",
        return_value=[
            {
                "is_collaborator": True,
                "count": 3
            },
            {
                "is_collaborator": False,
                "count": 7
            }
        ]
    )
    @patch.object(
        analytics,
        "get_organizations_by_size",
        return_value=[]
    )
    @patch.object(
        analytics,
        "get_organizations_by_type",
        return_value=[
            {
                "org_type": "Non-Profit",
                "count": 6
            },
            {
                "org_type": "For-profit",
                "count": 4
            }
        ]
    )
    @patch.object(
        analytics,
        "get_total_organizations",
        return_value=10
    )
    def test_overview_response_structure(
        self,
        mock_total,
        mock_type,
        mock_size,
        mock_collaborator,
        mock_contributor,
        mock_trend,
        mock_location
    ):
        cursor = MagicMock()

        result = analytics.build_overview_dashboard(
            cursor,
            {
                "time_filter": "ALL",
                "group_by": "daily"
            }
        )

        overview = result["organization_overview"]

        self.assertEqual(
            overview["summary"]["total_organizations"],
            10
        )

        self.assertEqual(
            overview["summary"]["non_profit_organizations"],
            6
        )

        self.assertEqual(
            overview["summary"]["for_profit_organizations"],
            4
        )

        self.assertEqual(
            overview["summary"]["collaborator_organizations"],
            3
        )

        self.assertEqual(
            overview["summary"]["non_collaborator_organizations"],
            7
        )

        self.assertIn(
            "organization_activity_trend",
            overview
        )

        self.assertIn(
            "organizations_by_location",
            overview
        )

    @patch.object(
        analytics,
        "get_ratings_by_organization_size",
        return_value=[]
    )
    @patch.object(
        analytics,
        "get_ratings_by_organization_type",
        return_value=[]
    )
    @patch.object(
        analytics,
        "get_top_contributor_organizations",
        return_value=[]
    )
    @patch.object(
        analytics,
        "get_top_collaborator_organizations",
        return_value=[]
    )
    @patch.object(
        analytics,
        "get_organizations_without_ratings",
        return_value=[]
    )
    @patch.object(
        analytics,
        "get_top_rated_organizations",
        return_value=[]
    )
    @patch.object(
        analytics,
        "get_rating_distribution",
        return_value=[]
    )
    @patch.object(
        analytics,
        "get_rating_summary",
        return_value={
            "average_rating": 4.2,
            "rated_organizations": 8,
            "unrated_organizations": 2,
            "five_star_organizations": 3
        }
    )
    def test_performance_response_structure(
        self,
        mock_summary,
        mock_distribution,
        mock_top_rated,
        mock_without_ratings,
        mock_collaborators,
        mock_contributors,
        mock_by_type,
        mock_by_size
    ):
        cursor = MagicMock()

        result = analytics.build_performance_dashboard(
            cursor,
            {
                "time_filter": "ALL"
            }
        )

        performance = result["organization_performance"]

        self.assertEqual(
            performance["summary"]["average_rating"],
            4.2
        )

        self.assertEqual(
            performance["summary"]["rated_organizations"],
            8
        )

        self.assertIn(
            "rating_distribution",
            performance
        )

        self.assertIn(
            "top_rated_organizations",
            performance
        )

        self.assertIn(
            "organizations_without_ratings",
            performance
        )

        self.assertIn(
            "top_collaborator_organizations",
            performance
        )

        self.assertIn(
            "top_contributor_organizations",
            performance
        )

        self.assertIn(
            "ratings_by_organization_type",
            performance
        )

        self.assertIn(
            "ratings_by_organization_size",
            performance
        )


if __name__ == "__main__":
    unittest.main()