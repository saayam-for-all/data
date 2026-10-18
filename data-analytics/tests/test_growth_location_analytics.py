"""Local acceptance tests for issue #336."""

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd


FUNCTION_FOLDER = (
    Path(__file__).resolve().parents[1] / "lambda_functions"
)
sys.path.insert(0, str(FUNCTION_FOLDER))

import growth_location_analytics as api


class FrozenDate(date):
    """Keep time-dependent tests consistent."""

    @classmethod
    def today(cls):
        return cls(2026, 10, 3)


def org(org_id, created_at, state_id="TX", collaborator=False):
    return {
        "org_id": org_id,
        "state_id": state_id,
        "created_at": created_at,
        "is_collaborator": collaborator,
    }


class GrowthLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp_folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_folder.cleanup)

        self.folder = Path(self.temp_folder.name)

        environment = patch.dict(
            os.environ,
            {"MOCK_DATA_DIR": str(self.folder)},
        )
        environment.start()
        self.addCleanup(environment.stop)

        clock = patch.object(api, "date", FrozenDate)
        clock.start()
        self.addCleanup(clock.stop)

        self.write_data([
            org("1", "2024-01-01", "TX", True),
            org("2", "2026-09-27", "FL", True),
            org("3", "2026-10-03 23:59:59", "MH", False),
            org("4", "2026-10-04", "TX", True),
        ])

    def write_data(self, rows):
        columns = [
            "org_id",
            "state_id",
            "created_at",
            "is_collaborator",
        ]

        pd.DataFrame(rows, columns=columns).to_csv(
            self.folder / "organizations.csv",
            index=False,
        )

        pd.DataFrame([
            {"state_id": "TX", "country_id": "1"},
            {"state_id": "FL", "country_id": "1"},
            {"state_id": "MH", "country_id": "2"},
        ]).to_csv(self.folder / "state.csv", index=False)

        pd.DataFrame([
            {"country_id": "1", "country_code": "USA"},
            {"country_id": "2", "country_code": "IND"},
        ]).to_csv(self.folder / "country.csv", index=False)

    def call_handler(self, event):
        response = api.lambda_handler(event, None)
        return response["statusCode"], json.loads(response["body"])

    def test_no_body_and_exact_response_keys(self):
        for event in ({}, {"body": None}):
            with self.subTest(event=event):
                status, payload = self.call_handler(event)

                self.assertEqual(status, 200)
                self.assertEqual(
                    set(payload),
                    {"7D", "30D", "1Y", "All", "Custom"},
                )

                for bucket in payload.values():
                    self.assertEqual(
                        set(bucket),
                        {"growth_trend", "organizations_by_location"},
                    )
                    self.assertEqual(
                        set(bucket["growth_trend"]),
                        {"total_organizations", "collaborators"},
                    )

                self.assertEqual(
                    payload["Custom"],
                    {
                        "growth_trend": {
                            "total_organizations": [],
                            "collaborators": [],
                        },
                        "organizations_by_location": [],
                    },
                )

    def test_custom_ranges_are_independent(self):
        growth = {
            "start_date": "2026-10-03",
            "end_date": "2026-10-03",
        }
        location = {
            "location_start_date": "2024-01-01",
            "location_end_date": "2024-01-01",
        }

        _, payload = self.call_handler(growth)
        self.assertEqual(
            payload["Custom"]["growth_trend"]["total_organizations"],
            [{"period": "2026-10-03", "count": 3}],
        )
        self.assertEqual(
            payload["Custom"]["organizations_by_location"], []
        )

        _, payload = self.call_handler(location)
        self.assertEqual(
            payload["Custom"]["growth_trend"]["total_organizations"], []
        )
        self.assertEqual(
            payload["Custom"]["organizations_by_location"],
            [{"country": "USA", "count": 1}],
        )

        _, payload = self.call_handler({**growth, **location})
        self.assertEqual(
            payload["Custom"]["growth_trend"]["total_organizations"][0]["count"],
            3,
        )
        self.assertEqual(
            payload["Custom"]["organizations_by_location"],
            [{"country": "USA", "count": 1}],
        )

    def test_invalid_dates_for_both_charts(self):
        for start_key, end_key in (
            ("start_date", "end_date"),
            ("location_start_date", "location_end_date"),
        ):
            for start, end in (
                ("2026/01/01", "2026-01-31"),
                ("2026-02-30", "2026-03-01"),
                ("2026-12-31", "2026-01-01"),
                ("2026-1-1", "2026-01-31"),
            ):
                with self.subTest(start_key=start_key, start=start):
                    status, payload = self.call_handler({
                        start_key: start,
                        end_key: end,
                    })
                    self.assertEqual(status, 400)
                    self.assertEqual(set(payload), {"error"})

    def test_daily_window_and_running_total(self):
        _, payload = self.call_handler({})

        self.assertEqual(
            payload["7D"]["growth_trend"]["total_organizations"],
            [
                {"period": "2026-09-27", "count": 2},
                {"period": "2026-10-03", "count": 3},
            ],
        )
        self.assertEqual(
            payload["7D"]["growth_trend"]["collaborators"],
            [
                {"period": "2026-09-27", "count": 1},
                {"period": "2026-10-03", "count": 0},
            ],
        )
        self.assertEqual(
            payload["30D"]["growth_trend"],
            payload["7D"]["growth_trend"],
        )

    def test_monthly_totals_and_all_history(self):
        _, payload = self.call_handler({})

        self.assertEqual(
            payload["1Y"]["growth_trend"]["total_organizations"],
            [
                {"period": "2026-09", "count": 2},
                {"period": "2026-10", "count": 3},
            ],
        )
        self.assertEqual(
            payload["All"]["growth_trend"]["total_organizations"][-1],
            {"period": "2026-10", "count": 4},
        )

    def test_country_rollup_and_window_scoping(self):
        _, payload = self.call_handler({})

        # TX and FL contribute to the same USA row.
        self.assertEqual(
            payload["All"]["organizations_by_location"],
            [
                {"country": "USA", "count": 3},
                {"country": "IND", "count": 1},
            ],
        )
        self.assertEqual(
            payload["7D"]["organizations_by_location"],
            [
                {"country": "IND", "count": 1},
                {"country": "USA", "count": 1},
            ],
        )

    def test_top_four_countries(self):
        data = pd.DataFrame({
            "created_at": pd.to_datetime(["2026-01-01"] * 6),
            "country_code": ["USA", "USA", "IND", "CAN", "GBR", "AUS"],
        })

        locations = api.build_organizations_by_location(data)

        self.assertEqual(
            locations,
            [
                {"country": "USA", "count": 2},
                {"country": "AUS", "count": 1},
                {"country": "CAN", "count": 1},
                {"country": "GBR", "count": 1},
            ],
        )

    def test_empty_and_one_row_csv(self):
        self.write_data([])

        status, payload = self.call_handler({})
        self.assertEqual(status, 200)

        for bucket in payload.values():
            self.assertEqual(
                bucket,
                {
                    "growth_trend": {
                        "total_organizations": [],
                        "collaborators": [],
                    },
                    "organizations_by_location": [],
                },
            )

        self.write_data([org("1", "2024-01-01")])

        status, payload = self.call_handler({})
        self.assertEqual(status, 200)
        self.assertEqual(
            payload["All"]["growth_trend"]["total_organizations"],
            [{"period": "2024-01", "count": 1}],
        )
        self.assertEqual(
            payload["7D"]["growth_trend"]["total_organizations"], []
        )

    def test_json_request_body(self):
        status, payload = self.call_handler({
            "body": json.dumps({
                "start_date": "2026-10-03",
                "end_date": "2026-10-03",
            })
        })

        self.assertEqual(status, 200)
        self.assertEqual(
            payload["Custom"]["growth_trend"]["total_organizations"],
            [{"period": "2026-10-03", "count": 3}],
        )


if __name__ == "__main__":
    unittest.main()
