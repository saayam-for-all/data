

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import organization_size_contribution_analytics as sca  # noqa: E402

NOW = datetime(2026, 9, 29, 12, 0, 0)

COUNTRIES = [
    {"country_id": 1, "country_name": "United States", "country_code": "USA"},
    {"country_id": 2, "country_name": "India", "country_code": "IND"},
]
STATES = [
    {"state_id": "US-CA", "country_id": 1},
    {"state_id": "IN-KA", "country_id": 2},
]


def org(org_id, size, collab, contrib, org_type, state, created):
    return {
        "org_id": org_id, "org_size": size, "is_collaborator": collab,
        "is_contributor": contrib, "org_type": org_type, "state_id": state,
        "created_at": created,
    }


# A small, hand-checkable dataset spread across every bucket boundary.
DEFAULT_ORGS = [
    org("O1", "small",  True,  True,  "non_profit", "US-CA", "2026-09-27 10:00:00"),  # 7D
    org("O2", "medium", False, True,  "for_profit", "IN-KA", "2026-09-25 10:00:00"),  # 7D
    org("O3", "small",  True,  False, "non_profit", "US-CA", "2026-09-10 10:00:00"),  # 30D
    org("O4", "large",  False, False, "non_profit", "IN-KA", "2026-03-15 10:00:00"),  # 1Y
    org("O5", "small",  True,  True,  "for_profit", "US-CA", "2025-12-31 23:30:00"),  # 1Y
    org("O6", "medium", False, True,  "non_profit", "US-CA", "2024-06-01 10:00:00"),  # All only
]


class SizeContributionTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.write_fixtures(DEFAULT_ORGS)
        patches = [
            mock.patch.object(sca, "USE_MOCK_DATA", True),
            mock.patch.object(sca, "MOCK_DATA_DIR", self.tmp),
            mock.patch.object(sca, "_now", return_value=NOW),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_fixtures(self, orgs, drop_columns=()):
        frame = pd.DataFrame(orgs, columns=list(DEFAULT_ORGS[0].keys()))
        frame = frame.drop(columns=list(drop_columns))
        frame.to_csv(os.path.join(self.tmp, "organizations.csv"), index=False)
        pd.DataFrame(STATES).to_csv(os.path.join(self.tmp, "states.csv"), index=False)
        pd.DataFrame(COUNTRIES).to_csv(os.path.join(self.tmp, "countries.csv"), index=False)

    def call(self, event):
        response = sca.lambda_handler(event)
        return response["statusCode"], json.loads(response["body"])

    @staticmethod
    def sizes(rows):
        return {r["size"]: r["count"] for r in rows}

    @staticmethod
    def cvc(rows):
        return {r["type"]: (r["count"], r["percentage"]) for r in rows}


class TestResponseShape(SizeContributionTestCase):

    def test_no_body_returns_exactly_five_keys(self):
        status, body = self.call({})
        self.assertEqual(status, 200)
        self.assertEqual(list(body.keys()), ["7D", "30D", "1Y", "All", "Custom"])
        self.assertEqual(body["Custom"], {"organizations_by_size": [], "collaborator_vs_contributor": []})

    def test_none_event_treated_as_no_body(self):
        status, body = self.call(None)
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 5)

    def test_every_bucket_has_exactly_two_keys(self):
        _, body = self.call({})
        for label, bucket in body.items():
            self.assertEqual(set(bucket), {"organizations_by_size", "collaborator_vs_contributor"}, label)

    def test_country_and_type_only_still_full_shape(self):
        _, body = self.call({"country": "USA", "organization_type": "non_profit"})
        self.assertEqual(list(body.keys()), ["7D", "30D", "1Y", "All", "Custom"])

    def test_api_gateway_body_string(self):
        status, body = self.call({"body": json.dumps({"country": "IND"})})
        self.assertEqual(status, 200)
        self.assertEqual(self.sizes(body["All"]["organizations_by_size"]), {"medium": 1, "large": 1})


