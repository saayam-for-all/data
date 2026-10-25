"""
Unit tests for the Organization Analytics API.

These run entirely against a mock cursor, so no PostgreSQL instance, no AWS
access and no third party test runner are required:

    py -m unittest data-analytics/lambda_functions/test_organization_analytics.py
    py data-analytics/lambda_functions/test_organization_analytics.py
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import organization_analytics as oa


# ---------------------------------------------------------------------------
# Mock database plumbing
# ---------------------------------------------------------------------------

class QueryError(Exception):
    """Stands in for a psycopg2 error raised while running a query."""


def classify_query(query):
    """Map a generated SQL statement back to the dashboard section that built it."""
    if "information_schema.tables" in query:
        return "table_exists"
    if "information_schema.columns" in query:
        return "column_exists"
    if "new_for_profit" in query:
        return "organization_type_distribution"
    if "new_organizations" in query:
        return "growth_trend"
    if "average_org_rating" in query:
        return "summary"
    if "AS city_name" in query:
        return "organizations_by_location"
    if "AS org_size" in query:
        return "organizations_by_size"
    if "collaborator_count" in query:
        return "collaborator_vs_contributor"
    if "AS rating" in query:
        return "rating_distribution"
    return "unknown"


class MockCursor:
    """Records every statement it is given and replays canned rows back."""

    def __init__(self, rows=None, state_table="states", has_contributor=True, failing_sections=()):
        self.rows = rows or {}
        # Name of the state lookup the fake database has, or None if it has neither.
        self.state_table = state_table
        self.has_contributor = has_contributor
        self.failing_sections = set(failing_sections)
        self.executed = []
        self.closed = False
        self._result = []

    def execute(self, query, params=None):
        section = classify_query(query)
        self.executed.append((section, query, list(params or [])))

        if section in self.failing_sections:
            raise QueryError(f"simulated failure in {section}")

        if section == "table_exists":
            probed_table = params[1] if params and len(params) > 1 else None
            self._result = [{"?column?": 1}] if probed_table == self.state_table else []
        elif section == "column_exists":
            self._result = [{"?column?": 1}] if self.has_contributor else []
        else:
            self._result = self.rows.get(section, [])

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0] if self._result else None

    def close(self):
        self.closed = True

    # helpers used by the assertions
    def query_for(self, section):
        for recorded_section, query, _params in self.executed:
            if recorded_section == section:
                return query
        raise AssertionError(f"no query was executed for section {section!r}")

    def params_for(self, section):
        for recorded_section, _query, params in self.executed:
            if recorded_section == section:
                return params
        raise AssertionError(f"no query was executed for section {section!r}")

    def sections(self):
        return [section for section, _query, _params in self.executed]


class MockConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self, *args, **kwargs):
        return self._cursor

    def close(self):
        self.closed = True


DEFAULT_ROWS = {
    "summary": [
        {
            "total_organizations": 126,
            "total_collaborators": 42,
            "total_contributors": 84,
            "average_org_rating": 4.2,
        }
    ],
    "growth_trend": [
        {"period": "2026-01", "total_organizations": 100, "total_collaborators": 34},
        {"period": "2026-02", "total_organizations": 108, "total_collaborators": 36},
    ],
    "organizations_by_location": [
        {"state_id": "CA", "state_name": "California", "city_name": "San Jose", "organization_count": 20},
        {"state_id": "CA", "state_name": "California", "city_name": "Fresno", "organization_count": 12},
        {"state_id": "TX", "state_name": "Texas", "city_name": "Austin", "organization_count": 24},
    ],
    "organizations_by_size": [
        {"org_size": "small", "organization_count": 50},
        {"org_size": "medium", "organization_count": 45},
        {"org_size": "large", "organization_count": 31},
    ],
    "collaborator_vs_contributor": [{"collaborator_count": 42, "contributor_count": 84}],
    "rating_distribution": [
        {"rating": 1, "organization_count": 1},
        {"rating": 3, "organization_count": 12},
        {"rating": 4, "organization_count": 46},
        {"rating": 5, "organization_count": 64},
    ],
    "organization_type_distribution": [
        {"period": "2026-01", "for_profit": 41, "non_profit": 68},
        {"period": "2026-02", "for_profit": 43, "non_profit": 68},
    ],
}

BASE_PAYLOAD = {
    "time_filter": "30D",
    "start_date": None,
    "end_date": None,
    "group_by": "daily",
    "region": "ALL",
    "organization_type": "ALL",
}


def run_handler(payload, cursor):
    """Invoke lambda_handler with the database swapped out for the mock cursor."""
    connection = MockConnection(cursor)
    with mock.patch.object(oa, "get_db_connection", return_value=connection):
        response = oa.lambda_handler(payload, None)
    return response, json.loads(response["body"]), connection


def context_for(cursor):
    return oa.build_schema_context(cursor)


DEFAULT_CONTEXT = {
    "has_states": True,
    "state_table": "states",
    "has_contributor": True,
    "from_clause": (
        f"FROM {oa.ORGANIZATIONS_TABLE} o "
        f"LEFT JOIN {oa.SCHEMA_NAME}.states s ON o.state_id = s.state_id"
    ),
    "state_id_expression": "COALESCE(NULLIF(TRIM(o.state_id::text), ''), 'Unknown')",
    "state_name_expression": "COALESCE(NULLIF(TRIM(s.state_name), ''), NULLIF(TRIM(o.state_id::text), ''), 'Unknown')",
    "contributor_expression": "o.is_contributor IS TRUE",
}


# ---------------------------------------------------------------------------
# Filter validation
# ---------------------------------------------------------------------------

class TestFilterValidation(unittest.TestCase):

    def test_defaults_are_applied_for_an_empty_payload(self):
        filters = oa.parse_filters({})
        self.assertEqual(filters["time_filter"], "ALL")
        self.assertEqual(filters["group_by"], "monthly")
        self.assertEqual(filters["region"], "ALL")
        self.assertEqual(filters["organization_type"], "ALL")
        self.assertIsNone(filters["start_date"])
        self.assertIsNone(filters["end_date"])

    def test_all_supported_time_filters_are_accepted(self):
        for time_filter in ("7D", "30D", "1Y", "ALL"):
            with self.subTest(time_filter=time_filter):
                self.assertEqual(
                    oa.parse_filters({"time_filter": time_filter})["time_filter"],
                    time_filter,
                )

    def test_all_supported_group_by_values_are_accepted(self):
        for group_by in ("daily", "weekly", "monthly", "yearly"):
            with self.subTest(group_by=group_by):
                self.assertEqual(
                    oa.parse_filters({"group_by": group_by})["group_by"], group_by
                )

    def test_filter_values_are_case_insensitive(self):
        filters = oa.parse_filters(
            {
                "time_filter": "custom",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "group_by": "MONTHLY",
                "organization_type": "Non-Profit",
            }
        )
        self.assertEqual(filters["time_filter"], "CUSTOM")
        self.assertEqual(filters["group_by"], "monthly")
        self.assertEqual(filters["organization_type"], "non_profit")

    def test_invalid_time_filter_is_rejected(self):
        with self.assertRaises(oa.FilterValidationError):
            oa.parse_filters({"time_filter": "90D"})

    def test_invalid_group_by_is_rejected(self):
        with self.assertRaises(oa.FilterValidationError):
            oa.parse_filters({"group_by": "hourly"})

    def test_invalid_organization_type_is_rejected(self):
        with self.assertRaises(oa.FilterValidationError):
            oa.parse_filters({"organization_type": "charity"})

    def test_custom_requires_both_dates(self):
        with self.assertRaises(oa.FilterValidationError):
            oa.parse_filters({"time_filter": "CUSTOM", "start_date": "2026-01-01"})
        with self.assertRaises(oa.FilterValidationError):
            oa.parse_filters({"time_filter": "CUSTOM", "end_date": "2026-06-30"})

    def test_custom_rejects_a_malformed_date(self):
        with self.assertRaises(oa.FilterValidationError):
            oa.parse_filters(
                {"time_filter": "CUSTOM", "start_date": "01-01-2026", "end_date": "2026-06-30"}
            )

    def test_custom_rejects_an_inverted_range(self):
        with self.assertRaises(oa.FilterValidationError):
            oa.parse_filters(
                {"time_filter": "CUSTOM", "start_date": "2026-06-30", "end_date": "2026-01-01"}
            )

    def test_custom_accepts_a_valid_range(self):
        filters = oa.parse_filters(
            {"time_filter": "CUSTOM", "start_date": "2026-01-01", "end_date": "2026-06-30"}
        )
        self.assertEqual(filters["start_date"], "2026-01-01")
        self.assertEqual(filters["end_date"], "2026-06-30")


class TestEventParsing(unittest.TestCase):

    def test_plain_dict_payload_is_returned_as_is(self):
        self.assertEqual(oa.parse_event_body(BASE_PAYLOAD), BASE_PAYLOAD)

    def test_api_gateway_string_body_is_decoded(self):
        event = {"body": json.dumps(BASE_PAYLOAD)}
        self.assertEqual(oa.parse_event_body(event), BASE_PAYLOAD)

    def test_api_gateway_dict_body_is_decoded(self):
        self.assertEqual(oa.parse_event_body({"body": BASE_PAYLOAD}), BASE_PAYLOAD)

    def test_empty_event_yields_empty_filters(self):
        self.assertEqual(oa.parse_event_body({}), {})
        self.assertEqual(oa.parse_event_body(None), {})

    def test_malformed_json_body_is_rejected(self):
        with self.assertRaises(oa.FilterValidationError):
            oa.parse_event_body({"body": "{not json"})


# ---------------------------------------------------------------------------
# WHERE clause construction / parameterised SQL
# ---------------------------------------------------------------------------

class TestWhereClause(unittest.TestCase):

    def build(self, payload, context=None):
        return oa.build_where_clause(
            oa.parse_filters(payload), context or DEFAULT_CONTEXT
        )

    def test_all_time_filter_adds_no_date_condition(self):
        sql, params = self.build({"time_filter": "ALL"})
        self.assertNotIn("INTERVAL", sql)
        self.assertEqual(params, [])

    def test_relative_time_filters_bind_the_interval(self):
        for time_filter, interval in (("7D", "7 days"), ("30D", "30 days"), ("1Y", "1 year")):
            with self.subTest(time_filter=time_filter):
                sql, params = self.build({"time_filter": time_filter})
                self.assertIn("CURRENT_DATE - %s::interval", sql)
                self.assertEqual(params, [interval])

    def test_custom_range_binds_both_dates(self):
        sql, params = self.build(
            {"time_filter": "CUSTOM", "start_date": "2026-01-01", "end_date": "2026-06-30"}
        )
        self.assertIn("o.created_at >= %s::date", sql)
        self.assertEqual(params, ["2026-01-01", "2026-06-30"])

    def test_region_filter_is_bound_not_interpolated(self):
        sql, params = self.build({"region": "California"})
        self.assertNotIn("California", sql)
        self.assertEqual(params, ["California", "California"])

    def test_region_filter_falls_back_to_state_id_without_the_states_table(self):
        context = dict(DEFAULT_CONTEXT, has_states=False)
        sql, params = self.build({"region": "CA"}, context)
        self.assertNotIn("s.state_name", sql)
        self.assertEqual(params, ["CA"])

    def test_organization_type_filter_is_bound_not_interpolated(self):
        sql, params = self.build({"organization_type": "non_profit"})
        self.assertNotIn("'non_profit'", sql)
        self.assertEqual(params, ["non_profit"])

    def test_all_region_and_type_add_no_conditions(self):
        sql, params = self.build({"region": "ALL", "organization_type": "ALL"})
        self.assertEqual(sql, "WHERE o.created_at IS NOT NULL")
        self.assertEqual(params, [])

    def test_filters_combine_in_a_single_clause(self):
        sql, params = self.build(
            {
                "time_filter": "CUSTOM",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "region": "Texas",
                "organization_type": "for_profit",
            }
        )
        self.assertEqual(sql.count("WHERE o.created_at IS NOT NULL"), 1)
        self.assertEqual(
            params, ["2026-01-01", "2026-06-30", "Texas", "Texas", "for_profit"]
        )

    def test_extra_conditions_are_appended(self):
        sql, _params = oa.build_where_clause(
            oa.parse_filters({}), DEFAULT_CONTEXT, extra_conditions=["o.org_rating IS NOT NULL"]
        )
        self.assertIn("AND o.org_rating IS NOT NULL", sql)


# ---------------------------------------------------------------------------
# Schema adaptation
# ---------------------------------------------------------------------------

class TestSchemaContext(unittest.TestCase):

    def test_full_schema_joins_states_and_uses_is_contributor(self):
        context = context_for(MockCursor())
        self.assertTrue(context["has_states"])
        self.assertTrue(context["has_contributor"])
        self.assertIn("LEFT JOIN", context["from_clause"])
        self.assertEqual(context["contributor_expression"], "o.is_contributor IS TRUE")

    def test_plural_states_lookup_is_preferred(self):
        context = context_for(MockCursor(state_table="states"))
        self.assertEqual(context["state_table"], "states")
        self.assertIn(f"{oa.SCHEMA_NAME}.states s", context["from_clause"])

    def test_singular_state_lookup_is_used_when_states_is_absent(self):
        context = context_for(MockCursor(state_table="state"))
        self.assertTrue(context["has_states"])
        self.assertEqual(context["state_table"], "state")
        self.assertIn(f"{oa.SCHEMA_NAME}.state s", context["from_clause"])
        self.assertNotIn(f"{oa.SCHEMA_NAME}.states s", context["from_clause"])

    def test_missing_is_contributor_column_degrades_to_zero(self):
        context = context_for(MockCursor(has_contributor=False))
        self.assertFalse(context["has_contributor"])
        self.assertEqual(context["contributor_expression"], "FALSE")

    def test_missing_states_table_drops_the_join(self):
        context = context_for(MockCursor(state_table=None))
        self.assertFalse(context["has_states"])
        self.assertIsNone(context["state_table"])
        self.assertNotIn("LEFT JOIN", context["from_clause"])
        self.assertEqual(
            context["state_name_expression"], context["state_id_expression"]
        )

    def test_introspection_failure_degrades_safely(self):
        context = context_for(
            MockCursor(failing_sections=("table_exists", "column_exists"))
        )
        self.assertFalse(context["has_states"])
        self.assertFalse(context["has_contributor"])


# ---------------------------------------------------------------------------
# Individual widget queries
# ---------------------------------------------------------------------------

class TestWidgetQueries(unittest.TestCase):

    def setUp(self):
        self.cursor = MockCursor(rows=DEFAULT_ROWS)
        self.filters = oa.parse_filters(BASE_PAYLOAD)
        self.context = DEFAULT_CONTEXT

    def test_summary_returns_the_four_kpi_cards(self):
        summary = oa.fetch_summary(self.cursor, self.filters, self.context)
        self.assertEqual(
            summary,
            {
                "total_organizations": 126,
                "total_collaborators": 42,
                "total_contributors": 84,
                "average_org_rating": 4.2,
            },
        )

    def test_summary_handles_a_null_average_rating(self):
        cursor = MockCursor(
            rows={
                "summary": [
                    {
                        "total_organizations": 3,
                        "total_collaborators": 0,
                        "total_contributors": 0,
                        "average_org_rating": None,
                    }
                ]
            }
        )
        summary = oa.fetch_summary(cursor, self.filters, self.context)
        self.assertEqual(summary["average_org_rating"], 0.0)
        self.assertEqual(summary["total_organizations"], 3)

    def test_growth_trend_returns_organizations_and_collaborators(self):
        trend = oa.fetch_growth_trend(self.cursor, self.filters, self.context)
        self.assertEqual(
            trend,
            [
                {"period": "2026-01", "total_organizations": 100, "total_collaborators": 34},
                {"period": "2026-02", "total_organizations": 108, "total_collaborators": 36},
            ],
        )

    def test_growth_trend_binds_the_grouping_period(self):
        for group_by, expected in (
            ("daily", ["day", "YYYY-MM-DD"]),
            ("weekly", ["week", 'IYYY-"W"IW']),
            ("monthly", ["month", "YYYY-MM"]),
            ("yearly", ["year", "YYYY"]),
        ):
            with self.subTest(group_by=group_by):
                cursor = MockCursor(rows=DEFAULT_ROWS)
                filters = oa.parse_filters(dict(BASE_PAYLOAD, group_by=group_by))
                oa.fetch_growth_trend(cursor, filters, self.context)
                query = cursor.query_for("growth_trend")
                self.assertIn("TO_CHAR(DATE_TRUNC(%s, o.created_at), %s)", query)
                self.assertEqual(cursor.params_for("growth_trend")[:2], expected)

    def test_location_nests_cities_and_computes_percentages(self):
        location = oa.fetch_organizations_by_location(
            self.cursor, self.filters, self.context
        )
        self.assertEqual([state["state_id"] for state in location], ["CA", "TX"])

        california = location[0]
        self.assertEqual(california["state_name"], "California")
        self.assertEqual(california["organization_count"], 32)
        self.assertEqual(california["percentage"], 57.1)  # 32 of 56
        self.assertEqual(
            california["cities"],
            [
                {"city_name": "San Jose", "organization_count": 20},
                {"city_name": "Fresno", "organization_count": 12},
            ],
        )

        texas = location[1]
        self.assertEqual(texas["organization_count"], 24)
        self.assertEqual(texas["percentage"], 42.9)

    def test_size_always_returns_the_three_supported_buckets(self):
        cursor = MockCursor(rows={"organizations_by_size": [{"org_size": "small", "organization_count": 7}]})
        sizes = oa.fetch_organizations_by_size(cursor, self.filters, self.context)
        self.assertEqual(
            sizes,
            [
                {"org_size": "small", "organization_count": 7},
                {"org_size": "medium", "organization_count": 0},
                {"org_size": "large", "organization_count": 0},
            ],
        )

    def test_size_reports_unexpected_values_after_the_known_ones(self):
        cursor = MockCursor(
            rows={
                "organizations_by_size": [
                    {"org_size": "large", "organization_count": 4},
                    {"org_size": "unknown", "organization_count": 2},
                ]
            }
        )
        sizes = oa.fetch_organizations_by_size(cursor, self.filters, self.context)
        self.assertEqual([entry["org_size"] for entry in sizes], ["small", "medium", "large", "unknown"])
        self.assertEqual(sizes[-1]["organization_count"], 2)

    def test_collaborator_vs_contributor_percentages(self):
        split = oa.fetch_collaborator_vs_contributor(
            self.cursor, self.filters, self.context
        )
        self.assertEqual(
            split,
            [
                {"type": "collaborator", "organization_count": 42, "percentage": 33.3},
                {"type": "contributor", "organization_count": 84, "percentage": 66.7},
            ],
        )

    def test_collaborator_vs_contributor_handles_a_zero_total(self):
        cursor = MockCursor(
            rows={"collaborator_vs_contributor": [{"collaborator_count": 0, "contributor_count": 0}]}
        )
        split = oa.fetch_collaborator_vs_contributor(cursor, self.filters, self.context)
        self.assertEqual([entry["percentage"] for entry in split], [0.0, 0.0])

    def test_rating_distribution_is_zero_filled_from_one_to_five(self):
        ratings = oa.fetch_rating_distribution(self.cursor, self.filters, self.context)
        self.assertEqual([entry["rating"] for entry in ratings], [1, 2, 3, 4, 5])
        self.assertEqual(
            [entry["organization_count"] for entry in ratings], [1, 0, 12, 46, 64]
        )

    def test_rating_distribution_excludes_null_ratings_in_sql(self):
        oa.fetch_rating_distribution(self.cursor, self.filters, self.context)
        query = self.cursor.query_for("rating_distribution")
        self.assertIn("o.org_rating IS NOT NULL", query)
        self.assertIn("o.org_rating BETWEEN 1 AND 5", query)

    def test_type_distribution_totals_each_period(self):
        distribution = oa.fetch_organization_type_distribution(
            self.cursor, self.filters, self.context
        )
        self.assertEqual(
            distribution,
            [
                {"period": "2026-01", "for_profit": 41, "non_profit": 68, "total": 109},
                {"period": "2026-02", "for_profit": 43, "non_profit": 68, "total": 111},
            ],
        )

    def test_type_distribution_normalises_the_stored_org_type(self):
        oa.fetch_organization_type_distribution(self.cursor, self.filters, self.context)
        query = self.cursor.query_for("organization_type_distribution")
        self.assertIn("REPLACE(LOWER(TRIM(o.org_type)), '-', '_')", query)


class TestEmptyResultSets(unittest.TestCase):
    """Every widget must degrade to a well formed, empty shaped payload."""

    def setUp(self):
        self.cursor = MockCursor(rows={})
        self.filters = oa.parse_filters(BASE_PAYLOAD)
        self.context = DEFAULT_CONTEXT

    def test_summary_is_zeroed(self):
        self.assertEqual(
            oa.fetch_summary(self.cursor, self.filters, self.context),
            {
                "total_organizations": 0,
                "total_collaborators": 0,
                "total_contributors": 0,
                "average_org_rating": 0.0,
            },
        )

    def test_trend_and_location_are_empty_lists(self):
        self.assertEqual(oa.fetch_growth_trend(self.cursor, self.filters, self.context), [])
        self.assertEqual(
            oa.fetch_organizations_by_location(self.cursor, self.filters, self.context), []
        )
        self.assertEqual(
            oa.fetch_organization_type_distribution(self.cursor, self.filters, self.context), []
        )

    def test_fixed_scale_widgets_keep_their_buckets(self):
        sizes = oa.fetch_organizations_by_size(self.cursor, self.filters, self.context)
        self.assertEqual([entry["organization_count"] for entry in sizes], [0, 0, 0])

        ratings = oa.fetch_rating_distribution(self.cursor, self.filters, self.context)
        self.assertEqual(len(ratings), 5)
        self.assertTrue(all(entry["organization_count"] == 0 for entry in ratings))

        split = oa.fetch_collaborator_vs_contributor(self.cursor, self.filters, self.context)
        self.assertEqual([entry["organization_count"] for entry in split], [0, 0])


# ---------------------------------------------------------------------------
# Handler behaviour
# ---------------------------------------------------------------------------

class TestLambdaHandler(unittest.TestCase):

    def test_happy_path_returns_every_dashboard_section(self):
        cursor = MockCursor(rows=DEFAULT_ROWS)
        response, body, connection = run_handler(BASE_PAYLOAD, cursor)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        for section in (
            "summary",
            "growth_trend",
            "organizations_by_location",
            "organizations_by_size",
            "collaborator_vs_contributor",
            "rating_distribution",
            "organization_type_distribution",
        ):
            self.assertIn(section, body)

        self.assertEqual(body["summary"]["total_organizations"], 126)
        self.assertEqual(body["summary"]["average_org_rating"], 4.2)
        self.assertEqual(len(body["growth_trend"]), 2)
        self.assertEqual(len(body["rating_distribution"]), 5)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_applied_filters_are_echoed_back(self):
        cursor = MockCursor(rows=DEFAULT_ROWS)
        payload = dict(BASE_PAYLOAD, region="California", organization_type="non_profit")
        _response, body, _connection = run_handler(payload, cursor)

        self.assertEqual(body["filters_applied"]["region"], "California")
        self.assertEqual(body["filters_applied"]["organization_type"], "non_profit")

    def test_custom_range_reaches_every_widget_query(self):
        cursor = MockCursor(rows=DEFAULT_ROWS)
        payload = {
            "time_filter": "CUSTOM",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "group_by": "monthly",
            "region": "ALL",
            "organization_type": "ALL",
        }
        response, _body, _connection = run_handler(payload, cursor)

        self.assertEqual(response["statusCode"], 200)
        for section, _fetch, _empty in oa.DASHBOARD_SECTIONS:
            with self.subTest(section=section):
                self.assertIn("2026-01-01", cursor.params_for(section))
                self.assertIn("2026-06-30", cursor.params_for(section))

    def test_api_gateway_event_shape_is_supported(self):
        cursor = MockCursor(rows=DEFAULT_ROWS)
        event = {"body": json.dumps(BASE_PAYLOAD)}
        response, body, _connection = run_handler(event, cursor)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["summary"]["total_organizations"], 126)

    def test_invalid_filter_returns_400_with_the_default_structure(self):
        cursor = MockCursor(rows=DEFAULT_ROWS)
        response, body, _connection = run_handler(dict(BASE_PAYLOAD, time_filter="90D"), cursor)

        self.assertEqual(response["statusCode"], 400)
        self.assertIn("Invalid time_filter", body["error"])
        self.assertEqual(body["summary"]["total_organizations"], 0)
        self.assertEqual(body["growth_trend"], [])
        # The database must never be touched for a rejected request.
        self.assertEqual(cursor.executed, [])

    def test_custom_without_dates_returns_400(self):
        cursor = MockCursor(rows=DEFAULT_ROWS)
        response, body, _connection = run_handler(
            dict(BASE_PAYLOAD, time_filter="CUSTOM"), cursor
        )
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("start_date", body["error"])

    def test_a_single_failing_widget_does_not_break_the_dashboard(self):
        cursor = MockCursor(rows=DEFAULT_ROWS, failing_sections=("rating_distribution",))
        response, body, _connection = run_handler(BASE_PAYLOAD, cursor)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["rating_distribution"], [])
        self.assertEqual(body["summary"]["total_organizations"], 126)
        self.assertEqual(len(body["growth_trend"]), 2)

    def test_a_failing_summary_query_keeps_the_default_kpi_card_values(self):
        cursor = MockCursor(rows=DEFAULT_ROWS, failing_sections=("summary",))
        response, body, _connection = run_handler(BASE_PAYLOAD, cursor)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["summary"], oa.get_default_response()["summary"])
        self.assertEqual(len(body["organizations_by_location"]), 2)

    def test_every_widget_failing_still_returns_200_and_the_full_shape(self):
        all_sections = [section for section, _fetch, _empty in oa.DASHBOARD_SECTIONS]
        cursor = MockCursor(rows=DEFAULT_ROWS, failing_sections=all_sections)
        response, body, _connection = run_handler(BASE_PAYLOAD, cursor)

        self.assertEqual(response["statusCode"], 200)
        default = oa.get_default_response()
        for section in all_sections:
            with self.subTest(section=section):
                self.assertEqual(body[section], default[section])

    def test_connection_failure_returns_500_with_the_default_structure(self):
        with mock.patch.object(
            oa, "get_db_connection", side_effect=Exception("could not connect to server")
        ):
            response = oa.lambda_handler(BASE_PAYLOAD, None)

        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 500)
        default = oa.get_default_response()
        self.assertEqual(body["summary"], default["summary"])
        self.assertEqual(body["growth_trend"], [])
        self.assertEqual(body["organization_type_distribution"], [])

    def test_missing_is_contributor_column_yields_zero_contributors(self):
        rows = dict(
            DEFAULT_ROWS,
            summary=[
                {
                    "total_organizations": 126,
                    "total_collaborators": 42,
                    "total_contributors": 0,
                    "average_org_rating": 4.2,
                }
            ],
            collaborator_vs_contributor=[{"collaborator_count": 42, "contributor_count": 0}],
        )
        cursor = MockCursor(rows=rows, has_contributor=False)
        response, body, _connection = run_handler(BASE_PAYLOAD, cursor)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["summary"]["total_contributors"], 0)
        self.assertIn("COUNT(*) FILTER (WHERE FALSE)", cursor.query_for("summary"))

    def test_missing_states_table_still_returns_locations(self):
        rows = dict(
            DEFAULT_ROWS,
            organizations_by_location=[
                {"state_id": "CA", "state_name": "CA", "city_name": "San Jose", "organization_count": 5}
            ],
        )
        cursor = MockCursor(rows=rows, state_table=None)
        response, body, _connection = run_handler(BASE_PAYLOAD, cursor)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["organizations_by_location"][0]["state_name"], "CA")
        self.assertNotIn("LEFT JOIN", cursor.query_for("organizations_by_location"))

    def test_response_body_is_json_serialisable(self):
        cursor = MockCursor(rows=DEFAULT_ROWS)
        response, _body, _connection = run_handler(BASE_PAYLOAD, cursor)
        self.assertIsInstance(response["body"], str)
        json.loads(response["body"])


class TestParameterisedSql(unittest.TestCase):
    """No user supplied value may ever be inlined into a statement."""

    def test_no_filter_value_appears_literally_in_any_query(self):
        cursor = MockCursor(rows=DEFAULT_ROWS)
        payload = {
            "time_filter": "CUSTOM",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "group_by": "monthly",
            "region": "California",
            "organization_type": "non_profit",
        }
        run_handler(payload, cursor)

        for section, query, params in cursor.executed:
            with self.subTest(section=section):
                self.assertNotIn("2026-01-01", query)
                self.assertNotIn("2026-06-30", query)
                self.assertNotIn("California", query)

                if section in ("table_exists", "column_exists"):
                    continue

                # The type distribution query legitimately contains 'for_profit' /
                # 'non_profit' as fixed bucket labels, so the filter value itself is
                # checked by confirming it was bound rather than inlined.
                self.assertIn(f"{oa.ORG_TYPE_EXPRESSION} = %s", query)
                self.assertIn("non_profit", params)

    def test_a_sql_injection_attempt_is_bound_as_a_value(self):
        cursor = MockCursor(rows=DEFAULT_ROWS)
        payload = dict(BASE_PAYLOAD, region="CA'; DROP TABLE organizations;--")
        response, _body, _connection = run_handler(payload, cursor)

        self.assertEqual(response["statusCode"], 200)
        for section, query, params in cursor.executed:
            with self.subTest(section=section):
                self.assertNotIn("DROP TABLE", query)
                if section not in ("table_exists", "column_exists"):
                    self.assertIn("CA'; DROP TABLE organizations;--", params)


class TestDatabaseConfig(unittest.TestCase):

    def test_config_comes_from_environment_variables(self):
        env = {
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "5433",
            "DB_NAME": "saayam_local",
            "DB_USER": "analytics",
            "DB_PASSWORD": "secret",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            config = oa.get_db_config()

        self.assertEqual(config["host"], "127.0.0.1")
        self.assertEqual(config["port"], 5433)
        self.assertEqual(config["dbname"], "saayam_local")
        self.assertEqual(config["user"], "analytics")
        self.assertEqual(config["password"], "secret")

    def test_module_does_not_reference_aws_parameter_store(self):
        source_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "organization_analytics.py"
        )
        with open(source_path, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertNotIn("boto3", source)
        self.assertNotIn("get_parameter", source)
        self.assertNotIn("/dev/saayam/db/", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
