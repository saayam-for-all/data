import json
import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

import pandas as pd

import size_and_contribution_analytics as sca

REPO_MOCK_DIR = sca.DEFAULT_DATA_DIR
TODAY = pd.Timestamp.now().normalize()


def days_ago(n):
    return (TODAY - timedelta(days=n) + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")


# org_id, state, type, size, collaborator, contributor, created
SAMPLE = [
    ["O1", "TX", "non_profit", "small", True, True, days_ago(1)],
    ["O2", "FL", "for_profit", "medium", False, True, days_ago(3)],
    ["O3", "MH", "non_profit", "small", False, False, days_ago(6)],
    ["O4", "ON", "non_profit", "large", True, False, days_ago(20)],
    ["O5", "TX", "for_profit", "small", False, True, days_ago(25)],
    ["O6", "MH", "non_profit", "medium", True, True, days_ago(200)],
    ["O7", "ON", "for_profit", "large", False, False, days_ago(300)],
    ["O8", "TX", "non_profit", "medium", True, False, days_ago(500)],
]


def write_dataset(rows, drop_contributor=False):
    folder = tempfile.mkdtemp()
    orgs = pd.DataFrame(rows, columns=["org_id", "state_id", "org_type", "org_size",
                                       "is_collaborator", "is_contributor", "created_at"])
    if drop_contributor:
        orgs = orgs.drop(columns=["is_contributor"])
    orgs.to_csv(os.path.join(folder, "organizations.csv"), index=False)
    pd.DataFrame({
        "state_id": ["TX", "FL", "MH", "ON"],
        "country_id": [1, 1, 2, 3],
    }).to_csv(os.path.join(folder, "states.csv"), index=False)
    pd.DataFrame({
        "country_id": [1, 2, 3],
        "country_code": ["USA", "IND", "CAN"],
        "country_name": ["UNITED_STATES", "INDIA", "CANADA"],
    }).to_csv(os.path.join(folder, "countries.csv"), index=False)
    return folder


def call(params=None, raw_event=None):
    event = raw_event if raw_event is not None else {"body": json.dumps(params or {})}
    res = sca.lambda_handler(event, None)
    return res["statusCode"], json.loads(res["body"])


class CsvTestCase(unittest.TestCase):
    rows = SAMPLE
    drop_contributor = False

    def setUp(self):
        self.folder = write_dataset(self.rows, self.drop_contributor)
        patcher = mock.patch.dict(os.environ, {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": self.folder})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.folder)

    def size_total(self, chart):
        return sum(row["count"] for row in chart["organizations_by_size"])


class FullResponseTests(CsvTestCase):

    def test_no_body_has_exactly_five_keys(self):
        status, body = call(raw_event={})
        self.assertEqual(status, 200)
        self.assertEqual(list(body), ["7D", "30D", "1Y", "All", "Custom"])
        for charts in body.values():
            self.assertEqual(set(charts), {"organizations_by_size", "collaborator_vs_contributor"})
        self.assertEqual(body["Custom"], sca.empty_charts())

    def test_each_window_only_counts_orgs_created_inside_it(self):
        _, body = call()
        self.assertEqual(self.size_total(body["7D"]), 3)
        self.assertEqual(self.size_total(body["30D"]), 5)
        self.assertEqual(self.size_total(body["1Y"]), 7)
        self.assertEqual(self.size_total(body["All"]), 8)

    def test_size_rows_come_from_the_data(self):
        _, body = call()
        self.assertEqual(body["7D"]["organizations_by_size"],
                         [{"size": "small", "count": 2}, {"size": "medium", "count": 1}])
        sizes = {row["size"] for row in body["All"]["organizations_by_size"]}
        self.assertEqual(sizes, {"small", "medium", "large"})

    def test_collaborator_and_contributor_are_counted_separately(self):
        _, body = call()
        # 7D: O1 is both, O2 contributor only, O3 neither
        self.assertEqual(body["7D"]["collaborator_vs_contributor"], [
            {"type": "Collaborator", "count": 1, "percentage": 33.3},
            {"type": "Contributor", "count": 2, "percentage": 66.7},
        ])
        for name in sca.FIXED_WINDOWS:
            total = self.size_total(body[name])
            rows = body[name]["collaborator_vs_contributor"]
            self.assertEqual([r["type"] for r in rows], ["Collaborator", "Contributor"])
            self.assertTrue(all(r["count"] <= total for r in rows))

    def test_query_string_params_work_for_get_requests(self):
        status, body = call(raw_event={"body": None, "queryStringParameters": {"country": "CAN"}})
        self.assertEqual(status, 200)
        self.assertEqual(self.size_total(body["All"]), 2)

    def test_direct_invoke_without_body_key(self):
        status, body = call(raw_event={"organization_type": "for_profit"})
        self.assertEqual(status, 200)
        self.assertEqual(self.size_total(body["All"]), 3)


class FilterTests(CsvTestCase):

    def test_country_by_code(self):
        _, body = call({"country": "USA"})
        self.assertEqual(self.size_total(body["All"]), 4)
        self.assertEqual(self.size_total(body["7D"]), 2)

    def test_country_by_name_in_any_spelling(self):
        for name in ("India", "INDIA", "united states", "United-States"):
            _, body = call({"country": name})
            expected = 2 if name.lower() == "india" else 4
            self.assertEqual(self.size_total(body["All"]), expected, name)

    def test_country_all_is_the_default(self):
        _, everything = call()
        _, explicit = call({"country": "ALL", "organization_type": "all"})
        self.assertEqual(everything, explicit)

    def test_unknown_country_gives_empty_charts(self):
        status, body = call({"country": "Atlantis"})
        self.assertEqual(status, 200)
        self.assertEqual(body["All"], sca.empty_charts())

    def test_org_type(self):
        _, non_profit = call({"organization_type": "non_profit"})
        _, for_profit = call({"organization_type": "Non-Profit"})
        self.assertEqual(non_profit, for_profit)
        self.assertEqual(self.size_total(non_profit["All"]), 5)
        _, body = call({"organization_type": "for_profit"})
        self.assertEqual(self.size_total(body["All"]), 3)

    def test_filters_apply_to_custom_ranges_too(self):
        _, body = call({"country": "USA", "organization_type": "for_profit",
                        "size_start_date": days_ago(30)[:10], "size_end_date": TODAY.strftime("%Y-%m-%d")})
        self.assertEqual(body["Custom"]["organizations_by_size"],
                         [{"size": "medium", "count": 1}, {"size": "small", "count": 1}])


class CustomRangeTests(CsvTestCase):

    def test_size_range_only(self):
        _, body = call({"size_start_date": days_ago(30)[:10], "size_end_date": days_ago(4)[:10]})
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(self.size_total(body["Custom"]), 3)
        self.assertEqual(body["Custom"]["collaborator_vs_contributor"], [])

    def test_contribution_range_only(self):
        _, body = call({"contribution_start_date": days_ago(400)[:10], "contribution_end_date": days_ago(100)[:10]})
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(body["Custom"]["organizations_by_size"], [])
        self.assertEqual(body["Custom"]["collaborator_vs_contributor"], [
            {"type": "Collaborator", "count": 1, "percentage": 50.0},
            {"type": "Contributor", "count": 1, "percentage": 50.0},
        ])

    def test_both_ranges_are_used_each_on_its_own_chart(self):
        _, body = call({
            "size_start_date": days_ago(7)[:10], "size_end_date": TODAY.strftime("%Y-%m-%d"),
            "contribution_start_date": days_ago(600)[:10], "contribution_end_date": days_ago(100)[:10],
        })
        self.assertEqual(list(body), ["Custom"])
        # size chart only sees the last week (3 orgs), contribution chart only the old ones (3 orgs)
        self.assertEqual(self.size_total(body["Custom"]), 3)
        self.assertEqual(body["Custom"]["collaborator_vs_contributor"], [
            {"type": "Collaborator", "count": 2, "percentage": 66.7},
            {"type": "Contributor", "count": 1, "percentage": 33.3},
        ])

    def test_end_date_is_inclusive(self):
        day = days_ago(1)[:10]
        _, body = call({"size_start_date": day, "size_end_date": day})
        self.assertEqual(self.size_total(body["Custom"]), 1)

    def test_range_with_no_orgs_is_empty_not_an_error(self):
        status, body = call({"size_start_date": "2001-01-01", "size_end_date": "2001-12-31",
                             "contribution_start_date": "2001-01-01", "contribution_end_date": "2001-12-31"})
        self.assertEqual(status, 200)
        self.assertEqual(body, {"Custom": sca.empty_charts()})


class BadInputTests(CsvTestCase):

    def assert_400(self, params=None, raw_event=None, mentions=""):
        status, body = call(params, raw_event)
        self.assertEqual(status, 400, body)
        self.assertIn(mentions, body["error"])

    def test_half_a_pair(self):
        self.assert_400({"size_start_date": "2026-01-01"}, mentions="sent together")
        self.assert_400({"contribution_end_date": "2026-01-01"}, mentions="sent together")

    def test_bad_format(self):
        self.assert_400({"size_start_date": "01/01/2026", "size_end_date": "2026-02-01"}, mentions="YYYY-MM-DD")
        self.assert_400({"contribution_start_date": "2026-13-01", "contribution_end_date": "2026-12-01"},
                        mentions="YYYY-MM-DD")
        self.assert_400({"size_start_date": 20260101, "size_end_date": 20260201}, mentions="YYYY-MM-DD")

    def test_start_after_end(self):
        self.assert_400({"contribution_start_date": "2026-05-01", "contribution_end_date": "2026-01-01"},
                        mentions="cannot be after")

    def test_one_good_pair_does_not_hide_a_bad_one(self):
        self.assert_400({"size_start_date": "2026-01-01", "size_end_date": "2026-02-01",
                         "contribution_start_date": "2026-03-01"}, mentions="contribution_start_date")

    def test_bad_filters(self):
        self.assert_400({"organization_type": "government"}, mentions="organization_type")
        self.assert_400({"country": ["USA"]}, mentions="strings")

    def test_bad_body(self):
        self.assert_400(raw_event={"body": "{not json"}, mentions="not valid JSON")
        self.assert_400(raw_event={"body": "[1, 2]"}, mentions="JSON object")


class MissingContributorColumnTests(CsvTestCase):
    drop_contributor = True

    def test_contributor_falls_back_to_zero(self):
        status, body = call()
        self.assertEqual(status, 200)
        contributor = body["7D"]["collaborator_vs_contributor"][1]
        self.assertEqual(contributor, {"type": "Contributor", "count": 0, "percentage": 0.0})


class EmptyFileTests(CsvTestCase):
    rows = []

    def test_header_only_file(self):
        status, body = call()
        self.assertEqual(status, 200)
        self.assertTrue(all(body[name] == sca.empty_charts() for name in body))

    def test_zero_byte_file(self):
        open(os.path.join(self.folder, "organizations.csv"), "w").close()
        status, body = call({"size_start_date": "2026-01-01", "size_end_date": "2026-12-31"})
        self.assertEqual(status, 200)
        self.assertEqual(body, {"Custom": sca.empty_charts()})


class SingleRowTests(CsvTestCase):
    rows = [["O1", "TX", "non_profit", "large", True, False, days_ago(0)]]

    def test_one_org(self):
        _, body = call()
        for name in sca.FIXED_WINDOWS:
            self.assertEqual(body[name]["organizations_by_size"], [{"size": "large", "count": 1}])
            self.assertEqual(body[name]["collaborator_vs_contributor"][0]["percentage"], 100.0)


@unittest.skipUnless(os.path.exists(os.path.join(REPO_MOCK_DIR, "organizations.csv")), "mock csvs not present")
class RepoMockDataTests(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": REPO_MOCK_DIR})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.orgs = pd.read_csv(os.path.join(REPO_MOCK_DIR, "organizations.csv"))

    def test_all_window_matches_the_raw_csv(self):
        _, body = call()
        size_rows = body["All"]["organizations_by_size"]
        self.assertEqual(sum(r["count"] for r in size_rows), len(self.orgs))
        self.assertEqual({r["size"]: r["count"] for r in size_rows},
                         self.orgs["org_size"].value_counts().to_dict())
        collab, contrib = body["All"]["collaborator_vs_contributor"]
        self.assertEqual(collab["count"], int(self.orgs["is_collaborator"].sum()))
        self.assertEqual(contrib["count"], int(self.orgs["is_contributor"].sum()))

    def test_filters_shrink_the_numbers(self):
        _, everything = call()
        total = sum(r["count"] for r in everything["All"]["organizations_by_size"])
        for params in ({"country": "USA"}, {"organization_type": "for_profit"}):
            _, body = call(params)
            filtered = sum(r["count"] for r in body["All"]["organizations_by_size"])
            self.assertLess(filtered, total, params)
            self.assertGreater(filtered, 0, params)


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None

    def execute(self, sql, args):
        self.conn.calls.append((sql, list(args)))
        if self.conn.missing_contributor and "o.is_contributor" in sql:
            err = Exception('column o.is_contributor does not exist')
            err.pgcode = "42703"
            raise err
        cols = ["org_size", "org_type", "is_collaborator", "is_contributor", "created_at",
                "country_code", "country_name"]
        self.description = [(c,) for c in cols]

    def fetchall(self):
        contributor = False if self.conn.missing_contributor else True
        return [("small", "non_profit", True, contributor, pd.Timestamp(days_ago(2), tz="UTC"), "USA", "UNITED_STATES")]


class FakeConnection:
    def __init__(self, missing_contributor=False):
        self.calls = []
        self.missing_contributor = missing_contributor
        self.rolled_back = self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class DatabasePathTests(unittest.TestCase):
    """no postgres locally, so these check the sql wiring with a fake connection"""

    def setUp(self):
        env = {"USE_MOCK_DATA": "false", "PGHOST": "h", "PGDATABASE": "d", "PGUSER": "u", "PGPASSWORD": "p"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_with(self, conn, params):
        fake_driver = mock.Mock()
        fake_driver.connect.return_value = conn
        with mock.patch.object(sca, "psycopg2", fake_driver):
            return call(params)

    def test_filters_are_sent_to_postgres_as_parameters(self):
        conn = FakeConnection()
        status, body = self.run_with(conn, {"country": "United States", "organization_type": "Non Profit"})
        self.assertEqual(status, 200)
        sql, args = conn.calls[0]
        self.assertIn("WHERE", sql)
        self.assertEqual(args, ["UNITED_STATES", "UNITED_STATES", "non_profit"])
        self.assertNotIn("UNITED_STATES", sql)
        self.assertTrue(conn.closed)
        self.assertEqual(body["7D"]["collaborator_vs_contributor"][1]["count"], 1)

    def test_no_filters_means_no_where_clause(self):
        conn = FakeConnection()
        self.run_with(conn, {})
        self.assertNotIn("WHERE", conn.calls[0][0])

    def test_retries_without_is_contributor_column(self):
        conn = FakeConnection(missing_contributor=True)
        status, body = self.run_with(conn, {})
        self.assertEqual(status, 200)
        self.assertTrue(conn.rolled_back)
        self.assertEqual(len(conn.calls), 2)
        self.assertEqual(body["7D"]["collaborator_vs_contributor"][1]["count"], 0)

    def test_missing_driver_is_a_500_not_a_crash(self):
        with mock.patch.object(sca, "psycopg2", None):
            status, body = call()
        self.assertEqual(status, 500)
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
