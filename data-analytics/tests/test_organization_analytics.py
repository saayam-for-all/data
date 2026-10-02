"""Unit + mock-DB tests for the Organization Analytics API (issue #228).

Stdlib `unittest` only -- the repo pins no test framework in
data-engineering/requirements.txt, so these run with plain `python -m unittest`
and need no PostgreSQL instance.

The mock layer is a FakeCursor/FakeConnection pair that classifies each SQL
string by a marker unique to the query that produced it and replays canned
rows. That is enough to drive lambda_handler end to end -- including the
graceful-degradation paths -- without a SQL engine.

Run from anywhere:
    python data-analytics/tests/test_organization_analytics.py
    python -m unittest discover -s data-analytics/tests -v
"""

import json
import os
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from psycopg2 import errorcodes

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lambda_functions"),
)

import organization_analytics as oa  # noqa: E402


# ---------------------------------------------------------------------------
# Fake database layer
# ---------------------------------------------------------------------------

SUMMARY = "summary"
GROWTH = "growth_trend"
LOCATION = "location"
SIZE = "size"
COLLABORATOR = "collaborator"
RATING = "rating"
ORG_TYPE = "org_type"


class FakeUndefinedColumn(Exception):
    """Shaped like psycopg2's UndefinedColumn: carries pgcode 42703."""

    pgcode = errorcodes.UNDEFINED_COLUMN

    def __init__(self, message='column o.is_contributor does not exist'):
        super().__init__(message)


class FakeQueryError(Exception):
    """A generic mid-query failure that is NOT an undefined-column error."""


def classify_query(query):
    """Maps a SQL string to the fetch_* function that built it.

    Ordered most-specific first: several queries share tokens (e.g. both the
    summary and collaborator queries select total_organizations), so each test
    keys off a marker that appears in exactly one query.
    """
    if "average_org_rating" in query:
        return SUMMARY
    if "collaborator_count" in query:
        return COLLABORATOR
    if "organizations_in_period" in query:
        return GROWTH
    if "for_profit_in_period" in query:
        return ORG_TYPE
    if "org_rating AS rating" in query:
        return RATING
    if "org_size" in query:
        return SIZE
    if "state_name" in query:
        return LOCATION
    raise AssertionError(f"FakeCursor saw an unrecognized query:\n{query}")


def populated_rows(kind, query):
    """Canned result rows for a database that has data.

    Numeric columns deliberately use Decimal wherever the real query wraps a
    count in SUM(...) OVER (...) or ROUND(...), because Postgres returns
    numeric there and psycopg2 hands back Decimal -- that is what the int()
    and float() casts in the fetch_* functions exist to absorb.
    """
    if kind == SUMMARY:
        return [{
            "total_organizations": 20,
            "total_collaborators": 8,
            # The fallback query selects a literal NULL for this column.
            "total_contributors": 5 if "is_contributor" in query else None,
            "average_org_rating": Decimal("3.75"),
        }]
    if kind == COLLABORATOR:
        row = {"total_organizations": 20, "collaborator_count": 8}
        if "is_contributor" in query:
            row["contributor_count"] = 5
        return [row]
    if kind == GROWTH:
        return [
            {"period": "2025-01", "total_organizations": Decimal(5), "total_collaborators": Decimal(2)},
            {"period": "2025-02", "total_organizations": Decimal(12), "total_collaborators": Decimal(7)},
        ]
    if kind == LOCATION:
        return [
            {"state_id": "CA", "state_name": "California",
             "organization_count": 12, "percentage": Decimal("60.00")},
            {"state_id": "NY", "state_name": "New York",
             "organization_count": 8, "percentage": Decimal("40.00")},
        ]
    if kind == SIZE:
        return [
            {"org_size": "Medium", "organization_count": 8},
            {"org_size": "Small", "organization_count": 7},
            {"org_size": "Large", "organization_count": 5},
        ]
    if kind == RATING:
        # Only ratings 3 and 5 occur; 1, 2 and 4 must still be backfilled.
        return [
            {"rating": 3, "organization_count": 4},
            {"rating": 5, "organization_count": 6},
        ]
    if kind == ORG_TYPE:
        return [
            {"period": "2025-01", "for_profit": Decimal(2), "non_profit": Decimal(3)},
            {"period": "2025-02", "for_profit": Decimal(5), "non_profit": Decimal(7)},
        ]
    raise AssertionError(f"no populated rows defined for {kind}")


