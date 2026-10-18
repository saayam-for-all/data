"""Tests for size_contribution_analytics.py (Size & Contribution Analytics API).

Run from data-analytics/lambda_functions/:

    python -m unittest discover -s tests -v      (or: pytest tests -q)

Each test writes its own small CSVs to a temporary folder, so no mock data needs
to be committed. "Today" is pinned to 2026-10-05, which gives these windows:
7D from 2026-09-29, 30D from 2026-09-06, 1Y from 2025-10-06.
"""

import datetime as dt
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

import pandas as pd

LAMBDA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(LAMBDA_DIR, "size_contribution_analytics.py")
sys.path.insert(0, LAMBDA_DIR)

import size_contribution_analytics as sca  # noqa: E402

TODAY = pd.Timestamp("2026-10-05")
FIXED_KEYS = ["7D", "30D", "1Y", "All", "Custom"]
CHART_KEYS = {"organizations_by_size", "collaborator_vs_contributor"}
ORG_COLUMNS = [
    "org_id", "org_size", "is_collaborator", "is_contributor", "org_type", "state_id", "created_at",
]

COUNTRIES = [
    {"country_id": "233", "country_code": "USA", "country_name": "UNITED_STATES_OF_AMERICA"},
    {"country_id": "101", "country_code": "IND", "country_name": "INDIA"},
    {"country_id": "39", "country_code": "CAN", "country_name": "CANADA"},  # has no organizations
]
STATES = [
    {"state_id": "233.1", "country_id": "233"},
    {"state_id": "233.10", "country_id": "233"},  # must not be confused with 233.1
    {"state_id": "101.5", "country_id": "101"},
]


def org(org_id, size, collaborator, contributor, org_type, state_id, created_at):
    """One organizations.csv row."""
    values = [org_id, size, collaborator, contributor, org_type, state_id, created_at]
    return dict(zip(ORG_COLUMNS, values))


# Windows: O1-O2 are in 7D (O2 on its first day), O3 is in 30D but just misses 7D,
# O4 is in 1Y, and O5-O6 only count toward All.
# Flags: O3 and O6 are both collaborator and contributor; O4 is neither.
BASE_ORGS = [
    org("O1", "small", "TRUE", "FALSE", "non_profit", "233.1", "2026-10-04 10:00:00"),
    org("O2", "small", "FALSE", "TRUE", "for_profit", "233.10", "2026-09-29 00:00:00"),
    org("O3", "medium", "TRUE", "TRUE", "non_profit", "101.5", "2026-09-28 23:59:59"),
    org("O4", "large", "FALSE", "FALSE", "non_profit", "101.5", "2026-03-15 08:00:00"),
    org("O5", "medium", "FALSE", "TRUE", "for_profit", "233.1", "2025-06-01 12:00:00"),
    org("O6", "small", "TRUE", "TRUE", "non_profit", "233.10", "2024-12-31 12:00:00"),
]

SIZE_RANGE = {"size_start_date": "2026-09-28", "size_end_date": "2026-10-04"}  # O1, O2, O3
SIZE_RANGE_SIZES = [{"size": "small", "count": 2}, {"size": "medium", "count": 1}]
CONTRIBUTION_RANGE = {  # O5, O6
    "contribution_start_date": "2024-12-31",
    "contribution_end_date": "2025-06-01",
}


def sizes(*pairs):
    return [{"size": size, "count": count} for size, count in pairs]


def flags(collaborators, collaborator_pct, contributors, contributor_pct):
    return [
        {"type": "Collaborator", "count": collaborators, "percentage": collaborator_pct},
        {"type": "Contributor", "count": contributors, "percentage": contributor_pct},
    ]


EMPTY = {"organizations_by_size": [], "collaborator_vs_contributor": []}
EXPECTED_FULL = {
    "7D": {
        "organizations_by_size": sizes(("small", 2)),
        "collaborator_vs_contributor": flags(1, 50.0, 1, 50.0),
    },
    "30D": {
        "organizations_by_size": sizes(("small", 2), ("medium", 1)),
        "collaborator_vs_contributor": flags(2, 66.7, 2, 66.7),
    },
    "1Y": {  # ties are ordered alphabetically
        "organizations_by_size": sizes(("small", 2), ("large", 1), ("medium", 1)),
        "collaborator_vs_contributor": flags(2, 50.0, 2, 50.0),
    },
    "All": {  # 3 + 4 = 7 > 6 organizations: the flags overlap, as expected
        "organizations_by_size": sizes(("small", 3), ("medium", 2), ("large", 1)),
        "collaborator_vs_contributor": flags(3, 50.0, 4, 66.7),
    },
    "Custom": EMPTY,
}