class TestFixedBuckets(SizeContributionTestCase):

    def test_bucket_windows(self):
        _, body = self.call({})
        self.assertEqual(self.sizes(body["7D"]["organizations_by_size"]), {"small": 1, "medium": 1})
        self.assertEqual(self.sizes(body["30D"]["organizations_by_size"]), {"small": 2, "medium": 1})
        self.assertEqual(self.sizes(body["1Y"]["organizations_by_size"]), {"small": 3, "medium": 1, "large": 1})
        self.assertEqual(self.sizes(body["All"]["organizations_by_size"]), {"small": 3, "medium": 2, "large": 1})

    def test_size_counts_sum_to_bucket_total(self):
        _, body = self.call({})
        expected_totals = {"7D": 2, "30D": 3, "1Y": 5, "All": 6}
        for label, total in expected_totals.items():
            rows = body[label]["organizations_by_size"]
            self.assertEqual(sum(r["count"] for r in rows), total, label)

    def test_sizes_ordered_most_common_first(self):
        _, body = self.call({})
        self.assertEqual([r["size"] for r in body["All"]["organizations_by_size"]],
                         ["small", "medium", "large"])

    def test_collaborator_vs_contributor_independent_counts(self):
        _, body = self.call({})
        # All: collaborators O1,O3,O5 = 3; contributors O1,O2,O5,O6 = 4; total 6
        self.assertEqual(self.cvc(body["All"]["collaborator_vs_contributor"]),
                         {"Collaborator": (3, 50.0), "Contributor": (4, 66.7)})
        # 7D: O1 is both, O2 contributor only; total 2
        self.assertEqual(self.cvc(body["7D"]["collaborator_vs_contributor"]),
                         {"Collaborator": (1, 50.0), "Contributor": (2, 100.0)})

    def test_counts_not_required_to_sum_to_total(self):
        _, body = self.call({})
        rows = body["All"]["collaborator_vs_contributor"]
        self.assertEqual([r["type"] for r in rows], ["Collaborator", "Contributor"])
        for r in rows:
            self.assertLessEqual(r["count"], 6)
        self.assertNotEqual(sum(r["count"] for r in rows), 6)  # 3 + 4 = 7, by design

    def test_empty_window_returns_empty_arrays(self):
        self.write_fixtures([org("O9", "small", True, True, "non_profit", "US-CA", "2020-01-01 00:00:00")])
        _, body = self.call({})
        for label in ("7D", "30D", "1Y"):
            self.assertEqual(body[label]["organizations_by_size"], [], label)
            self.assertEqual(body[label]["collaborator_vs_contributor"], [], label)
        self.assertEqual(self.sizes(body["All"]["organizations_by_size"]), {"small": 1})

    def test_future_dated_rows_excluded(self):
        self.write_fixtures(DEFAULT_ORGS + [org("OF", "large", True, True, "non_profit", "US-CA", "2027-01-01 00:00:00")])
        _, body = self.call({})
        self.assertNotIn("large", self.sizes(body["7D"]["organizations_by_size"]))
        self.assertEqual(self.sizes(body["All"]["organizations_by_size"])["large"], 1)