def empty_rows(kind, query):
    """Canned rows for a database with zero matching organizations.

    Un-grouped aggregates still return exactly one row in real SQL (COUNT(*)
    over no rows is 0, AVG is NULL); only the GROUP BY queries come back with
    no rows at all.
    """
    if kind == SUMMARY:
        return [{
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0 if "is_contributor" in query else None,
            "average_org_rating": None,
        }]
    if kind == COLLABORATOR:
        row = {"total_organizations": 0, "collaborator_count": 0}
        if "is_contributor" in query:
            row["contributor_count"] = 0
        return [row]
    return []


class FakeConnection:
    def __init__(self):
        self.rollback_count = 0
        self.closed = False
        self.cursors = []

    def cursor(self, cursor_factory=None):
        self.cursor_factory = cursor_factory
        cur = FakeCursor(self)
        self.cursors.append(cur)
        return cur

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        self.closed = True


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self._rows = []
        self.executed = []
        self.closed = False

    # -- knobs the tests set on the owning connection ----------------------
    @property
    def _cfg(self):
        return self.connection

    def execute(self, query, params=None):
        kind = classify_query(query)
        self.executed.append((kind, list(params or [])))

        if kind in getattr(self._cfg, "fail_kinds", ()):
            raise FakeQueryError(f"simulated failure running the {kind} query")

        if "is_contributor" in query and not getattr(self._cfg, "has_contributor", True):
            raise FakeUndefinedColumn()

        row_source = empty_rows if getattr(self._cfg, "empty", False) else populated_rows
        self._rows = row_source(kind, query)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        self.closed = True


def make_connection(has_contributor=True, fail_kinds=(), empty=False):
    conn = FakeConnection()
    conn.has_contributor = has_contributor
    conn.fail_kinds = set(fail_kinds)
    conn.empty = empty
    return conn


def invoke(payload, connection=None, as_string_body=True):
    """Runs lambda_handler against a fake connection; returns (response, conn)."""
    conn = connection if connection is not None else make_connection()
    body = json.dumps(payload) if as_string_body else payload
    with patch.object(oa, "get_db_connection", return_value=conn):
        response = oa.lambda_handler({"body": body}, None)
    return response, conn


def body_of(response):
    return json.loads(response["body"])


# ---------------------------------------------------------------------------
# Pure unit tests
# ---------------------------------------------------------------------------

