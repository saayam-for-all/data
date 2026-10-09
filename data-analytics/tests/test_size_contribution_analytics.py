"""Tests for size_contribution_analytics.py (#376).

The CSVs are small made-up ones written to a temp folder, so nothing needs
to be committed. Run from the repo root:
    python -m unittest discover -s data-analytics/tests -p "test_size_contribution*.py"
"""

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

LAMBDA_DIR = os.path.join(os.path.dirname(__file__), "..", "lambda_functions")
sys.path.insert(0, os.path.abspath(LAMBDA_DIR))

import size_contribution_analytics as sca  # noqa: E402

TODAY = date(2026, 9, 29)
FIVE_KEYS = ["7D", "30D", "1Y", "All", "Custom"]
EMPTY = {"organizations_by_size": [], "collaborator_vs_contributor": []}

COUNTRIES = [("1", "UNITED_STATES", "USA"), ("2", "INDIA", "IND")]
STATES = [("TX", "1"), ("FL", "1"), ("MH", "2")]
# org_id, org_size, is_collaborator, is_contributor, org_type, state_id, created_at
ORGANIZATIONS = [
    ("O1", "small", "True", "True", "non_profit", "TX", "2026-09-29 12:00:00"),
    ("O2", "small", "False", "False", "For-profit", "FL", "2026-09-23 00:00:00"),
    ("O3", "medium", "false", "TRUE", "Non-Profit", "MH", "2026-09-25 08:00:00"),
    ("O4", "large", "1", "0", "non_profit", "TX", "2026-09-22 23:59:59"),
    ("O5", "medium", "True", "True", "for_profit", "MH", "2026-08-31 00:00:00"),
    ("O6", "small", "False", "True", "non_profit", "TX", "2026-08-30 10:00:00"),
    ("O7", "large", "False", "False", "non_profit", "FL", "2025-10-01 00:00:00"),
    ("O8", "medium", "True", "False", "for_profit", "MH", "2026-03-15 10:00:00"),
    ("O9", "small", "True", "True", "non_profit", "TX", "2024-05-01 09:30:00"),
]
ORG_COLUMNS = [
    "org_id",
    "org_size",
    "is_collaborator",
    "is_contributor",
    "org_type",
    "state_id",
    "created_at",
]


def write_csv(path, header, rows):
    """Write a CSV with a header row."""
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def write_fixture(folder, organizations=ORGANIZATIONS, drop_contributor=False):
    """Write the three CSVs the lambda reads."""
    columns, rows = ORG_COLUMNS, organizations
    if drop_contributor:
        columns = [c for c in ORG_COLUMNS if c != "is_contributor"]
        rows = [row[:3] + row[4:] for row in organizations]
    write_csv(os.path.join(folder, "organizations.csv"), columns, rows)
    write_csv(os.path.join(folder, "states.csv"), ["state_id", "country_id"], STATES)
    write_csv(
        os.path.join(folder, "countries.csv"),
        ["country_id", "country_name", "country_code"],
        COUNTRIES,
    )


def collab_rows(collab_count, collab_pct, contrib_count, contrib_pct):
    """Shortcut for the expected collaborator_vs_contributor rows."""
    return [
        {"type": "Collaborator", "count": collab_count, "percentage": collab_pct},
        {"type": "Contributor", "count": contrib_count, "percentage": contrib_pct},
    ]