class TestFilters(SizeContributionTestCase):

    def test_country_by_code(self):
        _, body = self.call({"country": "USA"})
        self.assertEqual(self.sizes(body["All"]["organizations_by_size"]), {"small": 3, "medium": 1})

    def test_country_by_name_case_insensitive(self):
        _, body = self.call({"country": "united states"})
        self.assertEqual(self.sizes(body["All"]["organizations_by_size"]), {"small": 3, "medium": 1})

    def test_country_all(self):
        _, body = self.call({"country": "ALL"})
        self.assertEqual(sum(r["count"] for r in body["All"]["organizations_by_size"]), 6)

    def test_unknown_country_returns_empty_not_error(self):
        status, body = self.call({"country": "Atlantis"})
        self.assertEqual(status, 200)
        self.assertEqual(body["All"]["organizations_by_size"], [])

    def test_org_type_non_profit(self):
        _, body = self.call({"organization_type": "non_profit"})
        self.assertEqual(self.sizes(body["All"]["organizations_by_size"]), {"small": 2, "large": 1, "medium": 1})

    def test_org_type_for_profit(self):
        _, body = self.call({"organization_type": "for_profit"})
        self.assertEqual(self.sizes(body["All"]["organizations_by_size"]), {"medium": 1, "small": 1})

    def test_filters_apply_to_custom(self):
        _, body = self.call({"country": "IND",
                             "size_start_date": "2020-01-01", "size_end_date": "2026-12-31"})
        self.assertEqual(self.sizes(body["Custom"]["organizations_by_size"]), {"medium": 1, "large": 1})


class TestCustomRanges(SizeContributionTestCase):

    def test_size_range_only(self):
        _, body = self.call({"size_start_date": "2026-01-01", "size_end_date": "2026-09-30"})
        self.assertEqual(list(body.keys()), ["Custom"])
        self.assertEqual(self.sizes(body["Custom"]["organizations_by_size"]),
                         {"small": 2, "medium": 1, "large": 1})
        self.assertEqual(body["Custom"]["collaborator_vs_contributor"], [])

    def test_contribution_range_only(self):
        _, body = self.call({"contribution_start_date": "2024-01-01", "contribution_end_date": "2025-12-31"})
        self.assertEqual(list(body.keys()), ["Custom"])
        self.assertEqual(body["Custom"]["organizations_by_size"], [])
        # O5 and O6: collaborators 1, contributors 2, total 2
        self.assertEqual(self.cvc(body["Custom"]["collaborator_vs_contributor"]),
                         {"Collaborator": (1, 50.0), "Contributor": (2, 100.0)})

    def test_both_ranges_evaluated_independently(self):
        _, body = self.call({
            "size_start_date": "2026-09-01", "size_end_date": "2026-09-30",
            "contribution_start_date": "2024-01-01", "contribution_end_date": "2024-12-31",
        })
        self.assertEqual(list(body.keys()), ["Custom"])
        self.assertEqual(self.sizes(body["Custom"]["organizations_by_size"]), {"small": 2, "medium": 1})
        self.assertEqual(self.cvc(body["Custom"]["collaborator_vs_contributor"]),
                         {"Collaborator": (0, 0.0), "Contributor": (1, 100.0)})

    def test_end_date_is_inclusive(self):
        # O5 was created at 23:30 on 2025-12-31
        _, body = self.call({"size_start_date": "2025-12-31", "size_end_date": "2025-12-31"})
        self.assertEqual(self.sizes(body["Custom"]["organizations_by_size"]), {"small": 1})

    def test_custom_range_with_no_orgs(self):
        _, body = self.call({"size_start_date": "2019-01-01", "size_end_date": "2019-12-31",
                             "contribution_start_date": "2019-01-01", "contribution_end_date": "2019-12-31"})
        self.assertEqual(body, {"Custom": {"organizations_by_size": [], "collaborator_vs_contributor": []}})