class TestParseFilters(unittest.TestCase):
    def test_defaults_when_body_is_empty(self):
        self.assertEqual(oa.parse_filters({}), {
            "time_filter": "ALL",
            "start_date": None,
            "end_date": None,
            "group_by": "monthly",
            "region": "ALL",
            "organization_type": "ALL",
        })

    def test_none_body_uses_defaults(self):
        self.assertEqual(oa.parse_filters(None)["time_filter"], "ALL")

    def test_every_valid_time_filter(self):
        for value in ["7D", "30D", "1Y", "ALL"]:
            with self.subTest(time_filter=value):
                self.assertEqual(oa.parse_filters({"time_filter": value})["time_filter"], value)

    def test_custom_time_filter_with_dates(self):
        filters = oa.parse_filters({
            "time_filter": "CUSTOM",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
        })
        self.assertEqual(filters["time_filter"], "CUSTOM")
        self.assertEqual(filters["start_date"], "2026-01-01")
        self.assertEqual(filters["end_date"], "2026-06-30")

    def test_time_filter_is_case_insensitive(self):
        self.assertEqual(oa.parse_filters({"time_filter": "30d"})["time_filter"], "30D")
        self.assertEqual(oa.parse_filters({"time_filter": " 1y "})["time_filter"], "1Y")

    def test_group_by_is_case_insensitive(self):
        self.assertEqual(oa.parse_filters({"group_by": "MONTHLY"})["group_by"], "monthly")
        self.assertEqual(oa.parse_filters({"group_by": " Daily "})["group_by"], "daily")

    def test_invalid_time_filter_raises(self):
        with self.assertRaises(ValueError) as ctx:
            oa.parse_filters({"time_filter": "90D"})
        self.assertIn("time_filter", str(ctx.exception))

    def test_invalid_group_by_raises(self):
        with self.assertRaises(ValueError) as ctx:
            oa.parse_filters({"group_by": "hourly"})
        self.assertIn("group_by", str(ctx.exception))

    def test_custom_without_dates_raises(self):
        for payload in [
            {"time_filter": "CUSTOM"},
            {"time_filter": "CUSTOM", "start_date": "2026-01-01"},
            {"time_filter": "CUSTOM", "end_date": "2026-06-30"},
        ]:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    oa.parse_filters(payload)

    def test_region_all_passthrough_and_case_handling(self):
        self.assertEqual(oa.parse_filters({})["region"], "ALL")
        self.assertEqual(oa.parse_filters({"region": "all"})["region"], "ALL")
        self.assertEqual(oa.parse_filters({"region": "AlL"})["region"], "ALL")
        # A real region keeps its original casing -- it is matched against
        # states.state_name verbatim.
        self.assertEqual(oa.parse_filters({"region": " California "})["region"], "California")

    def test_organization_type_normalization(self):
        cases = {
            "ALL": "ALL",
            "all": "ALL",
            "non_profit": "non_profit",
            "Non-Profit": "non_profit",
            "NON PROFIT": "non_profit",
            "For-profit": "for_profit",
            "for profit": "for_profit",
        }
        for raw, expected in cases.items():
            with self.subTest(organization_type=raw):
                self.assertEqual(
                    oa.parse_filters({"organization_type": raw})["organization_type"], expected
                )

    def test_invalid_organization_type_raises(self):
        with self.assertRaises(ValueError) as ctx:
            oa.parse_filters({"organization_type": "charity"})
        self.assertIn("organization_type", str(ctx.exception))

    def test_explicit_nulls_fall_back_to_defaults(self):
        # The ticket's sample payloads send start_date/end_date as JSON null.
        filters = oa.parse_filters({
            "time_filter": "30D", "start_date": None, "end_date": None,
            "group_by": "daily", "region": "ALL", "organization_type": "ALL",
        })
        self.assertIsNone(filters["start_date"])
        self.assertIsNone(filters["end_date"])


class TestBuildDateFilter(unittest.TestCase):
    def test_all_returns_no_condition(self):
        self.assertEqual(oa.build_date_filter("ALL"), ("", ()))

    def test_relative_windows(self):
        clause, params = oa.build_date_filter("7D")
        self.assertEqual(clause, "created_at >= CURRENT_DATE - INTERVAL '7 days'")
        self.assertEqual(params, ())

        clause, params = oa.build_date_filter("30D")
        self.assertEqual(clause, "created_at >= CURRENT_DATE - INTERVAL '30 days'")
        self.assertEqual(params, ())

        clause, params = oa.build_date_filter("1Y")
        self.assertEqual(clause, "created_at >= CURRENT_DATE - INTERVAL '1 year'")
        self.assertEqual(params, ())

    def test_custom_with_dates_uses_between(self):
        clause, params = oa.build_date_filter("CUSTOM", "2026-01-01", "2026-06-30")
        self.assertEqual(clause, "created_at BETWEEN %s AND %s")
        self.assertEqual(params, ("2026-01-01", "2026-06-30"))

    def test_custom_without_dates_falls_back_to_no_condition(self):
        self.assertEqual(oa.build_date_filter("CUSTOM"), ("", ()))
        self.assertEqual(oa.build_date_filter("CUSTOM", "2026-01-01", None), ("", ()))
        self.assertEqual(oa.build_date_filter("CUSTOM", None, "2026-06-30"), ("", ()))

    def test_column_override(self):
        clause, _ = oa.build_date_filter("7D", column="o.created_at")
        self.assertEqual(clause, "o.created_at >= CURRENT_DATE - INTERVAL '7 days'")

        clause, params = oa.build_date_filter("CUSTOM", "2026-01-01", "2026-06-30", column="o.created_at")
        self.assertEqual(clause, "o.created_at BETWEEN %s AND %s")
        self.assertEqual(params, ("2026-01-01", "2026-06-30"))