class SizeContributionTests(unittest.TestCase):
    """Mock mode with "today" fixed to 2026-09-29 so the windows don't move."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        write_fixture(self.folder.name)
        env = {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": self.folder.name}
        self.env_patch = mock.patch.dict(os.environ, env)
        self.today_patch = mock.patch.object(sca, "utc_today", return_value=TODAY)
        self.env_patch.start()
        self.today_patch.start()

    def tearDown(self):
        self.today_patch.stop()
        self.env_patch.stop()
        self.folder.cleanup()

    def call(self, body=None, expected_status=200):
        """Call the handler, check the status code, return the body."""
        event = {} if body is None else {"body": json.dumps(body)}
        response = sca.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], expected_status, response["body"])
        return json.loads(response["body"])

    # response shape

    def test_no_body_returns_five_keys_and_empty_custom(self):
        result = self.call()
        self.assertEqual(list(result), FIVE_KEYS)
        self.assertEqual(result["Custom"], EMPTY)
        for bucket in result.values():
            self.assertEqual(list(bucket), ["organizations_by_size", "collaborator_vs_contributor"])

    def test_fixed_buckets(self):
        result = self.call()
        # 7D is O1-O3. O2 sits right on the start boundary, O4 is 1s before it
        self.assertEqual(
            result["7D"]["organizations_by_size"],
            [{"size": "small", "count": 2}, {"size": "medium", "count": 1}],
        )
        self.assertEqual(result["7D"]["collaborator_vs_contributor"], collab_rows(1, 33.3, 2, 66.7))
        # 30D adds O4-O5, 1Y adds O6-O8, All adds O9
        self.assertEqual(
            result["30D"]["collaborator_vs_contributor"], collab_rows(3, 60.0, 3, 60.0)
        )
        self.assertEqual(
            result["1Y"]["organizations_by_size"],
            [
                {"size": "small", "count": 3},
                {"size": "medium", "count": 3},
                {"size": "large", "count": 2},
            ],
        )
        self.assertEqual(
            result["All"]["collaborator_vs_contributor"], collab_rows(5, 55.6, 5, 55.6)
        )

    def test_sizes_add_up_to_total_and_flags_never_exceed_it(self):
        result = self.call()
        totals = {"7D": 3, "30D": 5, "1Y": 8, "All": 9}
        for bucket, total in totals.items():
            sizes = result[bucket]["organizations_by_size"]
            self.assertEqual(sum(row["count"] for row in sizes), total)
            for row in result[bucket]["collaborator_vs_contributor"]:
                self.assertLessEqual(row["count"], total)

    # filters

    def test_country_filter_by_code_and_name(self):
        by_code = self.call({"country": "USA"})
        self.assertEqual(
            by_code["All"]["organizations_by_size"],
            [{"size": "small", "count": 4}, {"size": "large", "count": 2}],
        )
        for name in ("usa", "United States", "UNITED_STATES"):
            self.assertEqual(self.call({"country": name}), by_code)
        india = self.call({"country": "India"})
        self.assertEqual(india["All"]["collaborator_vs_contributor"], collab_rows(2, 66.7, 2, 66.7))

    def test_unknown_country_returns_empty_charts(self):
        result = self.call({"country": "Atlantis"})
        for bucket in result.values():
            self.assertEqual(bucket, EMPTY)

    def test_organization_type_filter(self):
        for_profit = self.call({"organization_type": "for_profit"})
        self.assertEqual(
            for_profit["All"]["organizations_by_size"],
            [{"size": "small", "count": 1}, {"size": "medium", "count": 2}],
        )
        non_profit = self.call({"organization_type": "non_profit"})
        self.assertEqual(
            non_profit["All"]["collaborator_vs_contributor"],
            collab_rows(3, 50.0, 4, 66.7),
        )
        self.assertEqual(self.call({"organization_type": "ALL"}), self.call())
        # real CSVs spell it "Non-Profit" / "For-profit"; all spellings should match
        for spelling in ("Non-Profit", "non-profit", "NON_PROFIT"):
            self.assertEqual(self.call({"organization_type": spelling}), non_profit)

    def test_repo_sample_file_names_work(self):
        # data-analytics/sql uses state.csv / country.csv instead
        folder = self.folder.name
        os.rename(os.path.join(folder, "states.csv"), os.path.join(folder, "state.csv"))
        os.rename(os.path.join(folder, "countries.csv"), os.path.join(folder, "country.csv"))
        result = self.call({"country": "USA"})
        self.assertEqual(
            result["All"]["organizations_by_size"],
            [{"size": "small", "count": 4}, {"size": "large", "count": 2}],
        )

    def test_country_and_type_together_also_apply_to_custom(self):
        result = self.call(
            {
                "country": "IND",
                "organization_type": "for_profit",
                "size_start_date": "2024-01-01",
                "size_end_date": "2026-12-31",
            }
        )
        self.assertEqual(
            result["Custom"]["organizations_by_size"], [{"size": "medium", "count": 2}]
        )

    # custom date ranges

    def test_size_range_only(self):
        result = self.call({"size_start_date": "2026-09-23", "size_end_date": "2026-09-29"})
        self.assertEqual(list(result), ["Custom"])
        self.assertEqual(
            result["Custom"]["organizations_by_size"],
            [{"size": "small", "count": 2}, {"size": "medium", "count": 1}],
        )
        self.assertEqual(result["Custom"]["collaborator_vs_contributor"], [])

    def test_contribution_range_only(self):
        result = self.call(
            {"contribution_start_date": "2024-01-01", "contribution_end_date": "2025-12-31"}
        )
        self.assertEqual(list(result), ["Custom"])
        self.assertEqual(result["Custom"]["organizations_by_size"], [])
        # O7 is neither, O9 is both
        self.assertEqual(
            result["Custom"]["collaborator_vs_contributor"], collab_rows(1, 50.0, 1, 50.0)
        )

    def test_both_ranges_are_calculated_independently(self):
        size_only = {"size_start_date": "2026-09-23", "size_end_date": "2026-09-29"}
        contribution_only = {
            "contribution_start_date": "2024-01-01",
            "contribution_end_date": "2025-12-31",
        }
        both = self.call({**size_only, **contribution_only})
        self.assertEqual(list(both), ["Custom"])
        self.assertEqual(
            both["Custom"]["organizations_by_size"],
            self.call(size_only)["Custom"]["organizations_by_size"],
        )
        self.assertEqual(
            both["Custom"]["collaborator_vs_contributor"],
            self.call(contribution_only)["Custom"]["collaborator_vs_contributor"],
        )

    def test_end_date_includes_the_whole_day(self):
        result = self.call({"size_start_date": "2026-09-22", "size_end_date": "2026-09-22"})
        self.assertEqual(result["Custom"]["organizations_by_size"], [{"size": "large", "count": 1}])

    def test_range_with_no_organizations_returns_empty_arrays(self):
        result = self.call(
            {
                "size_start_date": "2020-01-01",
                "size_end_date": "2020-12-31",
                "contribution_start_date": "2020-01-01",
                "contribution_end_date": "2020-12-31",
            }
        )
        self.assertEqual(result, {"Custom": EMPTY})

    # invalid input

    def test_incomplete_pairs_return_400(self):
        for body in (
            {"size_start_date": "2026-01-01"},
            {"size_end_date": "2026-01-01"},
            {"contribution_start_date": "2026-01-01"},
            {"contribution_end_date": "2026-01-01"},
        ):
            with self.subTest(body=body):
                self.assertIn("must be sent together", self.call(body, 400)["error"])

    def test_malformed_dates_return_400(self):
        for bad in ("2026/01/01", "01-01-2026", "2026-02-30", "yesterday", 20260101):
            with self.subTest(bad=bad):
                self.call({"size_start_date": bad, "size_end_date": "2026-12-31"}, 400)
                self.call(
                    {"contribution_start_date": bad, "contribution_end_date": "2026-12-31"},
                    400,
                )

    def test_start_after_end_returns_400(self):
        error = self.call(
            {"contribution_start_date": "2026-02-01", "contribution_end_date": "2026-01-01"},
            400,
        )["error"]
        self.assertIn("must be on or before", error)

    def test_invalid_filter_or_body_returns_400(self):
        self.call({"organization_type": "charity"}, 400)
        self.call({"country": 123}, 400)
        response = sca.lambda_handler({"body": "{not json"}, None)
        self.assertEqual(response["statusCode"], 400)

    # collaborator / contributor rules

    def test_flags_are_independent_and_percentages_need_not_sum_to_100(self):
        chart = self.call()["30D"]["collaborator_vs_contributor"]
        # 5 orgs, 3 collaborators, 3 contributors -> 60% + 60%
        self.assertEqual(sum(row["percentage"] for row in chart), 120.0)
        # "False" / "0" strings shouldn't be read as True
        usa_for_profit = self.call({"country": "USA", "organization_type": "for_profit"})
        self.assertEqual(
            usa_for_profit["All"]["collaborator_vs_contributor"],
            collab_rows(0, 0.0, 0, 0.0),
        )

    def test_missing_is_contributor_column_gives_zero(self):
        write_fixture(self.folder.name, drop_contributor=True)
        chart = self.call()["All"]["collaborator_vs_contributor"]
        self.assertEqual(chart, collab_rows(5, 55.6, 0, 0.0))

    # small datasets and data errors

    def test_empty_and_one_row_datasets(self):
        write_fixture(self.folder.name, organizations=[])
        for bucket in self.call().values():
            self.assertEqual(bucket, EMPTY)
        write_fixture(self.folder.name, organizations=[ORGANIZATIONS[0]])
        result = self.call()
        self.assertEqual(result["7D"]["organizations_by_size"], [{"size": "small", "count": 1}])

    def test_missing_file_returns_500(self):
        os.remove(os.path.join(self.folder.name, "organizations.csv"))
        self.assertIn("organizations.csv", self.call(None, 500)["error"])


class FixedWindowTest(unittest.TestCase):
    def test_window_lengths(self):
        start, end = sca.fixed_window("7D", TODAY)
        self.assertEqual((start.date(), (end - start).days), (date(2026, 9, 23), 7))
        start, end = sca.fixed_window("30D", TODAY)
        self.assertEqual((start.date(), (end - start).days), (date(2026, 8, 31), 30))

    def test_1y_is_current_month_plus_previous_11(self):
        self.assertEqual(sca.fixed_window("1Y", TODAY)[0].date(), date(2025, 10, 1))
        self.assertEqual(sca.fixed_window("1Y", date(2026, 1, 15))[0].date(), date(2025, 2, 1))
        self.assertEqual(sca.fixed_window("1Y", date(2026, 12, 31))[0].date(), date(2026, 1, 1))
        self.assertEqual(sca.fixed_window("All", TODAY), (None, None))


class NoPsycopg2Test(unittest.TestCase):
    def test_mock_mode_runs_without_psycopg2(self):
        with tempfile.TemporaryDirectory() as folder:
            write_fixture(folder)
            script = (
                "import sys\n"
                "sys.modules['psycopg2'] = None  # simulate psycopg2 not installed\n"
                f"sys.path.insert(0, {os.path.abspath(LAMBDA_DIR)!r})\n"
                "import size_contribution_analytics as m\n"
                "print(m.psycopg2, m.lambda_handler({}, None)['statusCode'])\n"
            )
            env = dict(os.environ, USE_MOCK_DATA="true", MOCK_DATA_DIR=folder)
            result = subprocess.run(
                [sys.executable, "-c", script], env=env, capture_output=True, text=True
            )
        self.assertEqual(result.stdout.strip(), "None 200", result.stderr)


if __name__ == "__main__":
    unittest.main()