def write_dataset(folder, orgs=None, states=None, countries=None):
    """Write organizations.csv / states.csv / countries.csv into folder."""
    orgs_frame = orgs if isinstance(orgs, pd.DataFrame) else pd.DataFrame(
        BASE_ORGS if orgs is None else orgs, columns=ORG_COLUMNS
    )
    orgs_frame.to_csv(os.path.join(folder, "organizations.csv"), index=False)
    pd.DataFrame(STATES if states is None else states).to_csv(
        os.path.join(folder, "states.csv"), index=False
    )
    pd.DataFrame(COUNTRIES if countries is None else countries).to_csv(
        os.path.join(folder, "countries.csv"), index=False
    )


class SizeContributionTestCase(unittest.TestCase):
    """Runs the handler against CSVs in a temporary MOCK_DATA_DIR, with today pinned."""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.data_dir = temp_dir.name
        for patcher in (
            mock.patch.dict(os.environ, {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": self.data_dir}),
            mock.patch.object(sca, "today_utc", return_value=TODAY),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        write_dataset(self.data_dir)

    def invoke(self, params=None):
        """Call the handler the way API Gateway does and return (status, parsed body)."""
        event = {} if params is None else {"body": json.dumps(params)}
        result = sca.lambda_handler(event, None)
        return result["statusCode"], json.loads(result["body"])

    def assert_ok(self, params=None):
        status, body = self.invoke(params)
        self.assertEqual(status, 200, body)
        return body

    def assert_rejected(self, params, message_part=""):
        status, body = self.invoke(params)
        self.assertEqual(status, 400, body)
        self.assertEqual(list(body), ["error"])
        self.assertIn(message_part, body["error"])
        return body

    def assert_shape(self, body, top_level_keys):
        """Exact top-level keys; each bucket has exactly the two charts."""
        self.assertEqual(list(body), top_level_keys)
        for bucket in body.values():
            self.assertEqual(set(bucket), CHART_KEYS)
            flag_rows = bucket["collaborator_vs_contributor"]
            if flag_rows:
                row_types = [row["type"] for row in flag_rows]
                self.assertEqual(row_types, ["Collaborator", "Contributor"])


class TestFullResponse(SizeContributionTestCase):
    def test_no_body_returns_four_fixed_buckets_and_empty_custom(self):
        body = self.assert_ok()
        self.assert_shape(body, FIXED_KEYS)
        self.assertEqual(body, EXPECTED_FULL)

    def test_body_variants_without_custom_params_give_the_full_response(self):
        events = [None, {}, {"body": None}, {"body": ""}, {"body": "{}"}, {"body": {}}]
        for event in events:
            with self.subTest(event=event):
                result = sca.lambda_handler(event, None)
                self.assertEqual(result["statusCode"], 200)
                self.assertEqual(json.loads(result["body"]), EXPECTED_FULL)

    def test_null_values_are_treated_as_not_sent(self):
        body = self.assert_ok({
            "country": None, "organization_type": None,
            "size_start_date": None, "size_end_date": None,
            "contribution_start_date": None, "contribution_end_date": None,
        })
        self.assertEqual(body, EXPECTED_FULL)

    def test_all_keyword_means_no_filter_in_any_case(self):
        for value in ("ALL", "all", "All"):
            with self.subTest(value=value):
                body = self.assert_ok({"country": value, "organization_type": value})
                self.assertEqual(body, EXPECTED_FULL)

    def test_response_is_api_gateway_shaped_json_with_cors(self):
        result = sca.lambda_handler({}, None)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["headers"]["Access-Control-Allow-Origin"], "*")
        self.assertEqual(result["headers"]["Content-Type"], "application/json")
        self.assertIsInstance(result["body"], str)

    def test_console_output_is_valid_json_matching_the_response(self):
        for params in (None, {**SIZE_RANGE, **CONTRIBUTION_RANGE}, {"country": "Atlantis"}):
            with self.subTest(params=params):
                body = self.invoke(params)[1]
                self.assertEqual(json.loads(sca.format_for_console(body)), body)

    def test_size_counts_add_up_to_the_bucket_total(self):
        body = self.assert_ok()
        totals = {"7D": 2, "30D": 3, "1Y": 4, "All": 6}
        for key, total in totals.items():
            with self.subTest(bucket=key):
                rows = body[key]["organizations_by_size"]
                self.assertEqual(sum(row["count"] for row in rows), total)
                for row in body[key]["collaborator_vs_contributor"]:
                    self.assertLessEqual(row["count"], total)

    def test_buckets_are_window_scoped_snapshots_not_cumulative(self):
        write_dataset(self.data_dir, orgs=[
            org("A", "small", "TRUE", "TRUE", "non_profit", "233.1", "2026-10-05 08:00:00"),
            org("B", "large", "TRUE", "TRUE", "non_profit", "233.1", "2026-08-01 08:00:00"),
        ])
        body = self.assert_ok()
        self.assertEqual(body["7D"]["organizations_by_size"], sizes(("small", 1)))
        self.assertEqual(body["30D"]["organizations_by_size"], sizes(("small", 1)))
        self.assertEqual(body["1Y"]["organizations_by_size"], sizes(("large", 1), ("small", 1)))

    def test_bucket_with_no_organizations_has_empty_arrays(self):
        write_dataset(self.data_dir, orgs=[BASE_ORGS[5]])  # created 2024-12-31
        body = self.assert_ok()
        for key in ("7D", "30D", "1Y"):
            self.assertEqual(body[key], EMPTY)
        self.assertEqual(body["All"]["organizations_by_size"], sizes(("small", 1)))


class TestFilters(SizeContributionTestCase):
    def test_country_code_filter_counts_only_that_country(self):
        body = self.assert_ok({"country": "USA"})
        self.assert_shape(body, FIXED_KEYS)
        self.assertEqual(body["7D"]["organizations_by_size"], sizes(("small", 2)))
        self.assertEqual(body["All"]["organizations_by_size"], sizes(("small", 3), ("medium", 1)))
        self.assertEqual(body["All"]["collaborator_vs_contributor"], flags(2, 50.0, 3, 75.0))

    def test_country_name_and_code_are_interchangeable(self):
        expected = self.assert_ok({"country": "USA"})
        for value in ("UNITED_STATES_OF_AMERICA", "United States of America", "usa"):
            with self.subTest(value=value):
                self.assertEqual(self.assert_ok({"country": value}), expected)

    def test_other_country(self):
        body = self.assert_ok({"country": "IND"})
        self.assertEqual(body["7D"], EMPTY)
        self.assertEqual(body["All"]["organizations_by_size"], sizes(("large", 1), ("medium", 1)))
        self.assertEqual(body["All"]["collaborator_vs_contributor"], flags(1, 50.0, 1, 50.0))

    def test_known_country_without_organizations_returns_empty_arrays(self):
        body = self.assert_ok({"country": "CAN"})
        self.assert_shape(body, FIXED_KEYS)
        for bucket in body.values():
            self.assertEqual(bucket, EMPTY)

    def test_organization_type_filter(self):
        non_profit = self.assert_ok({"organization_type": "non_profit"})
        self.assertEqual(
            non_profit["All"]["organizations_by_size"],
            sizes(("small", 2), ("large", 1), ("medium", 1)),
        )
        self.assertEqual(non_profit["All"]["collaborator_vs_contributor"], flags(3, 75.0, 2, 50.0))

        for_profit = self.assert_ok({"organization_type": "for_profit"})
        self.assertEqual(
            for_profit["All"]["organizations_by_size"], sizes(("medium", 1), ("small", 1))
        )
        self.assertEqual(for_profit["All"]["collaborator_vs_contributor"], flags(0, 0.0, 2, 100.0))

    def test_organization_type_spellings(self):
        expected = self.assert_ok({"organization_type": "non_profit"})
        for value in ("NON_PROFIT", "Non-Profit", "non profit"):
            with self.subTest(value=value):
                self.assertEqual(self.assert_ok({"organization_type": value}), expected)

    def test_filters_also_apply_to_custom_ranges(self):
        body = self.assert_ok({"country": "USA", **SIZE_RANGE, **CONTRIBUTION_RANGE})
        self.assert_shape(body, ["Custom"])
        self.assertEqual(body["Custom"]["organizations_by_size"], sizes(("small", 2)))  # O3 is IND
        self.assertEqual(body["Custom"]["collaborator_vs_contributor"], flags(1, 50.0, 2, 100.0))

    def test_direct_invocation_with_top_level_parameters(self):
        result = sca.lambda_handler({"country": "USA"}, None)
        self.assertEqual(json.loads(result["body"]), self.assert_ok({"country": "USA"}))


class TestCustomRanges(SizeContributionTestCase):
    def test_size_range_only(self):
        body = self.assert_ok(SIZE_RANGE)
        self.assert_shape(body, ["Custom"])
        self.assertEqual(body["Custom"]["organizations_by_size"], SIZE_RANGE_SIZES)
        self.assertEqual(body["Custom"]["collaborator_vs_contributor"], [])

    def test_contribution_range_only(self):
        body = self.assert_ok(CONTRIBUTION_RANGE)
        self.assert_shape(body, ["Custom"])
        self.assertEqual(body["Custom"]["organizations_by_size"], [])
        self.assertEqual(body["Custom"]["collaborator_vs_contributor"], flags(1, 50.0, 2, 100.0))

    def test_both_ranges_are_evaluated_independently(self):
        body = self.assert_ok({**SIZE_RANGE, **CONTRIBUTION_RANGE})
        self.assert_shape(body, ["Custom"])
        self.assertEqual(body["Custom"]["organizations_by_size"], SIZE_RANGE_SIZES)
        self.assertEqual(body["Custom"]["collaborator_vs_contributor"], flags(1, 50.0, 2, 100.0))

    def test_range_ends_are_inclusive_whole_days(self):
        body = self.assert_ok({"size_start_date": "2026-10-04", "size_end_date": "2026-10-04"})
        # Only O1 (created at 10:00 on the end date) falls inside this one-day range.
        self.assertEqual(body["Custom"]["organizations_by_size"], sizes(("small", 1)))

    def test_range_without_organizations_returns_empty_arrays(self):
        body = self.assert_ok({
            "size_start_date": "2020-01-01", "size_end_date": "2020-12-31",
            "contribution_start_date": "2020-01-01", "contribution_end_date": "2020-12-31",
        })
        self.assertEqual(body, {"Custom": EMPTY})


class TestValidation(SizeContributionTestCase):
    PAIRS = (
        ("size_start_date", "size_end_date"),
        ("contribution_start_date", "contribution_end_date"),
    )

    def test_malformed_or_incomplete_date_pairs_are_rejected(self):
        for start, end in self.PAIRS:
            cases = [
                ({start: "2026-01-01"}, "must be provided together"),
                ({end: "2026-01-31"}, "must be provided together"),
                ({start: "2026/01/01", end: "2026-01-31"}, "YYYY-MM-DD"),
                ({start: "2026-1-1", end: "2026-01-31"}, "YYYY-MM-DD"),
                ({start: "", end: "2026-01-31"}, "YYYY-MM-DD"),
                ({start: 20260101, end: "2026-01-31"}, "YYYY-MM-DD"),
                ({start: "2026-01-01", end: "2026-02-30"}, "valid calendar date"),
                ({start: "2026-06-30", end: "2026-01-01"}, "on or before"),
            ]
            for params, message in cases:
                with self.subTest(params=params):
                    body = self.assert_rejected(params, message)
                    self.assertIn(start if start in body["error"] else end, body["error"])

    def test_one_bad_pair_rejects_the_whole_request(self):
        """No partial result: a valid size pair doesn't rescue a broken contribution pair."""
        params = {**SIZE_RANGE, "contribution_start_date": "2025-01-01"}
        self.assert_rejected(params, "contribution")

    def test_invalid_filters_are_rejected(self):
        cases = [
            ({"organization_type": "government"}, "organization_type"),
            ({"organization_type": ""}, "organization_type"),
            ({"organization_type": 7}, "organization_type"),
            ({"country": ""}, "country"),
            ({"country": 233}, "country"),
            ({"country": "-"}, "country"),  # must not silently mean ALL
            ({"country": "Atlantis"}, "does not match"),
        ]
        for params, message in cases:
            with self.subTest(params=params):
                self.assert_rejected(params, message)

    def test_malformed_request_bodies_are_rejected(self):
        events = ({"body": "{not json"}, {"body": "[1, 2]"}, {"body": 42}, ["not", "a", "dict"])
        for event in events:
            with self.subTest(event=event):
                result = sca.lambda_handler(event, None)
                self.assertEqual(result["statusCode"], 400)
                self.assertIn("error", json.loads(result["body"]))

    def test_request_is_validated_before_data_is_loaded(self):
        with mock.patch.dict(os.environ, {"MOCK_DATA_DIR": os.path.join(self.data_dir, "missing")}):
            self.assert_rejected({"size_start_date": "2026-13-01", "size_end_date": "2026-12-31"})


class TestDataEdgeCases(SizeContributionTestCase):
    def test_missing_is_contributor_column_counts_as_zero(self):
        write_dataset(self.data_dir, orgs=pd.DataFrame(BASE_ORGS).drop(columns=["is_contributor"]))
        body = self.assert_ok()
        self.assertEqual(body["All"]["collaborator_vs_contributor"], flags(3, 50.0, 0, 0.0))
        custom = self.assert_ok(CONTRIBUTION_RANGE)
        self.assertEqual(custom["Custom"]["collaborator_vs_contributor"], flags(1, 50.0, 0, 0.0))

    def test_missing_is_collaborator_column_counts_as_zero(self):
        write_dataset(self.data_dir, orgs=pd.DataFrame(BASE_ORGS).drop(columns=["is_collaborator"]))
        body = self.assert_ok()
        self.assertEqual(body["All"]["collaborator_vs_contributor"], flags(0, 0.0, 4, 66.7))

    def test_header_only_and_zero_byte_files_return_empty_arrays(self):
        for kind in ("header only", "zero bytes"):
            with self.subTest(kind=kind):
                write_dataset(self.data_dir, orgs=[])
                if kind == "zero bytes":
                    open(os.path.join(self.data_dir, "organizations.csv"), "w").close()
                full = self.assert_ok()
                self.assert_shape(full, FIXED_KEYS)
                for bucket in full.values():
                    self.assertEqual(bucket, EMPTY)
                custom = self.assert_ok({**SIZE_RANGE, **CONTRIBUTION_RANGE})
                self.assertEqual(custom, {"Custom": EMPTY})

    def test_single_row_file(self):
        write_dataset(self.data_dir, orgs=[BASE_ORGS[0]])
        body = self.assert_ok()
        self.assertEqual(body["7D"]["organizations_by_size"], sizes(("small", 1)))
        self.assertEqual(body["7D"]["collaborator_vs_contributor"], flags(1, 100.0, 0, 0.0))
        self.assertEqual(self.assert_ok(CONTRIBUTION_RANGE), {"Custom": EMPTY})

    def test_sizes_are_not_hardcoded(self):
        when = "2026-10-01 09:00:00"
        extra = [
            org("O7", "extra_large", "FALSE", "FALSE", "non_profit", "233.1", when),
            org("O8", "", "FALSE", "FALSE", "non_profit", "233.1", when),  # no size at all
        ]
        write_dataset(self.data_dir, orgs=BASE_ORGS + extra)
        rows = self.assert_ok()["7D"]["organizations_by_size"]
        self.assertEqual(rows, sizes(("small", 2), ("extra_large", 1), (None, 1)))
        self.assertEqual(sum(row["count"] for row in rows), 4)

    def test_flag_spellings(self):
        values = ["TRUE", "true", "1", "yes", "Y", "FALSE", "0", "no", ""]
        orgs = [
            org(f"F{i}", "small", value, "FALSE", "non_profit", "233.1", "2026-10-01 09:00:00")
            for i, value in enumerate(values)
        ]
        write_dataset(self.data_dir, orgs=orgs)
        body = self.assert_ok()
        self.assertEqual(body["7D"]["collaborator_vs_contributor"], flags(5, 55.6, 0, 0.0))

    def test_timestamp_formats_and_time_zones(self):
        orgs = [
            org("T1", "small", "TRUE", "FALSE", "non_profit", "233.1", "2026-10-01"),
            org("T2", "small", "TRUE", "FALSE", "non_profit", "233.1", "2026-10-04T23:30:00-05:00"),
            org("T3", "small", "TRUE", "FALSE", "non_profit", "233.1", "2026-09-28T23:30:00Z"),
        ]
        write_dataset(self.data_dir, orgs=orgs)
        body = self.assert_ok()
        self.assertEqual(body["7D"]["organizations_by_size"], sizes(("small", 2)))  # T1, T2
        self.assertEqual(body["30D"]["organizations_by_size"], sizes(("small", 3)))

    def test_undated_organizations_only_count_toward_all(self):
        orgs = BASE_ORGS + [
            org("U1", "large", "TRUE", "FALSE", "non_profit", "233.1", "not a date"),
            org("U2", "large", "TRUE", "FALSE", "non_profit", "233.1", ""),
        ]
        write_dataset(self.data_dir, orgs=orgs)
        with self.assertLogs(sca.logger, level="WARNING") as logs:
            body = self.assert_ok()
        self.assertIn("created_at", "\n".join(logs.output))
        self.assertEqual(body["7D"], EXPECTED_FULL["7D"])
        self.assertEqual(
            body["All"]["organizations_by_size"], sizes(("large", 3), ("small", 3), ("medium", 2))
        )

    def test_duplicate_rows_do_not_inflate_counts(self):
        states = STATES + [{"state_id": "233.1", "country_id": "233"}]
        countries = COUNTRIES + [COUNTRIES[0]]
        orgs = BASE_ORGS + [BASE_ORGS[0]]
        write_dataset(self.data_dir, orgs=orgs, states=states, countries=countries)
        joined, _ = sca.load_mock_data(self.data_dir)
        self.assertEqual(len(joined), len(BASE_ORGS) + 1)  # the join adds no rows
        self.assertEqual(self.assert_ok(), EXPECTED_FULL)  # and the repeated O1 counts once

    def test_numeric_ids_written_with_decimals_still_join(self):
        states = [dict(row, country_id=row["country_id"] + ".0") for row in STATES]
        write_dataset(self.data_dir, states=states)
        body = self.assert_ok({"country": "USA"})
        self.assertEqual(body["7D"]["organizations_by_size"], sizes(("small", 2)))

    def test_percentages_round_half_up_to_one_decimal(self):
        cases = [((1, 3), 33.3), ((2, 3), 66.7), ((1, 16), 6.3), ((33, 126), 26.2),
                 ((40, 126), 31.7), ((0, 5), 0.0), ((3, 0), 0.0)]
        for (count, total), expected in cases:
            with self.subTest(count=count, total=total):
                self.assertEqual(sca.percentage(count, total), expected)


class TestDataSourceErrors(SizeContributionTestCase):
    def assert_server_error(self, message_part):
        with self.assertLogs(sca.logger, level="ERROR") as logs:
            status, body = self.invoke()
        self.assertEqual(status, 500)
        self.assertEqual(body, {"error": "Internal server error"})
        self.assertIn(message_part, str(logs.records[0].exc_info[1]))

    def test_missing_csv_file(self):
        os.remove(os.path.join(self.data_dir, "states.csv"))
        self.assert_server_error("Mock data file not found")

    def test_missing_required_column(self):
        write_dataset(self.data_dir, orgs=pd.DataFrame(BASE_ORGS).drop(columns=["org_size"]))
        self.assert_server_error("org_size")

    def test_database_mode_without_psycopg2(self):
        with mock.patch.dict(os.environ, {"USE_MOCK_DATA": "false"}), \
                mock.patch.object(sca, "psycopg2", None):
            self.assert_server_error("psycopg2 is not installed")

    def test_database_mode_without_settings(self):
        env = {"USE_MOCK_DATA": "false", "DB_HOST": "", "DB_NAME": "", "DB_USER": ""}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(sca, "psycopg2", types.SimpleNamespace(connect=None)):
            self.assert_server_error("DB_HOST")

    def test_module_runs_standalone_without_psycopg2(self):
        spec = importlib.util.spec_from_file_location("sca_without_psycopg2", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"psycopg2": None, "psycopg2.sql": None}):
            spec.loader.exec_module(module)
        self.assertIsNone(module.psycopg2)
        with mock.patch.object(module, "today_utc", return_value=TODAY):
            result = module.lambda_handler({}, None)
        self.assertEqual(json.loads(result["body"]), EXPECTED_FULL)


class FakeCursor:
    """Answers information_schema lookups and the two data queries from fixtures."""

    def __init__(self, tables, org_rows, country_rows):
        self.tables, self.org_rows, self.country_rows = tables, org_rows, country_rows
        self.description, self._rows, self._data_queries = None, [], 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, query, params=None):
        if params is not None:  # information_schema.columns lookup
            self._rows = [(name,) for name in self.tables.get(params[1], [])]
            return
        self._data_queries += 1
        columns, rows = self.org_rows if self._data_queries == 1 else self.country_rows
        self.description = [(name,) for name in columns]
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self, cursor):
        self._cursor, self.closed, self.session = cursor, False, None

    def cursor(self):
        return self._cursor

    def set_session(self, **kwargs):
        self.session = kwargs

    def close(self):
        self.closed = True