class TestGetGrouping(unittest.TestCase):
    def test_all_valid_group_by_values(self):
        self.assertEqual(oa.get_grouping("daily"), ("day", "YYYY-MM-DD"))
        self.assertEqual(oa.get_grouping("weekly"), ("week", "YYYY-MM-DD"))
        self.assertEqual(oa.get_grouping("monthly"), ("month", "YYYY-MM"))
        self.assertEqual(oa.get_grouping("yearly"), ("year", "YYYY"))

    def test_invalid_group_by_raises(self):
        with self.assertRaises(ValueError):
            oa.get_grouping("hourly")


class TestBuildCommonWhere(unittest.TestCase):
    @staticmethod
    def filters(**overrides):
        base = {
            "time_filter": "ALL", "start_date": None, "end_date": None,
            "group_by": "monthly", "region": "ALL", "organization_type": "ALL",
        }
        base.update(overrides)
        return base

    def test_no_filters_produces_empty_clause(self):
        clause, params = oa.build_common_where(self.filters())
        self.assertEqual(clause, "")
        self.assertEqual(params, [])

    def test_region_filter_uses_states_subquery(self):
        clause, params = oa.build_common_where(self.filters(region="California"))
        self.assertIn("o.state_id IN (SELECT state_id FROM", clause)
        self.assertIn("WHERE state_name = %s", clause)
        self.assertEqual(params, ["California"])

    def test_organization_type_filter_normalizes_column(self):
        clause, params = oa.build_common_where(self.filters(organization_type="non_profit"))
        self.assertIn("LOWER(REPLACE(REPLACE(o.org_type, '-', '_'), ' ', '_')) = %s", clause)
        self.assertEqual(params, ["non_profit"])

    def test_date_filter_included(self):
        clause, params = oa.build_common_where(self.filters(time_filter="7D"))
        self.assertEqual(clause, "o.created_at >= CURRENT_DATE - INTERVAL '7 days'")
        self.assertEqual(params, [])

    def test_custom_date_params_come_first(self):
        clause, params = oa.build_common_where(self.filters(
            time_filter="CUSTOM", start_date="2026-01-01", end_date="2026-06-30",
            region="California",
        ))
        self.assertTrue(clause.startswith("o.created_at BETWEEN %s AND %s AND "))
        self.assertEqual(params, ["2026-01-01", "2026-06-30", "California"])

    def test_all_conditions_combined_with_and(self):
        clause, params = oa.build_common_where(self.filters(
            time_filter="1Y", region="California", organization_type="for_profit",
        ))
        self.assertEqual(clause.count(" AND "), 2)
        self.assertEqual(params, ["California", "for_profit"])

    def test_alias_is_honored(self):
        clause, _ = oa.build_common_where(self.filters(time_filter="30D", region="California"), alias="org")
        self.assertIn("org.created_at", clause)
        self.assertIn("org.state_id", clause)