class TestValidation(SizeContributionTestCase):

    def assert_400(self, event, fragment):
        status, body = self.call(event)
        self.assertEqual(status, 400, body)
        self.assertIn(fragment, body["error"])

    def test_missing_end_of_size_pair(self):
        self.assert_400({"size_start_date": "2026-01-01"}, "size_end_date is missing")

    def test_missing_start_of_contribution_pair(self):
        self.assert_400({"contribution_end_date": "2026-01-01"}, "contribution_start_date is missing")

    def test_bad_date_format(self):
        self.assert_400({"size_start_date": "2026/01/01", "size_end_date": "2026-02-01"}, "YYYY-MM-DD")

    def test_impossible_date(self):
        self.assert_400({"size_start_date": "2026-02-30", "size_end_date": "2026-03-01"}, "valid date")

    def test_non_string_date(self):
        self.assert_400({"size_start_date": 20260101, "size_end_date": "2026-03-01"}, "date string")

    def test_start_after_end(self):
        self.assert_400({"contribution_start_date": "2026-06-30",
                         "contribution_end_date": "2026-01-01"}, "on or before")

    def test_one_valid_pair_does_not_hide_other_invalid_pair(self):
        self.assert_400({"size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
                         "contribution_start_date": "2026-01-01"}, "contribution_end_date is missing")

    def test_invalid_org_type(self):
        self.assert_400({"organization_type": "government"}, "organization_type")

    def test_invalid_json_body(self):
        self.assert_400({"body": "{not json"}, "not valid JSON")

    def test_empty_strings_treated_as_absent(self):
        status, body = self.call({"size_start_date": "", "size_end_date": "", "country": ""})
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 5)


class TestDataEdgeCases(SizeContributionTestCase):

    def test_missing_is_contributor_column(self):
        self.write_fixtures(DEFAULT_ORGS, drop_columns=["is_contributor"])
        status, body = self.call({})
        self.assertEqual(status, 200)
        self.assertEqual(self.cvc(body["All"]["collaborator_vs_contributor"]),
                         {"Collaborator": (3, 50.0), "Contributor": (0, 0.0)})

    def test_empty_organizations_csv(self):
        self.write_fixtures([])
        status, body = self.call({})
        self.assertEqual(status, 200)
        for bucket in body.values():
            self.assertEqual(bucket, {"organizations_by_size": [], "collaborator_vs_contributor": []})
        status, body = self.call({"size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
                                  "contribution_start_date": "2026-01-01", "contribution_end_date": "2026-06-30"})
        self.assertEqual(status, 200)
        self.assertEqual(body["Custom"], {"organizations_by_size": [], "collaborator_vs_contributor": []})

    def test_single_row_organizations_csv(self):
        self.write_fixtures([DEFAULT_ORGS[0]])
        _, body = self.call({})
        self.assertEqual(self.sizes(body["7D"]["organizations_by_size"]), {"small": 1})
        self.assertEqual(self.cvc(body["7D"]["collaborator_vs_contributor"]),
                         {"Collaborator": (1, 100.0), "Contributor": (1, 100.0)})

    def test_unexpected_size_value_passed_through(self):
        self.write_fixtures(DEFAULT_ORGS + [org("OX", "extra_large", False, False, "non_profit", "US-CA", "2026-09-28 00:00:00")])
        _, body = self.call({})
        self.assertIn("extra_large", self.sizes(body["7D"]["organizations_by_size"]))

    def test_blank_size_ignored_but_org_still_counted_in_total(self):
        self.write_fixtures(DEFAULT_ORGS + [org("OB", "", True, False, "non_profit", "US-CA", "2026-09-28 00:00:00")])
        _, body = self.call({})
        self.assertEqual(self.sizes(body["7D"]["organizations_by_size"]), {"small": 1, "medium": 1})
        self.assertEqual(self.cvc(body["7D"]["collaborator_vs_contributor"])["Collaborator"], (2, 66.7))

    def test_string_booleans(self):
        rows = [dict(r, is_collaborator=str(r["is_collaborator"]).lower(),
                     is_contributor="t" if r["is_contributor"] else "f") for r in DEFAULT_ORGS]
        self.write_fixtures(rows)
        _, body = self.call({})
        self.assertEqual(self.cvc(body["All"]["collaborator_vs_contributor"]),
                         {"Collaborator": (3, 50.0), "Contributor": (4, 66.7)})

    def test_missing_data_file_returns_500_not_crash(self):
        os.remove(os.path.join(self.tmp, "organizations.csv"))
        status, body = self.call({})
        self.assertEqual(status, 500)
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)