@unittest.skipIf(sca.pg_sql is None, "psycopg2 not installed")
class TestDatabasePath(SizeContributionTestCase):
    """The real-database path with psycopg2's connection faked out."""

    ORG_SELECT = [*sca.ORG_REQUIRED_COLUMNS, *sca.ORG_FLAG_COLUMNS, "country_code", "country_name"]

    def run_db(self, org_table_columns):
        utc = dt.timezone.utc
        oct_4 = dt.datetime(2026, 10, 4, 10, tzinfo=utc)
        sep_28 = dt.datetime(2026, 9, 28, 23, tzinfo=utc)
        usa, ind = ("USA", "UNITED_STATES_OF_AMERICA"), ("IND", "INDIA")
        rows = [  # psycopg2 returns real datetimes/bools; is_contributor arrives as NULL
            ("O1", "small", "non_profit", "233.1", oct_4, True, None, *usa),
            ("O3", "medium", "non_profit", "101.5", sep_28, True, None, *ind),
        ]
        cursor = FakeCursor(
            tables={
                "organizations": org_table_columns,
                "state": ["state_id", "country_id"],
                "country": ["country_id", "country_code", "country_name"],
            },
            org_rows=(self.ORG_SELECT, rows),
            country_rows=(["country_code", "country_name"], [("USA", "UNITED_STATES_OF_AMERICA")]),
        )
        connection = FakeConnection(cursor)
        env = {
            "USE_MOCK_DATA": "false", "DB_HOST": "db", "DB_NAME": "saayam", "DB_USER": "analytics",
        }
        with mock.patch.dict(os.environ, env), mock.patch.object(
            sca, "psycopg2", types.SimpleNamespace(connect=lambda **kwargs: connection)
        ):
            result = sca.lambda_handler({}, None)
        return result, connection

    def test_database_rows_flow_through_the_same_logic(self):
        columns = ["org_id", "org_size", "org_type", "state_id", "created_at", "is_collaborator"]
        result, connection = self.run_db(columns)  # no is_contributor column at all
        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertEqual(body["30D"]["organizations_by_size"], sizes(("medium", 1), ("small", 1)))
        self.assertEqual(body["30D"]["collaborator_vs_contributor"], flags(2, 100.0, 0, 0.0))
        self.assertTrue(connection.closed)
        self.assertEqual(connection.session, {"readonly": True, "autocommit": True})

    def test_missing_database_column_is_reported_clearly(self):
        with self.assertLogs(sca.logger, level="ERROR") as logs:
            result, connection = self.run_db(["org_id", "org_type", "state_id", "created_at"])
        self.assertEqual(result["statusCode"], 500)
        self.assertIn("missing required column(s): org_size", str(logs.records[0].exc_info[1]))
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