class TestIsUndefinedColumnError(unittest.TestCase):
    def test_detects_pgcode_42703(self):
        # pgcode alone is enough -- the message here says nothing useful.
        exc = FakeUndefinedColumn("relation error")
        self.assertTrue(oa.is_undefined_column_error(exc))

    def test_detects_message_without_pgcode(self):
        self.assertTrue(
            oa.is_undefined_column_error(Exception('column "is_contributor" does not exist'))
        )

    def test_detects_real_psycopg2_undefined_column(self):
        from psycopg2 import errors
        self.assertTrue(
            oa.is_undefined_column_error(errors.UndefinedColumn("column o.is_contributor does not exist"))
        )

    def test_does_not_false_positive(self):
        self.assertFalse(oa.is_undefined_column_error(Exception("connection reset by peer")))
        self.assertFalse(oa.is_undefined_column_error(FakeQueryError("division by zero")))

        syntax_error = Exception("syntax error at or near GROUP")
        syntax_error.pgcode = errorcodes.SYNTAX_ERROR
        self.assertFalse(oa.is_undefined_column_error(syntax_error))


# ---------------------------------------------------------------------------
# Mock-DB tests: lambda_handler end to end
# ---------------------------------------------------------------------------

EXPECTED_SECTIONS = [
    "summary",
    "growth_trend",
    "organizations_by_location",
    "organizations_by_size",
    "collaborator_vs_contributor",
    "rating_distribution",
    "organization_type_distribution",
]


class TestHandlerValidFilters(unittest.TestCase):
    def assert_full_shape(self, body):
        self.assertEqual(sorted(body.keys()), sorted(EXPECTED_SECTIONS))
        for key in EXPECTED_SECTIONS:
            self.assertIsNotNone(body[key], f"{key} missing from response")

    def test_default_filters(self):
        response, conn = invoke({})
        self.assertEqual(response["statusCode"], 200)
        body = body_of(response)
        self.assert_full_shape(body)

        self.assertEqual(body["summary"], {
            "total_organizations": 20,
            "total_collaborators": 8,
            "total_contributors": 5,
            "average_org_rating": 3.75,
        })
        self.assertEqual(body["growth_trend"], [
            {"period": "2025-01", "total_organizations": 5, "total_collaborators": 2},
            {"period": "2025-02", "total_organizations": 12, "total_collaborators": 7},
        ])
        self.assertEqual(body["organizations_by_location"][0], {
            "state_id": "CA", "state_name": "California",
            "organization_count": 12, "percentage": 60.0,
        })
        self.assertEqual(body["organizations_by_size"][0],
                         {"org_size": "Medium", "organization_count": 8})
        self.assertEqual(body["collaborator_vs_contributor"], [
            {"type": "collaborator", "organization_count": 8, "percentage": 40.0},
            {"type": "contributor", "organization_count": 5, "percentage": 25.0},
        ])
        self.assertEqual(body["organization_type_distribution"], [
            {"period": "2025-01", "for_profit": 2, "non_profit": 3, "total": 5},
            {"period": "2025-02", "for_profit": 5, "non_profit": 7, "total": 12},
        ])
        self.assertEqual(conn.rollback_count, 0)
        self.assertTrue(conn.closed)
        self.assertTrue(conn.cursors[0].closed)

    def test_cumulative_totals_serialize_as_numbers_not_strings(self):
        # Regression guard: SUM(...) OVER (...) returns Decimal, and
        # build_response uses json.dumps(default=str), so a missing int()
        # cast would silently produce "5" instead of 5.
        body = body_of(invoke({})[0])
        for entry in body["growth_trend"]:
            self.assertIsInstance(entry["total_organizations"], int)
            self.assertIsInstance(entry["total_collaborators"], int)
        for entry in body["organization_type_distribution"]:
            self.assertIsInstance(entry["for_profit"], int)
            self.assertIsInstance(entry["non_profit"], int)
            self.assertIsInstance(entry["total"], int)

    def test_region_filter(self):
        response, conn = invoke({"time_filter": "1Y", "group_by": "monthly", "region": "California"})
        self.assertEqual(response["statusCode"], 200)
        self.assert_full_shape(body_of(response))
        # Every query carries the region parameter through.
        for kind, params in conn.cursors[0].executed:
            self.assertIn("California", params, f"{kind} query dropped the region filter")

    def test_organization_type_filter(self):
        response, conn = invoke({"time_filter": "1Y", "organization_type": "Non-Profit"})
        self.assertEqual(response["statusCode"], 200)
        self.assert_full_shape(body_of(response))
        for kind, params in conn.cursors[0].executed:
            self.assertIn("non_profit", params, f"{kind} query dropped the organization_type filter")

    def test_custom_date_range(self):
        response, conn = invoke({
            "time_filter": "CUSTOM", "start_date": "2026-01-01", "end_date": "2026-06-30",
            "group_by": "monthly",
        })
        self.assertEqual(response["statusCode"], 200)
        self.assert_full_shape(body_of(response))
        for kind, params in conn.cursors[0].executed:
            self.assertIn("2026-01-01", params, f"{kind} query dropped start_date")
            self.assertIn("2026-06-30", params, f"{kind} query dropped end_date")

    def test_accepts_dict_body_as_well_as_string(self):
        response, _ = invoke({"time_filter": "1Y"}, as_string_body=False)
        self.assertEqual(response["statusCode"], 200)

    def test_response_headers_and_content_type(self):
        response, _ = invoke({})
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        self.assertEqual(response["headers"]["Access-Control-Allow-Origin"], "*")


