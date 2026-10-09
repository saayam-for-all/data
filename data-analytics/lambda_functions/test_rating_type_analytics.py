import contextlib
import io
import json
import os
import random
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import rating_type_analytics as api


class RatingTypeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        environment = patch.dict(
            os.environ,
            {
                "USE_MOCK_DATA": "true",
                "MOCK_DATA_DIR": str(self.root),
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.organizations = pd.DataFrame(
            [
                [1, 5, "non_profit", "TX", "2024-01-01"],
                [2, 4, "for_profit", "FL", "2025-12-01"],
                [3, 3, "non_profit", "TX", "2026-06-23"],
                [4, 4, "non_profit", "FL", "2026-06-24"],
                [5, 5, "for_profit", "DL", "2026-06-30"],
                [6, 2, "for_profit", "TX", "2026-06-30"],
                [7, 1, "non_profit", "DL", "2026-07-01"],
            ],
            columns=["org_id", "org_rating", "org_type", "state_id", "created_at"],
        )
        self.states = pd.DataFrame(
            [
                ["TX", 1],
                ["FL", 1],
                ["DL", 2],
            ],
            columns=["state_id", "country_id"],
        )
        self.countries = pd.DataFrame(
            [
                [1, "USA", "United States"],
                [2, "IND", "India"],
            ],
            columns=["country_id", "country_code", "country_name"],
        )
        self.write_tables()

    def write_tables(self):
        for name in ("organizations", "states", "countries"):
            getattr(self, name).to_csv(self.root / f"{name}.csv", index=False)

    def call(self, event, status=200):
        result = api.lambda_handler(event, None)
        self.assertEqual(result["statusCode"], status, result)
        self.assertEqual(result["headers"]["Content-Type"], "application/json")
        return json.loads(result["body"])

    def test_default_shape_and_empty_custom(self):
        result = self.call({})
        self.assertEqual(set(result), {"7D", "30D", "1Y", "All", "Custom"})
        for bucket in result.values():
            self.assertEqual(
                set(bucket), {"rating_distribution", "organization_mix_trend"}
            )
            self.assertEqual(
                set(bucket["organization_mix_trend"]), {"non_profit", "for_profit"}
            )
        self.assertEqual(
            result["Custom"],
            {
                "rating_distribution": [],
                "organization_mix_trend": {"non_profit": [], "for_profit": []},
            },
        )
        self.assertEqual(
            result["All"]["rating_distribution"],
            [
                {"rating": 1, "count": 1},
                {"rating": 2, "count": 1},
                {"rating": 3, "count": 1},
                {"rating": 4, "count": 2},
                {"rating": 5, "count": 2},
            ],
        )

    def test_rating_custom_only(self):
        result = self.call(
            {"rating_start_date": "2026-06-24", "rating_end_date": "2026-06-30"}
        )
        self.assertEqual(
            result,
            {
                "Custom": {
                    "rating_distribution": [
                        {"rating": 2, "count": 1},
                        {"rating": 4, "count": 1},
                        {"rating": 5, "count": 1},
                    ],
                    "organization_mix_trend": {"non_profit": [], "for_profit": []},
                }
            },
        )

    def test_type_custom_is_daily_sparse_and_cumulative(self):
        result = self.call(
            {"type_start_date": "2026-06-24", "type_end_date": "2026-06-30"}
        )
        self.assertEqual(
            result,
            {
                "Custom": {
                    "rating_distribution": [],
                    "organization_mix_trend": {
                        "non_profit": [{"period": "2026-06-24", "count": 3}],
                        "for_profit": [{"period": "2026-06-30", "count": 3}],
                    },
                }
            },
        )

    def test_both_custom_ranges_are_independent(self):
        result = self.call(
            {
                "body": json.dumps(
                    {
                        "rating_start_date": "2024-01-01",
                        "rating_end_date": "2024-12-31",
                        "type_start_date": "2026-06-24",
                        "type_end_date": "2026-06-30",
                    }
                ),
            }
        )
        self.assertEqual(set(result), {"Custom"})
        self.assertEqual(
            result["Custom"]["rating_distribution"], [{"rating": 5, "count": 1}]
        )
        self.assertEqual(
            result["Custom"]["organization_mix_trend"]["for_profit"],
            [{"period": "2026-06-30", "count": 3}],
        )

    def test_country_code_name_and_all(self):
        by_code = self.call({"country": " usa "})
        self.assertEqual(by_code, self.call({"country": "UNITED STATES"}))
        self.assertEqual(
            sum(row["count"] for row in by_code["All"]["rating_distribution"]), 5
        )
        self.assertEqual(self.call({}), self.call({"country": "all"}))
        missing = self.call({"country": "no such country"})
        self.assertEqual(missing["All"], missing["Custom"])

    def test_country_filters_custom_and_historical_baseline(self):
        result = self.call(
            {
                "country": "USA",
                "rating_start_date": "2026-06-24",
                "rating_end_date": "2026-06-30",
                "type_start_date": "2026-06-24",
                "type_end_date": "2026-06-30",
            }
        )
        self.assertEqual(
            result["Custom"]["rating_distribution"],
            [{"rating": 2, "count": 1}, {"rating": 4, "count": 1}],
        )
        self.assertEqual(
            result["Custom"]["organization_mix_trend"],
            {
                "non_profit": [{"period": "2026-06-24", "count": 3}],
                "for_profit": [{"period": "2026-06-30", "count": 2}],
            },
        )

    def test_country_file_can_have_only_code_or_name(self):
        for column, value in (
            ("country_code", "USA"),
            ("country_name", "United States"),
        ):
            with self.subTest(column=column):
                self.countries[["country_id", column]].to_csv(
                    self.root / "countries.csv", index=False
                )
                result = self.call({"country": value})
                self.assertEqual(
                    sum(row["count"] for row in result["All"]["rating_distribution"]), 5
                )

    def test_fixed_windows_and_monthly_totals(self):
        result = api.build_analytics(api.load_data(), today="2026-06-30")
        self.assertEqual(
            result["7D"]["organization_mix_trend"],
            {
                "non_profit": [{"period": "2026-06-24", "count": 3}],
                "for_profit": [{"period": "2026-06-30", "count": 3}],
            },
        )
        self.assertEqual(
            result["30D"]["organization_mix_trend"]["non_profit"],
            [
                {"period": "2026-06-23", "count": 2},
                {"period": "2026-06-24", "count": 3},
            ],
        )
        self.assertEqual(
            result["1Y"]["organization_mix_trend"],
            {
                "non_profit": [{"period": "2026-06", "count": 3}],
                "for_profit": [
                    {"period": "2025-12", "count": 1},
                    {"period": "2026-06", "count": 3},
                ],
            },
        )
        self.assertEqual(
            result["All"]["organization_mix_trend"]["non_profit"][-1],
            {"period": "2026-07", "count": 4},
        )

    def test_partial_month_excludes_later_creations(self):
        result = api.build_analytics(api.load_data(), today="2026-06-23")
        self.assertEqual(
            result["1Y"]["organization_mix_trend"]["non_profit"],
            [{"period": "2026-06", "count": 2}],
        )

    def test_inclusive_end_day_and_iso_timezone_offsets(self):
        self.organizations.loc[4, "created_at"] = "2026-06-30T23:59:59Z"
        self.organizations.loc[6, "created_at"] = "2026-07-01T00:30:00+01:00"
        self.write_tables()
        result = self.call(
            {"type_start_date": "2026-06-30", "type_end_date": "2026-06-30"}
        )
        self.assertEqual(
            result["Custom"]["organization_mix_trend"],
            {
                "non_profit": [{"period": "2026-06-30", "count": 4}],
                "for_profit": [{"period": "2026-06-30", "count": 3}],
            },
        )

    def test_empty_and_single_row_data(self):
        for size in (0, 1):
            self.organizations.head(size).to_csv(
                self.root / "organizations.csv", index=False
            )
            for event in (
                {},
                {
                    "rating_start_date": "2024-01-01",
                    "rating_end_date": "2024-01-01",
                    "type_start_date": "2024-01-01",
                    "type_end_date": "2024-01-01",
                },
            ):
                with self.subTest(size=size, event=event):
                    result = self.call(event)
                    bucket = result["All"] if "All" in result else result["Custom"]
                    self.assertEqual(
                        bucket["rating_distribution"],
                        [{"rating": 5, "count": 1}] if size else [],
                    )
                    self.assertEqual(bucket["organization_mix_trend"]["for_profit"], [])

    def test_no_activity_returns_empty_arrays(self):
        result = self.call(
            {
                "rating_start_date": "2020-01-01",
                "rating_end_date": "2020-01-02",
                "type_start_date": "2020-01-01",
                "type_end_date": "2020-01-02",
            }
        )
        self.assertEqual(result["Custom"], self.call({})["Custom"])

    def test_invalid_dates_and_incomplete_pairs(self):
        for prefix in ("rating", "type"):
            start, end = f"{prefix}_start_date", f"{prefix}_end_date"
            for payload in (
                {start: "2026-01-01"},
                {end: "2026-01-01"},
                {start: None, end: "2026-01-01"},
                {start: "2026-02-30", end: "2026-03-01"},
                {start: "2026-02-01", end: "2026-01-01"},
                {start: "2026-1-01", end: "2026-01-31"},
                {start: [], end: "2026-01-01"},
                {start: "9999-12-31", end: "9999-12-31"},
            ):
                with (
                    self.subTest(payload=payload),
                    patch.object(api, "load_data") as loader,
                ):
                    self.assertEqual(set(self.call(payload, 400)), {"error"})
                    loader.assert_not_called()

    def test_invalid_second_pair_does_not_return_partial_result(self):
        self.call(
            {
                "rating_start_date": "2026-01-01",
                "rating_end_date": "2026-06-30",
                "type_start_date": "bad",
            },
            400,
        )

    def test_invalid_filters_and_bodies(self):
        for event in (
            None,
            [],
            {"body": "{"},
            {"body": "[]"},
            {"body": "null"},
            {"body": 1},
            {"country": None},
            {"country": []},
            {"country": " "},
            {"time_filter": "7D"},
            {"organization_type": "non_profit"},
        ):
            with self.subTest(event=event):
                self.call(event, 400)
        for event in ({"body": None}, {"body": ""}, {"body": {}}, {"body": "{}"}):
            self.assertEqual(self.call(event), self.call({}))

    def test_invalid_data_returns_generic_error(self):
        for field, value in (
            ("org_rating", "4.5"),
            ("org_rating", "6"),
            ("org_rating", None),
            ("org_type", "other"),
            ("created_at", "bad"),
        ):
            with self.subTest(field=field, value=value):
                rows = self.organizations.astype(object).copy()
                rows.loc[0, field] = value
                rows.to_csv(self.root / "organizations.csv", index=False)
                with self.assertLogs(level="ERROR"):
                    self.assertEqual(
                        self.call({}, 500), {"error": "Unable to load analytics data"}
                    )

    def test_duplicate_lookups_cannot_multiply_counts(self):
        pd.concat([self.states, self.states.iloc[:1]]).to_csv(
            self.root / "states.csv", index=False
        )
        with self.assertLogs(level="ERROR"):
            self.call({}, 500)

    def test_existing_csv_type_labels(self):
        self.organizations["org_type"] = self.organizations.org_type.map(
            {"non_profit": "Non-Profit", "for_profit": "For-profit"}
        )
        self.write_tables()
        self.assertEqual(set(api.load_data().org_type), {"non_profit", "for_profit"})

    def test_mock_path_runs_without_psycopg2(self):
        with patch.dict(sys.modules, {"psycopg2": None, "psycopg2.sql": None}):
            namespace = runpy.run_path(api.__file__)
            self.assertIsNone(namespace["psycopg2"])
            self.assertEqual(namespace["lambda_handler"]({}, None)["statusCode"], 200)

    def test_database_mode_requires_driver(self):
        with (
            patch.dict(os.environ, {"USE_MOCK_DATA": "false"}),
            patch.object(api, "psycopg2", None),
            self.assertLogs(level="ERROR"),
        ):
            self.call({}, 500)

    @unittest.skipIf(api.psycopg2 is None, "Optional psycopg2 driver not installed")
    def test_database_path_matches_csv_and_closes_connection(self):
        expected = self.call({})
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        organizations = self.organizations.copy()
        organizations["created_at"] = pd.to_datetime(organizations.created_at)
        tables = [organizations, self.states, self.countries]
        cursor.fetchall.side_effect = [
            list(frame.itertuples(index=False, name=None)) for frame in tables
        ]
        descriptions = iter(
            [[(column,) for column in frame.columns] for frame in tables]
        )
        cursor.execute.side_effect = lambda query: setattr(
            cursor, "description", next(descriptions)
        )
        with (
            patch.dict(os.environ, {"USE_MOCK_DATA": "false"}),
            patch.object(api.psycopg2, "connect", return_value=connection),
        ):
            self.assertEqual(self.call({}), expected)
        self.assertEqual(cursor.execute.call_count, 3)
        connection.close.assert_called_once()
        connection.set_session.assert_called_once_with(
            readonly=True, isolation_level="REPEATABLE READ"
        )

    @unittest.skipIf(api.psycopg2 is None, "Optional psycopg2 driver not installed")
    def test_database_failure_closes_connection(self):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.execute.side_effect = (
            RuntimeError("private error")
        )
        with (
            patch.dict(os.environ, {"USE_MOCK_DATA": "false"}),
            patch.object(api.psycopg2, "connect", return_value=connection),
            self.assertLogs(level="ERROR"),
        ):
            self.assertEqual(
                self.call({}, 500), {"error": "Unable to load analytics data"}
            )
        connection.close.assert_called_once()

    def test_local_samples_print_five_successful_responses(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            runpy.run_path(api.__file__, run_name="__main__")
        self.assertEqual(output.getvalue().count('"statusCode": 200'), 5)

    def test_leap_year_and_timezone_reference_day(self):
        data = api.load_data().iloc[:3].copy()
        data["created_at"] = pd.to_datetime(
            ["2023-02-28", "2023-03-01", "2024-02-29"], utc=True
        )
        data["org_type"] = "non_profit"
        result = api.build_analytics(data, today="2024-02-29")
        self.assertEqual(
            result["1Y"]["organization_mix_trend"]["non_profit"],
            [{"period": "2023-03", "count": 2}, {"period": "2024-02", "count": 3}],
        )
        self.assertEqual(
            result, api.build_analytics(data, today="2024-03-01T00:30:00+01:00")
        )

    def test_missing_country_join_preserves_all_totals(self):
        self.organizations.loc[0, "state_id"] = "UNKNOWN"
        self.write_tables()
        all_rows = self.call({})["All"]["rating_distribution"]
        usa_rows = self.call({"country": "USA"})["All"]["rating_distribution"]
        self.assertEqual(sum(row["count"] for row in all_rows), 7)
        self.assertEqual(sum(row["count"] for row in usa_rows), 4)

    def test_missing_csv_returns_generic_error(self):
        with (
            patch.dict(os.environ, {"MOCK_DATA_DIR": str(self.root / "missing")}),
            self.assertLogs(level="ERROR"),
        ):
            self.assertEqual(
                self.call({}, 500), {"error": "Unable to load analytics data"}
            )

    def test_randomized_results_match_row_by_row_reference(self):
        rng = random.Random(380)
        for _ in range(10):
            rows = [
                {
                    "created_at": pd.Timestamp("2024-01-01", tz="UTC")
                    + pd.Timedelta(hours=rng.randrange(24000)),
                    "org_type": rng.choice(["non_profit", "for_profit"]),
                    "org_rating": rng.randrange(1, 6),
                    "country_code": rng.choice(["USA", "IND"]),
                }
                for _ in range(60)
            ]
            data = pd.DataFrame(rows)
            end = pd.Timestamp("2026-07-01", tz="UTC")
            windows = {
                "7D": (end - pd.Timedelta(days=7), end),
                "30D": (end - pd.Timedelta(days=30), end),
                "1Y": (end - pd.DateOffset(years=1), end),
                "All": None,
            }
            for country in ("all", "usa"):
                actual = api.build_analytics(data, country=country, today="2026-06-30")
                history = [
                    row
                    for row in rows
                    if country == "all" or row["country_code"].lower() == country
                ]
                for key, window in windows.items():
                    selected = [
                        row
                        for row in history
                        if window is None or window[0] <= row["created_at"] < window[1]
                    ]
                    ratings = [
                        {
                            "rating": rating,
                            "count": sum(
                                row["org_rating"] == rating for row in selected
                            ),
                        }
                        for rating in sorted({row["org_rating"] for row in selected})
                    ]
                    self.assertEqual(actual[key]["rating_distribution"], ratings)
                    fmt = "%Y-%m" if key in ("1Y", "All") else "%Y-%m-%d"
                    for org_type in ("non_profit", "for_profit"):
                        periods = sorted(
                            {
                                row["created_at"].strftime(fmt)
                                for row in selected
                                if row["org_type"] == org_type
                            }
                        )
                        expected = [
                            {
                                "period": period,
                                "count": sum(
                                    row["org_type"] == org_type
                                    and row["created_at"].strftime(fmt) <= period
                                    and (
                                        window is None or row["created_at"] < window[1]
                                    )
                                    for row in history
                                ),
                            }
                            for period in periods
                        ]
                        self.assertEqual(
                            actual[key]["organization_mix_trend"][org_type], expected
                        )


if __name__ == "__main__":
    unittest.main()
