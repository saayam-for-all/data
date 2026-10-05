import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


BASE = Path(__file__).resolve().parents[1]
HANDLER = runpy.run_path(
    str(BASE / "lambda_functions" / "rating_type_analytics.py"),
    run_name="rating_type_test",
)["lambda_handler"]


class RatingTypeAnalyticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

        environment = patch.dict(
            os.environ,
            {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": temporary.name},
        )
        environment.start()
        self.addCleanup(environment.stop)

        self.organizations = pd.DataFrame([
            {"org_id": 1, "org_rating": 3, "org_type": "Non-Profit",
             "state_id": 10, "created_at": "2024-01-01"},
            {"org_id": 2, "org_rating": 4, "org_type": "Non-Profit",
             "state_id": 10, "created_at": "2025-01-10"},
            {"org_id": 3, "org_rating": 5, "org_type": "For-profit",
             "state_id": 20, "created_at": "2025-02-02"},
        ])
        self.organizations.to_csv(
            self.directory / "organizations.csv", index=False
        )
        pd.DataFrame([
            {"state_id": 10, "country_id": 100},
            {"state_id": 20, "country_id": 200},
        ]).to_csv(self.directory / "state.csv", index=False)
        pd.DataFrame([
            {"country_id": 100, "country_code": "AFG",
             "country_name": "AFGHANISTAN"},
            {"country_id": 200, "country_code": "USA",
             "country_name": "UNITED STATES"},
        ]).to_csv(self.directory / "country.csv", index=False)

    def test_default_shape_and_sparse_cumulative_trend(self):
        response = HANDLER({}, None)
        self.assertEqual(response["statusCode"], 200)
        body = response["body"]
        self.assertEqual(list(body), ["7D", "30D", "1Y", "All", "Custom"])

        for bucket in body.values():
            self.assertEqual(
                set(bucket), {"rating_distribution", "organization_mix_trend"}
            )
            self.assertEqual(
                set(bucket["organization_mix_trend"]),
                {"non_profit", "for_profit"},
            )

        self.assertEqual(body["Custom"]["rating_distribution"], [])
        self.assertEqual(
            body["All"]["organization_mix_trend"]["non_profit"],
            [
                {"period": "2024-01", "count": 1},
                {"period": "2025-01", "count": 2},
            ],
        )
        self.assertEqual(
            body["All"]["organization_mix_trend"]["for_profit"],
            [{"period": "2025-02", "count": 1}],
        )

    def test_country_filters_both_charts(self):
        for country, expected in (("ALL", 3), ("AFG", 2), ("USA", 1)):
            with self.subTest(country=country):
                response = HANDLER({"country": country}, None)
                self.assertEqual(response["statusCode"], 200)
                bucket = response["body"]["All"]
                ratings = sum(
                    row["count"] for row in bucket["rating_distribution"]
                )
                trends = sum(
                    series[-1]["count"] if series else 0
                    for series in bucket["organization_mix_trend"].values()
                )
                self.assertEqual((ratings, trends), (expected, expected))

    def test_custom_pairs_are_independent(self):
        rating = {
            "rating_start_date": "2025-01-01",
            "rating_end_date": "2025-12-31",
        }
        org_type = {
            "type_start_date": "2025-01-01",
            "type_end_date": "2025-12-31",
        }

        rating_only = HANDLER(rating, None)
        self.assertEqual(list(rating_only["body"]), ["Custom"])
        self.assertEqual(
            rating_only["body"]["Custom"]["rating_distribution"],
            [{"rating": 4, "count": 1}, {"rating": 5, "count": 1}],
        )
        self.assertEqual(
            rating_only["body"]["Custom"]["organization_mix_trend"],
            {"non_profit": [], "for_profit": []},
        )

        type_only = HANDLER(org_type, None)
        self.assertEqual(list(type_only["body"]), ["Custom"])
        self.assertEqual(
            type_only["body"]["Custom"]["rating_distribution"], []
        )
        self.assertEqual(
            type_only["body"]["Custom"]["organization_mix_trend"]["non_profit"],
            [{"period": "2025-01-10", "count": 2}],
        )

        both = HANDLER({**rating, **org_type}, None)
        self.assertEqual(list(both["body"]), ["Custom"])
        self.assertEqual(
            both["body"]["Custom"]["rating_distribution"],
            rating_only["body"]["Custom"]["rating_distribution"],
        )
        self.assertEqual(
            both["body"]["Custom"]["organization_mix_trend"],
            type_only["body"]["Custom"]["organization_mix_trend"],
        )

    def test_invalid_date_pairs_return_400(self):
        cases = [
            {"rating_start_date": "2025-01-01"},
            {"type_start_date": "2025-13-01",
             "type_end_date": "2025-12-31"},
            {"rating_start_date": "2025-12-31",
             "rating_end_date": "2025-01-01"},
        ]
        for event in cases:
            with self.subTest(event=event):
                response = HANDLER(event, None)
                self.assertEqual(response["statusCode"], 400)
                self.assertIn("error", response["body"])

    def test_header_only_and_one_row_files(self):
        for count in (0, 1):
            with self.subTest(count=count):
                self.organizations.head(count).to_csv(
                    self.directory / "organizations.csv", index=False
                )
                response = HANDLER({}, None)
                self.assertEqual(response["statusCode"], 200)
                ratings = response["body"]["All"]["rating_distribution"]
                self.assertEqual(
                    sum(row["count"] for row in ratings), count
                )


if __name__ == "__main__":
    unittest.main()