class TestHandlerValidationErrors(unittest.TestCase):
    def test_invalid_time_filter_returns_400(self):
        response, _ = invoke({"time_filter": "90D"})
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("error", body_of(response))

    def test_invalid_group_by_returns_400(self):
        response, _ = invoke({"group_by": "hourly"})
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("error", body_of(response))

    def test_custom_without_dates_returns_400(self):
        response, _ = invoke({"time_filter": "CUSTOM"})
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("error", body_of(response))

    def test_invalid_organization_type_returns_400(self):
        response, _ = invoke({"organization_type": "charity"})
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("error", body_of(response))

    def test_validation_failure_never_opens_a_connection(self):
        with patch.object(oa, "get_db_connection", side_effect=AssertionError("should not connect")):
            response = oa.lambda_handler({"body": json.dumps({"time_filter": "90D"})}, None)
        self.assertEqual(response["statusCode"], 400)


class TestHandlerEmptyResults(unittest.TestCase):
    def setUp(self):
        self.response, self.conn = invoke({}, connection=make_connection(empty=True))
        self.body = body_of(self.response)

    def test_still_returns_200(self):
        self.assertEqual(self.response["statusCode"], 200)

    def test_summary_shows_zeros_and_null_rating(self):
        self.assertEqual(self.body["summary"], {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": None,
        })

    def test_rating_distribution_still_has_all_five_buckets(self):
        self.assertEqual(self.body["rating_distribution"], [
            {"rating": 1, "organization_count": 0},
            {"rating": 2, "organization_count": 0},
            {"rating": 3, "organization_count": 0},
            {"rating": 4, "organization_count": 0},
            {"rating": 5, "organization_count": 0},
        ])

    def test_list_sections_are_empty_lists_not_missing_keys(self):
        for key in ["growth_trend", "organizations_by_location", "organizations_by_size",
                    "organization_type_distribution"]:
            with self.subTest(section=key):
                self.assertIn(key, self.body)
                self.assertEqual(self.body[key], [])

    def test_collaborator_percentages_do_not_divide_by_zero(self):
        self.assertEqual(self.body["collaborator_vs_contributor"], [
            {"type": "collaborator", "organization_count": 0, "percentage": 0.0},
            {"type": "contributor", "organization_count": 0, "percentage": 0.0},
        ])

    def test_no_rollbacks_needed(self):
        self.assertEqual(self.conn.rollback_count, 0)


