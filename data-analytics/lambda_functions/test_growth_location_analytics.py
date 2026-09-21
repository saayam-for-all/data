"""Unit tests for growth_location_analytics.py (issue #336)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import growth_location_analytics as gla

REFERENCE = pd.Timestamp("2026-06-15")


def _write_csv(path: Path, header, rows) -> None:
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(str(value) for value in row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_dataset(tmp: Path, organizations, states=None, countries=None):
    states = states if states is not None else [
        ("US-TX", "Texas", "1"),
        ("US-FL", "Florida", "1"),
        ("IN-DL", "Delhi", "2"),
        ("GB-LDN", "London", "3"),
        ("CA-ON", "Ontario", "4"),
        ("AU-NSW", "New South Wales", "5"),
    ]
    countries = countries if countries is not None else [
        ("1", "USA"),
        ("2", "IND"),
        ("3", "GBR"),
        ("4", "CAN"),
        ("5", "AUS"),
    ]
    _write_csv(
        tmp / "organizations.csv",
        ["org_id", "state_id", "city_name", "is_collaborator", "created_at"],
        organizations,
    )
    _write_csv(tmp / "states.csv", ["state_id", "state_name", "country_id"], states)
    _write_csv(tmp / "countries.csv", ["country_id", "country_code"], countries)
    return gla.load_organizations(data_dir=str(tmp))


def _days_before(days: int) -> str:
    return (REFERENCE - pd.Timedelta(days=days)).strftime("%Y-%m-%d")


class GrowthLocationAnalyticsTests(unittest.TestCase):
    def test_no_body_returns_all_five_keys_and_empty_custom(self):
        with tempfile.TemporaryDirectory() as tmp:
            orgs = _write_dataset(
                Path(tmp),
                [("ORG-1", "US-TX", "Austin", "TRUE", _days_before(40))],
            )
            response = gla.build_growth_location_response(orgs, {}, reference_date=REFERENCE)

        self.assertEqual(set(response), {"7D", "30D", "1Y", "All", "Custom"})
        self.assertEqual(
            response["7D"]["growth_trend"],
            {"total_organizations": [], "collaborators": []},
        )
        self.assertEqual(response["7D"]["organizations_by_location"], [])
        self.assertEqual(
            response["30D"]["growth_trend"],
            {"total_organizations": [], "collaborators": []},
        )
        self.assertEqual(len(response["1Y"]["growth_trend"]["total_organizations"]), 1)
        self.assertEqual(response["1Y"]["organizations_by_location"], [{"country": "USA", "count": 1}])
        self.assertEqual(
            response["Custom"],
            {
                "growth_trend": {"total_organizations": [], "collaborators": []},
                "organizations_by_location": [],
            },
        )

    def test_custom_growth_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            orgs = _write_dataset(
                Path(tmp),
                [
                    ("ORG-1", "US-TX", "Austin", "TRUE", "2026-02-10"),
                    ("ORG-2", "IN-DL", "Delhi", "FALSE", "2026-03-05"),
                    ("ORG-3", "US-FL", "Miami", "TRUE", "2025-06-01"),
                ],
            )
            response = gla.build_growth_location_response(
                orgs,
                {"start_date": "2026-01-01", "end_date": "2026-06-30"},
                reference_date=REFERENCE,
            )

        custom = response["Custom"]
        self.assertTrue(custom["growth_trend"]["total_organizations"])
        self.assertEqual(custom["organizations_by_location"], [])
        periods = [row["period"] for row in custom["growth_trend"]["total_organizations"]]
        self.assertTrue(all(len(period) == 10 for period in periods))

    def test_custom_location_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            orgs = _write_dataset(
                Path(tmp),
                [
                    ("ORG-1", "US-TX", "Austin", "TRUE", "2025-03-01"),
                    ("ORG-2", "IN-DL", "Delhi", "FALSE", "2025-08-01"),
                    ("ORG-3", "US-FL", "Miami", "TRUE", "2026-02-01"),
                ],
            )
            response = gla.build_growth_location_response(
                orgs,
                {"location_start_date": "2025-01-01", "location_end_date": "2025-12-31"},
                reference_date=REFERENCE,
            )

        custom = response["Custom"]
        self.assertEqual(
            custom["growth_trend"],
            {"total_organizations": [], "collaborators": []},
        )
        self.assertEqual(
            custom["organizations_by_location"],
            [{"country": "IND", "count": 1}, {"country": "USA", "count": 1}],
        )

    def test_custom_both_ranges_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            orgs = _write_dataset(
                Path(tmp),
                [
                    ("ORG-1", "US-TX", "Austin", "TRUE", "2026-02-10"),
                    ("ORG-2", "IN-DL", "Delhi", "FALSE", "2025-05-01"),
                ],
            )
            response = gla.build_growth_location_response(
                orgs,
                {
                    "start_date": "2026-01-01",
                    "end_date": "2026-06-30",
                    "location_start_date": "2025-01-01",
                    "location_end_date": "2025-12-31",
                },
                reference_date=REFERENCE,
            )

        custom = response["Custom"]
        self.assertTrue(custom["growth_trend"]["total_organizations"])
        self.assertEqual(custom["organizations_by_location"], [{"country": "IND", "count": 1}])

    def test_invalid_dates_return_400(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_dataset(Path(tmp), [("ORG-1", "US-TX", "Austin", "TRUE", "2026-01-01")])
            with mock.patch.dict("os.environ", {"MOCK_DATA_DIR": tmp}):
                inverted = gla.lambda_handler(
                    {"start_date": "2026-06-30", "end_date": "2026-01-01"}, None
                )
                bad_format = gla.lambda_handler(
                    {"location_start_date": "not-a-date", "location_end_date": "2026-01-01"},
                    None,
                )
                incomplete = gla.lambda_handler({"start_date": "2026-01-01"}, None)

        self.assertEqual(inverted["statusCode"], 400)
        self.assertIn("error", json.loads(inverted["body"]))
        self.assertEqual(bad_format["statusCode"], 400)
        self.assertEqual(incomplete["statusCode"], 400)

    def test_total_organizations_cumulative_collaborators_per_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            orgs = _write_dataset(
                Path(tmp),
                [
                    ("ORG-1", "US-TX", "Austin", "TRUE", "2026-01-10"),
                    ("ORG-2", "US-FL", "Miami", "FALSE", "2026-02-10"),
                    ("ORG-3", "IN-DL", "Delhi", "TRUE", "2026-02-20"),
                    ("ORG-4", "US-TX", "Dallas", "TRUE", "2026-03-05"),
                ],
            )
            growth = gla.build_growth_trend(orgs, None, None, "month")

        totals = [row["count"] for row in growth["total_organizations"]]
        collabs = [row["count"] for row in growth["collaborators"]]
        self.assertEqual(totals, sorted(totals))
        self.assertEqual(totals[-1], 4)
        self.assertEqual(sum(collabs), 3)
        self.assertNotEqual(collabs, totals)
        self.assertEqual(
            [row["period"] for row in growth["total_organizations"]],
            [row["period"] for row in growth["collaborators"]],
        )

    def test_day_vs_month_granularity(self):
        with tempfile.TemporaryDirectory() as tmp:
            orgs = _write_dataset(
                Path(tmp),
                [
                    ("ORG-1", "US-TX", "Austin", "TRUE", _days_before(2)),
                    ("ORG-2", "US-FL", "Miami", "FALSE", _days_before(20)),
                    ("ORG-3", "IN-DL", "Delhi", "TRUE", _days_before(100)),
                ],
            )
            response = gla.build_growth_location_response(orgs, {}, reference_date=REFERENCE)

        for bucket in ("7D", "30D"):
            periods = [
                row["period"] for row in response[bucket]["growth_trend"]["total_organizations"]
            ]
            self.assertTrue(all(len(period) == 10 for period in periods), bucket)

        for bucket in ("1Y", "All"):
            periods = [
                row["period"] for row in response[bucket]["growth_trend"]["total_organizations"]
            ]
            self.assertTrue(all(len(period) == 7 for period in periods), bucket)

    def test_location_aggregates_by_country_top_4_no_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            orgs = _write_dataset(
                Path(tmp),
                [
                    ("ORG-1", "US-TX", "Austin", "TRUE", "2026-01-01"),
                    ("ORG-2", "US-FL", "Miami", "TRUE", "2026-01-02"),
                    ("ORG-3", "IN-DL", "Delhi", "FALSE", "2026-01-03"),
                    ("ORG-4", "GB-LDN", "London", "FALSE", "2026-01-04"),
                    ("ORG-5", "CA-ON", "Toronto", "FALSE", "2026-01-05"),
                    ("ORG-6", "AU-NSW", "Sydney", "FALSE", "2026-01-06"),
                    ("ORG-7", "AU-NSW", "Newcastle", "FALSE", "2026-01-07"),
                ],
            )
            locations = gla.build_organizations_by_location(orgs, None, None)

        self.assertLessEqual(len(locations), 4)
        # USA and AUS both have count 2; ties break by country code ascending.
        self.assertEqual(locations[0], {"country": "AUS", "count": 2})
        self.assertEqual(locations[1], {"country": "USA", "count": 2})
        self.assertNotIn("Other", {row["country"] for row in locations})
        for row in locations:
            self.assertNotIn("percentage", row)
            self.assertNotIn("percent", row)

    def test_single_country_states_returns_one_location_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            orgs = _write_dataset(
                Path(tmp),
                [
                    ("ORG-1", "US-TX", "Austin", "TRUE", "2026-01-01"),
                    ("ORG-2", "US-FL", "Miami", "FALSE", "2026-02-01"),
                ],
                states=[("US-TX", "Texas", "1"), ("US-FL", "Florida", "1")],
                countries=[("1", "USA")],
            )
            locations = gla.build_organizations_by_location(orgs, None, None)

        self.assertEqual(locations, [{"country": "USA", "count": 2}])

    def test_empty_and_single_row_do_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = _write_dataset(Path(tmp), [])
            response_empty = gla.build_growth_location_response(
                empty, {}, reference_date=REFERENCE
            )
            self.assertEqual(set(response_empty), {"7D", "30D", "1Y", "All", "Custom"})

        with tempfile.TemporaryDirectory() as tmp:
            one = _write_dataset(
                Path(tmp), [("ORG-1", "US-TX", "Austin", "TRUE", "2026-01-01")]
            )
            response_one = gla.build_growth_location_response(
                one, {}, reference_date=REFERENCE
            )
            self.assertEqual(response_one["All"]["growth_trend"]["total_organizations"][-1]["count"], 1)

    def test_lambda_handler_api_gateway_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_dataset(Path(tmp), [("ORG-1", "US-TX", "Austin", "TRUE", "2026-01-01")])
            with mock.patch.dict("os.environ", {"MOCK_DATA_DIR": tmp}):
                result = gla.lambda_handler({"body": "{}"}, None)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(set(json.loads(result["body"])), {"7D", "30D", "1Y", "All", "Custom"})


if __name__ == "__main__":
    unittest.main()
