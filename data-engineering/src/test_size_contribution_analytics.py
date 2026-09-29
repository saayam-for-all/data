import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

import pandas as pd

from size_contribution_analytics import lambda_handler

NOW = datetime.now()


def days_ago(n):
    return (NOW - timedelta(days=n)).strftime("%Y-%m-%d %H:%M:%S")


ORGS = [
    # org_id, org_size, is_collaborator, is_contributor, org_type, state_id, created_at
    [1, "small", True, True, "non_profit", 1, days_ago(2)],
    [2, "medium", False, True, "for_profit", 1, days_ago(20)],
    [3, "large", True, False, "non_profit", 2, days_ago(200)],
    [4, "small", False, False, "for_profit", 2, days_ago(500)],
]
COLUMNS = [
    "org_id", "org_size", "is_collaborator", "is_contributor",
    "org_type", "state_id", "created_at",
]


def write_csvs(folder, organizations):
    pd.DataFrame({"country_id": [1, 2], "country_code": ["USA", "IND"]}).to_csv(
        os.path.join(folder, "countries.csv"), index=False
    )
    pd.DataFrame({"state_id": [1, 2], "country_id": [1, 2]}).to_csv(
        os.path.join(folder, "states.csv"), index=False
    )
    organizations.to_csv(os.path.join(folder, "organizations.csv"), index=False)


def call(event):
    result = lambda_handler(event, None)
    return result["statusCode"], json.loads(result["body"])


def total_size_count(bucket):
    return sum(row["count"] for row in bucket["organizations_by_size"])


class SizeContributionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        os.environ["USE_MOCK_DATA"] = "true"
        os.environ["MOCK_DATA_DIR"] = self.folder.name
        write_csvs(self.folder.name, pd.DataFrame(ORGS, columns=COLUMNS))

    def tearDown(self):
        self.folder.cleanup()

    def test_no_params_returns_five_keys(self):
        status, body = call({})
        self.assertEqual(status, 200)
        self.assertEqual(list(body.keys()), ["7D", "30D", "1Y", "All", "Custom"])
        self.assertEqual(body["Custom"]["organizations_by_size"], [])
        self.assertEqual(body["Custom"]["collaborator_vs_contributor"], [])
        self.assertEqual(total_size_count(body["All"]), 4)
        self.assertEqual(total_size_count(body["7D"]), 1)

    def test_collaborator_and_contributor_are_independent(self):
        _, body = call({})
        rows = {row["type"]: row for row in body["All"]["collaborator_vs_contributor"]}
        self.assertEqual(rows["Collaborator"]["count"], 2)
        self.assertEqual(rows["Contributor"]["count"], 2)
        self.assertEqual(rows["Collaborator"]["percentage"], 50.0)

    def test_country_filter(self):
        _, body = call({"country": "USA"})
        self.assertEqual(total_size_count(body["All"]), 2)

    def test_organization_type_filter(self):
        _, body = call({"organization_type": "non_profit"})
        self.assertEqual(total_size_count(body["All"]), 2)

    def test_size_range_only(self):
        _, body = call({"size_start_date": "2000-01-01", "size_end_date": "2100-01-01"})
        self.assertEqual(list(body.keys()), ["Custom"])
        self.assertEqual(total_size_count(body["Custom"]), 4)
        self.assertEqual(body["Custom"]["collaborator_vs_contributor"], [])

    def test_contribution_range_only(self):
        _, body = call({
            "contribution_start_date": "2000-01-01",
            "contribution_end_date": "2100-01-01",
        })
        self.assertEqual(list(body.keys()), ["Custom"])
        self.assertEqual(body["Custom"]["organizations_by_size"], [])
        self.assertEqual(len(body["Custom"]["collaborator_vs_contributor"]), 2)

    def test_both_ranges_together(self):
        _, body = call({
            "size_start_date": "2000-01-01",
            "size_end_date": "2100-01-01",
            "contribution_start_date": "2000-01-01",
            "contribution_end_date": "2100-01-01",
        })
        self.assertEqual(list(body.keys()), ["Custom"])
        self.assertTrue(body["Custom"]["organizations_by_size"])
        self.assertTrue(body["Custom"]["collaborator_vs_contributor"])

    def test_bad_input_returns_400(self):
        bad_events = [
            {"size_start_date": "2026-01-01"},
            {"contribution_end_date": "2026-01-01"},
            {"size_start_date": "01/01/2026", "size_end_date": "2026-02-01"},
            {"contribution_start_date": "2026-05-01", "contribution_end_date": "2026-01-01"},
            {"organization_type": "something_else"},
        ]
        for event in bad_events:
            status, body = call(event)
            self.assertEqual(status, 400, event)
            self.assertIn("error", body)

    def test_missing_is_contributor_column(self):
        orgs = pd.DataFrame(ORGS, columns=COLUMNS).drop(columns=["is_contributor"])
        write_csvs(self.folder.name, orgs)
        _, body = call({})
        rows = {row["type"]: row for row in body["All"]["collaborator_vs_contributor"]}
        self.assertEqual(rows["Contributor"]["count"], 0)
        self.assertEqual(rows["Contributor"]["percentage"], 0.0)

    def test_one_row_and_empty_csv(self):
        write_csvs(self.folder.name, pd.DataFrame(ORGS[:1], columns=COLUMNS))
        status, _ = call({})
        self.assertEqual(status, 200)

        write_csvs(self.folder.name, pd.DataFrame(columns=COLUMNS))
        status, body = call({})
        self.assertEqual(status, 200)
        self.assertEqual(body["All"]["organizations_by_size"], [])
        self.assertEqual(body["All"]["collaborator_vs_contributor"], [])


if __name__ == "__main__":
    unittest.main()
