"""
Tests for steward_volunteer_review_api.

Runs fully offline. Unit tests stub psycopg2/boto3 and use fake regional
cursors. Integration tests load users.csv and volunteer_applications.csv into
in-memory SQLite under the real schema names and exercise the handler's actual
SQL, and are skipped if the CSVs are not present.

    python -m unittest test_steward_volunteer_review_api -v
    pytest test_steward_volunteer_review_api.py -v
"""

import json
import os
import unittest
from datetime import datetime
from unittest import mock

from local_invoke import build_csv_connection, install_stubs

install_stubs()

import steward_volunteer_review_api as api  # noqa: E402

CSV_DIR = os.environ.get("LOCAL_CSV_DIR", "/mnt/user-data/uploads")
CSV_AVAILABLE = all(
    os.path.exists(os.path.join(CSV_DIR, name))
    for name in ("users.csv", "volunteer_applications.csv")
)

BASE_ENV = {
    "REVIEW_REGIONS": "Virginia,Ireland",
    "REVIEW_APPLICATION_STATUSES": "UNDER_REVIEW",
    "DB_PARAM_PATH_VIRGINIA": "/dev/saayam/db/Virginia/Analytics/user",
    "DB_PARAM_PATH_IRELAND": "/dev/saayam/db/Ireland/Analytics/user",
}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeCursor:
    def __init__(self, region, rows):
        self.region = region
        self._rows = rows
        self._result = None
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "COUNT(*)" in sql:
            self._result = [(len(self._rows),)]
        else:
            limit = params[-1]
            self._result = self._rows[:limit]

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result


class FakeConnection:
    def __init__(self, region, rows):
        self.region = region
        self.cursor_obj = FakeCursor(region, rows)
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def make_rows(count, start=1, hour=12):
    """Rows as psycopg2 returns them: tuples of (user_id, datetime)."""
    return [
        (
            f"SID-00-000-000-{index:03d}",
            datetime(2026, 5, 12, hour, 0, max(0, 59 - index)),
        )
        for index in range(start, start + count)
    ]


def body_of(response):
    return json.loads(response["body"])


def patched_env(**overrides):
    env = dict(BASE_ENV)
    env.update(overrides)
    return mock.patch.dict(api.os.environ, env, clear=False)