class TestHandlerPartialFailure(unittest.TestCase):
    def setUp(self):
        self.response, self.conn = invoke({}, connection=make_connection(fail_kinds=[SIZE]))
        self.body = body_of(self.response)

    def test_one_failing_query_does_not_break_the_response(self):
        self.assertEqual(self.response["statusCode"], 200)

    def test_failed_section_falls_back_to_its_default(self):
        self.assertEqual(self.body["organizations_by_size"], [])

    def test_other_sections_still_populate(self):
        self.assertEqual(self.body["summary"]["total_organizations"], 20)
        self.assertEqual(len(self.body["growth_trend"]), 2)
        self.assertEqual(len(self.body["organizations_by_location"]), 2)
        self.assertEqual(len(self.body["rating_distribution"]), 5)
        self.assertEqual(len(self.body["organization_type_distribution"]), 2)
        self.assertEqual(self.body["collaborator_vs_contributor"][0]["organization_count"], 8)

    def test_connection_rolled_back_once(self):
        self.assertEqual(self.conn.rollback_count, 1)

    def test_cursor_and_connection_still_closed(self):
        self.assertTrue(self.conn.closed)
        self.assertTrue(self.conn.cursors[0].closed)

    def test_summary_failure_falls_back_to_null_summary(self):
        response, _ = invoke({}, connection=make_connection(fail_kinds=[SUMMARY]))
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body_of(response)["summary"], {
            "total_organizations": None,
            "total_collaborators": None,
            "total_contributors": None,
            "average_org_rating": None,
        })

    def test_every_section_can_fail_independently(self):
        for kind in [SUMMARY, GROWTH, LOCATION, SIZE, COLLABORATOR, RATING, ORG_TYPE]:
            with self.subTest(failing=kind):
                response, _ = invoke({}, connection=make_connection(fail_kinds=[kind]))
                self.assertEqual(response["statusCode"], 200)
                self.assertEqual(sorted(body_of(response).keys()), sorted(EXPECTED_SECTIONS))


class TestHandlerMissingContributorColumn(unittest.TestCase):
    """The dev DB may not have is_contributor yet -- every query touching it
    must degrade instead of failing the request."""

    def setUp(self):
        self.response, self.conn = invoke({}, connection=make_connection(has_contributor=False))
        self.body = body_of(self.response)

    def test_still_returns_200(self):
        self.assertEqual(self.response["statusCode"], 200)

    def test_summary_total_contributors_is_null(self):
        self.assertIsNone(self.body["summary"]["total_contributors"])

    def test_summary_other_metrics_still_populate(self):
        self.assertEqual(self.body["summary"]["total_organizations"], 20)
        self.assertEqual(self.body["summary"]["total_collaborators"], 8)
        self.assertEqual(self.body["summary"]["average_org_rating"], 3.75)

    def test_contributor_entry_is_null_but_collaborator_survives(self):
        self.assertEqual(self.body["collaborator_vs_contributor"], [
            {"type": "collaborator", "organization_count": 8, "percentage": 40.0},
            {"type": "contributor", "organization_count": None, "percentage": None},
        ])

    def test_all_other_sections_unaffected(self):
        self.assertEqual(len(self.body["growth_trend"]), 2)
        self.assertEqual(len(self.body["organizations_by_location"]), 2)
        self.assertEqual(len(self.body["organizations_by_size"]), 3)
        self.assertEqual(len(self.body["rating_distribution"]), 5)
        self.assertEqual(len(self.body["organization_type_distribution"]), 2)

    def test_rolled_back_before_each_retry(self):
        # One rollback for fetch_summary, one for fetch_collaborator_vs_contributor.
        self.assertEqual(self.conn.rollback_count, 2)


class TestHandlerConnectionFailure(unittest.TestCase):
    def test_returns_500_with_error_key(self):
        with patch.object(oa, "get_db_connection",
                          side_effect=Exception("could not connect to server")):
            response = oa.lambda_handler({"body": json.dumps({})}, None)
        self.assertEqual(response["statusCode"], 500)
        self.assertIn("error", body_of(response))

    def test_missing_env_vars_surface_as_500(self):
        with patch.object(oa, "get_db_connection", side_effect=KeyError("PGHOST")):
            response = oa.lambda_handler({"body": json.dumps({})}, None)
        self.assertEqual(response["statusCode"], 500)
        self.assertIn("error", body_of(response))


if __name__ == "__main__":
    unittest.main(verbosity=2)