def invoke(event, connections):
    """Run the handler with one fake connection per region."""
    with mock.patch.object(api, "get_db_config", side_effect=lambda r: {"region": r}):
        with mock.patch.object(
            api.psycopg2, "connect", side_effect=lambda **kw: connections[kw["region"]]
        ):
            return api.lambda_handler(event, None)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class ConfigTests(unittest.TestCase):
    def test_regions_default_to_both_databases(self):
        with patched_env():
            self.assertEqual(api.get_regions(), ["Virginia", "Ireland"])

    def test_single_region_can_be_configured(self):
        with patched_env(REVIEW_REGIONS="Virginia"):
            self.assertEqual(api.get_regions(), ["Virginia"])

    def test_unknown_region_raises(self):
        with patched_env(REVIEW_REGIONS="Atlantis"):
            with self.assertRaises(ValueError):
                api.get_regions()

    def test_statuses_default_to_both_review_values(self):
        """The enum was renamed mid-migration, so both values are accepted."""
        with mock.patch.dict(api.os.environ, {}, clear=True):
            self.assertEqual(
                api.get_review_statuses(), ["IN_REVIEW", "UNDER_REVIEW"]
            )

    def test_multiple_statuses_are_supported(self):
        with patched_env(REVIEW_APPLICATION_STATUSES="under_review, submitted"):
            self.assertEqual(
                api.get_review_statuses(), ["UNDER_REVIEW", "SUBMITTED"]
            )

    def test_missing_parameter_path_raises(self):
        with mock.patch.dict(api.os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                api.get_db_config("Virginia")


class PaginationParsingTests(unittest.TestCase):
    def test_defaults_when_payload_is_empty(self):
        self.assertEqual(api.parse_pagination({}), (1, 5))

    def test_string_values_are_coerced(self):
        self.assertEqual(api.parse_pagination({"page": "3", "page_size": "25"}), (3, 25))

    def test_rows_per_page_selection_is_honoured(self):
        for size in (5, 10, 25, 50, 100):
            self.assertEqual(api.parse_pagination({"page_size": size})[1], size)

    def test_rejects_zero_negative_and_oversized_values(self):
        for payload in ({"page": 0}, {"page": -1}, {"page_size": "abc"}, {"page_size": 101}):
            with self.assertRaises(api.ValidationError):
                api.parse_pagination(payload)


class PayloadParsingTests(unittest.TestCase):
    def test_api_gateway_string_body(self):
        event = {"body": json.dumps({"page": 2, "page_size": 10})}
        self.assertEqual(api.parse_event_body(event), {"page": 2, "page_size": 10})

    def test_direct_invoke_dict(self):
        self.assertEqual(api.parse_event_body({"page": 4}), {"page": 4})

    def test_query_string_parameters(self):
        event = {"body": None, "queryStringParameters": {"page": "2"}}
        self.assertEqual(api.parse_event_body(event), {"page": "2"})


class TimestampTests(unittest.TestCase):
    def test_datetime_is_iso_utc(self):
        self.assertEqual(
            api.format_timestamp(datetime(2026, 5, 12, 7, 15, 0)), "2026-05-12T07:15:00Z"
        )

    def test_string_with_milliseconds_is_normalised(self):
        self.assertEqual(
            api.format_timestamp("2026-06-19 08:13:21.000"), "2026-06-19T08:13:21Z"
        )

    def test_blank_and_none_are_none(self):
        self.assertIsNone(api.format_timestamp(None))
        self.assertIsNone(api.format_timestamp("  "))


class MergeTests(unittest.TestCase):
    def _row(self, user_id, updated_time):
        return {
            "user_id": user_id,
            "updated_time": updated_time,
            "volunteer_review": "Review",
        }

    def test_regions_interleave_by_updated_time(self):
        virginia = [self._row("V1", "2026-05-12T10:00:00Z"), self._row("V2", "2026-05-10T10:00:00Z")]
        ireland = [self._row("I1", "2026-05-11T10:00:00Z"), self._row("I2", "2026-05-09T10:00:00Z")]

        merged = api.merge_review_requests([virginia, ireland], 1, 4)
        self.assertEqual([row["user_id"] for row in merged], ["V1", "I1", "V2", "I2"])

    def test_slice_respects_page_offset(self):
        virginia = [self._row("V1", "2026-05-12T10:00:00Z"), self._row("V2", "2026-05-10T10:00:00Z")]
        ireland = [self._row("I1", "2026-05-11T10:00:00Z"), self._row("I2", "2026-05-09T10:00:00Z")]

        merged = api.merge_review_requests([virginia, ireland], 2, 2)
        self.assertEqual([row["user_id"] for row in merged], ["V2", "I2"])

    def test_page_past_the_end_is_empty(self):
        merged = api.merge_review_requests([[self._row("V1", "2026-05-12T10:00:00Z")]], 5, 5)
        self.assertEqual(merged, [])


class HandlerTests(unittest.TestCase):
    def setUp(self):
        patcher = patched_env()
        patcher.start()
        self.addCleanup(patcher.stop)

    def _connections(self, virginia_rows, ireland_rows):
        return {
            "Virginia": FakeConnection("Virginia", virginia_rows),
            "Ireland": FakeConnection("Ireland", ireland_rows),
        }

    def test_happy_path_shape_matches_contract(self):
        connections = self._connections(make_rows(12), make_rows(8, start=100, hour=9))
        response = invoke({"page": 1, "page_size": 5}, connections)
        body = body_of(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(len(body["data"]), 5)
        self.assertEqual(
            body["pagination"],
            {"current_page": 1, "page_size": 5, "total_records": 20, "total_pages": 4},
        )
        first = body["data"][0]
        self.assertEqual(sorted(first), ["updated_time", "user_id", "volunteer_review"])
        self.assertEqual(first["volunteer_review"], "Review")
        self.assertRegex(first["updated_time"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_totals_sum_across_regions(self):
        connections = self._connections(make_rows(7), make_rows(3, start=50))
        body = body_of(invoke({"page": 1, "page_size": 5}, connections))
        self.assertEqual(body["pagination"]["total_records"], 10)
        self.assertEqual(body["pagination"]["total_pages"], 2)

    def test_statuses_are_bound_parameters(self):
        connections = self._connections(make_rows(5), [])
        with patched_env(REVIEW_APPLICATION_STATUSES="UNDER_REVIEW,SUBMITTED"):
            invoke({"page": 1, "page_size": 5}, connections)

        count_sql, count_params = connections["Virginia"].cursor_obj.executed[0]
        self.assertIn("application_status::text IN (%s, %s)", count_sql)
        self.assertEqual(count_params, ("UNDER_REVIEW", "SUBMITTED"))
        self.assertNotIn("UNDER_REVIEW", count_sql)

    def test_each_region_fetches_enough_rows_for_the_page(self):
        connections = self._connections(make_rows(30), make_rows(30, start=100))
        invoke({"page": 3, "page_size": 5}, connections)

        _select_sql, select_params = connections["Virginia"].cursor_obj.executed[1]
        self.assertEqual(select_params[-1], 15)  # offset 10 + page_size 5

    def test_query_targets_applications_and_users(self):
        connections = self._connections(make_rows(5), [])
        invoke({"page": 1, "page_size": 5}, connections)

        select_sql = connections["Virginia"].cursor_obj.executed[1][0]
        self.assertIn("virginia_dev_saayam_rdbms.volunteer_applications", select_sql)
        self.assertIn("virginia_dev_saayam_rdbms.users", select_sql)
        self.assertIn("u.user_id = va.user_id", select_sql)
        self.assertIn("ORDER BY va.last_updated_at DESC", select_sql)

    def test_results_are_newest_first(self):
        connections = self._connections(make_rows(6), make_rows(6, start=200, hour=15))
        body = body_of(invoke({"page": 1, "page_size": 10}, connections))
        times = [row["updated_time"] for row in body["data"]]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_no_records_returns_success_with_empty_array(self):
        connections = self._connections([], [])
        body = body_of(invoke({"page": 1, "page_size": 5}, connections))

        self.assertEqual(body["data"], [])
        self.assertEqual(body["pagination"]["total_records"], 0)
        self.assertEqual(body["pagination"]["total_pages"], 0)
        # count only, the select is skipped for an empty region
        self.assertEqual(len(connections["Virginia"].cursor_obj.executed), 1)

    def test_empty_second_region_does_not_break_the_page(self):
        connections = self._connections(make_rows(10), [])
        body = body_of(invoke({"page": 1, "page_size": 5}, connections))
        self.assertEqual(len(body["data"]), 5)
        self.assertEqual(body["pagination"]["total_records"], 10)

    def test_page_beyond_last_page_returns_empty_array(self):
        connections = self._connections(make_rows(10), [])
        body = body_of(invoke({"page": 9, "page_size": 5}, connections))
        self.assertEqual(body["data"], [])
        self.assertEqual(body["pagination"]["current_page"], 9)

    def test_invalid_input_returns_400(self):
        connections = self._connections(make_rows(5), [])
        response = invoke({"page": 0}, connections)
        body = body_of(response)

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(body["data"], [])

    def test_database_error_returns_safe_500(self):
        connections = self._connections(make_rows(5), [])
        connections["Virginia"].cursor_obj.execute = mock.Mock(
            side_effect=Exception("FATAL: password authentication failed for host 10.0.4.11")
        )
        with self.assertLogs(api.LOGGER, level="ERROR"):
            response = invoke({"page": 1, "page_size": 5}, connections)
        body = body_of(response)

        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(body["data"], [])
        self.assertEqual(body["message"], api.GENERIC_ERROR_MESSAGE)
        self.assertNotIn("10.0.4.11", response["body"])
        self.assertNotIn("password", response["body"])

    def test_connections_are_closed_even_on_failure(self):
        connections = self._connections(make_rows(5), [])
        connections["Ireland"].cursor_obj.execute = mock.Mock(
            side_effect=Exception("boom")
        )
        with self.assertLogs(api.LOGGER, level="ERROR"):
            invoke({"page": 1, "page_size": 5}, connections)

        self.assertTrue(connections["Virginia"].closed)
        self.assertTrue(connections["Ireland"].closed)

    def test_connections_are_closed_on_success(self):
        connections = self._connections(make_rows(5), [])
        invoke({"page": 1, "page_size": 5}, connections)
        self.assertTrue(all(c.closed for c in connections.values()))


# ---------------------------------------------------------------------------
# Integration tests against the real CSV extracts
# ---------------------------------------------------------------------------

@unittest.skipUnless(CSV_AVAILABLE, f"CSV extracts not found in {CSV_DIR}")
class CsvIntegrationTests(unittest.TestCase):
    """Runs the handler's real SQL over users.csv and volunteer_applications.csv."""

    @classmethod
    def setUpClass(cls):
        cls.connection = build_csv_connection(CSV_DIR)

    def _invoke(self, page, page_size, statuses="UNDER_REVIEW"):
        with patched_env(REVIEW_APPLICATION_STATUSES=statuses):
            with mock.patch.object(
                api, "get_db_config", side_effect=lambda r: {"region": r}
            ):
                with mock.patch.object(
                    api.psycopg2, "connect", side_effect=lambda **kw: self.connection
                ):
                    response = api.lambda_handler(
                        {"body": json.dumps({"page": page, "page_size": page_size})},
                        None,
                    )
        self.assertEqual(response["statusCode"], 200)
        return body_of(response)

    def test_only_under_review_applications_are_returned(self):
        body = self._invoke(1, 5)
        self.assertEqual(body["pagination"]["total_records"], 10)
        self.assertEqual(body["pagination"]["total_pages"], 2)

    def test_widening_the_status_list_returns_more(self):
        body = self._invoke(1, 5, statuses="UNDER_REVIEW,SUBMITTED")
        self.assertEqual(body["pagination"]["total_records"], 19)

    def test_first_page_is_newest_first(self):
        body = self._invoke(1, 10)
        times = [row["updated_time"] for row in body["data"]]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertEqual(body["data"][0]["user_id"], "SID-00-000-000-371")
        self.assertEqual(body["data"][0]["updated_time"], "2026-06-19T08:13:21Z")

    def test_paging_covers_every_record_exactly_once(self):
        ids = [row["user_id"] for row in self._invoke(1, 5)["data"]]
        ids += [row["user_id"] for row in self._invoke(2, 5)["data"]]

        self.assertEqual(len(ids), 10)
        self.assertEqual(len(set(ids)), 10)
        self.assertEqual(ids, [row["user_id"] for row in self._invoke(1, 10)["data"]])

    def test_every_row_is_usable_by_the_frontend(self):
        for row in self._invoke(1, 10)["data"]:
            self.assertTrue(row["user_id"].startswith("SID-"))
            self.assertRegex(
                row["updated_time"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
            )
            self.assertEqual(row["volunteer_review"], "Review")

    def test_page_past_the_end_is_empty(self):
        body = self._invoke(50, 5)
        self.assertEqual(body["data"], [])
        self.assertEqual(body["pagination"]["total_records"], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
