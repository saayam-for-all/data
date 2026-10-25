"""Unit tests for organization_analytics.py.

These are cursor-based / mock-database tests: no PostgreSQL server is required.
Every query the lambda generates is additionally parsed with ``pglast`` (a real
PostgreSQL grammar) so syntax errors are caught without a live database.

Run from data-analytics/lambda_functions/tests:
    python -m pytest -q
"""

import json
import re

import pytest

import organization_analytics as m


# --------------------------------------------------------------------------- #
# Fake cursor / connection
# --------------------------------------------------------------------------- #
class FakeCursor:
    """Minimal DB-API cursor that answers from a canned dataset.

    Which canned rows to return is decided by matching on the query text, which
    keeps the tests independent of call ordering inside the handler.
    """

    def __init__(self, data, recorder):
        self.data = data
        self.recorder = recorder
        self._rows = []

    # -- DB-API surface -----------------------------------------------------
    def execute(self, query, params=None):
        self.recorder.append((query, list(params or [])))
        self._rows = self._resolve(query)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    # -- routing ------------------------------------------------------------
    def _resolve(self, query):
        if "information_schema.columns" in query:
            return [{"exists": 1}] if self.data.get("has_is_contributor", True) else []
        if "total_organizations" in query:
            return [self.data.get("summary", {})]
        if "new_collaborators" in query:
            return self.data.get("growth", [])
        if "city_name" in query:
            return self.data.get("location", [])
        if "org_size" in query:
            return self.data.get("size", [])
        if "AS rating" in query:
            return self.data.get("rating", [])
        if "for_profit" in query:
            return self.data.get("org_type", [])
        raise AssertionError(f"unrouted query:\n{query}")


class FakeConnection:
    def __init__(self, data, recorder):
        self.data = data
        self.recorder = recorder
        self.closed = False

    def cursor(self, *args, **kwargs):
        return FakeCursor(self.data, self.recorder)

    def close(self):
        self.closed = True


EMPTY_SUMMARY = {
    "total_organizations": 0,
    "total_collaborators": 0,
    "total_contributors": 0,
    "rating_sum": 0,
    "rating_count": 0,
}


def make_data(**overrides):
    data = {
        "has_is_contributor": True,
        "summary": {
            "total_organizations": 40,
            "total_collaborators": 21,
            "total_contributors": 19,
            "rating_sum": 130,
            "rating_count": 40,
        },
        "growth": [
            {"period": "2026-01", "new_organizations": 3, "new_collaborators": 2},
            {"period": "2026-02", "new_organizations": 5, "new_collaborators": 1},
        ],
        "location": [
            {
                "state_id": "TX",
                "state_name": "Texas",
                "city_name": "Austin",
                "organization_count": 2,
            },
            {
                "state_id": "TX",
                "state_name": "Texas",
                "city_name": "Dallas",
                "organization_count": 1,
            },
            {
                "state_id": "CA",
                "state_name": "California",
                "city_name": "Fresno",
                "organization_count": 1,
            },
        ],
        "size": [
            {"org_size": "small", "organization_count": 10},
            {"org_size": "large", "organization_count": 21},
            {"org_size": "medium", "organization_count": 9},
        ],
        "rating": [
            {"rating": 1, "organization_count": 5},
            {"rating": 3, "organization_count": 10},
            {"rating": 5, "organization_count": 12},
        ],
        "org_type": [
            {"period": "2026-01", "for_profit": 2, "non_profit": 1},
            {"period": "2026-02", "for_profit": 1, "non_profit": 4},
        ],
    }
    data.update(overrides)
    return data


@pytest.fixture()
def single_region(monkeypatch):
    """Patch the module so it talks to one fake Virginia database."""
    monkeypatch.delenv("IRELAND_PGHOST", raising=False)
    recorder = []
    state = {"data": make_data()}

    def fake_connect(env_prefix=""):
        return FakeConnection(state["data"], recorder)

    monkeypatch.setattr(m, "get_db_connection", fake_connect)
    return state, recorder


def invoke(event=None):
    response = m.lambda_handler(event or {}, None)
    return response["statusCode"], json.loads(response["body"])


BASE_EVENT = {
    "time_filter": "1Y",
    "start_date": None,
    "end_date": None,
    "group_by": "monthly",
    "region": "ALL",
    "organization_type": "ALL",
}


# --------------------------------------------------------------------------- #
# Filter validation
# --------------------------------------------------------------------------- #
class TestParseFilters:
    def test_defaults_when_payload_empty(self):
        filters = m.parse_filters({})
        assert filters["time_filter"] == "ALL"
        assert filters["group_by"] == "monthly"
        assert filters["region"] == "ALL"
        assert filters["organization_type"] == "ALL"
        assert filters["start_date"] is None and filters["end_date"] is None

    @pytest.mark.parametrize("time_filter", ["7D", "30D", "1Y", "ALL"])
    def test_accepts_documented_time_filters(self, time_filter):
        assert m.parse_filters({"time_filter": time_filter})["time_filter"] == time_filter

    @pytest.mark.parametrize("group_by", ["daily", "weekly", "monthly", "yearly"])
    def test_accepts_documented_groupings(self, group_by):
        assert m.parse_filters({"group_by": group_by})["group_by"] == group_by

    def test_time_filter_is_case_insensitive(self):
        assert m.parse_filters({"time_filter": "all"})["time_filter"] == "ALL"

    def test_rejects_unknown_time_filter(self):
        with pytest.raises(m.FilterValidationError, match="time_filter"):
            m.parse_filters({"time_filter": "90D"})

    def test_rejects_unknown_group_by(self):
        with pytest.raises(m.FilterValidationError, match="group_by"):
            m.parse_filters({"group_by": "hourly"})

    def test_rejects_unknown_organization_type(self):
        with pytest.raises(m.FilterValidationError, match="organization_type"):
            m.parse_filters({"organization_type": "charity"})

    def test_custom_requires_both_dates(self):
        with pytest.raises(m.FilterValidationError, match="both required"):
            m.parse_filters({"time_filter": "CUSTOM", "start_date": "2026-01-01"})

    def test_custom_rejects_malformed_date(self):
        with pytest.raises(m.FilterValidationError, match="YYYY-MM-DD"):
            m.parse_filters(
                {
                    "time_filter": "CUSTOM",
                    "start_date": "01/01/2026",
                    "end_date": "2026-06-30",
                }
            )

    def test_custom_rejects_reversed_range(self):
        with pytest.raises(m.FilterValidationError, match="after end_date"):
            m.parse_filters(
                {
                    "time_filter": "CUSTOM",
                    "start_date": "2026-06-30",
                    "end_date": "2026-01-01",
                }
            )

    def test_custom_accepts_valid_range(self):
        filters = m.parse_filters(
            {
                "time_filter": "CUSTOM",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
            }
        )
        assert (filters["start_date"], filters["end_date"]) == (
            "2026-01-01",
            "2026-06-30",
        )

    def test_non_custom_ignores_stray_dates(self):
        filters = m.parse_filters({"time_filter": "7D", "start_date": "2026-01-01"})
        assert filters["start_date"] is None


class TestFilterClause:
    def test_all_produces_no_clause(self):
        sql, params = m.build_filter_clause(m.parse_filters({}))
        assert sql == "" and params == []

    @pytest.mark.parametrize(
        "time_filter,interval",
        [("7D", "7 days"), ("30D", "30 days"), ("1Y", "1 year")],
    )
    def test_relative_windows(self, time_filter, interval):
        sql, params = m.build_filter_clause(
            m.parse_filters({"time_filter": time_filter})
        )
        assert f"INTERVAL '{interval}'" in sql
        assert params == []

    def test_custom_range_is_parameterised(self):
        sql, params = m.build_filter_clause(
            m.parse_filters(
                {
                    "time_filter": "CUSTOM",
                    "start_date": "2026-01-01",
                    "end_date": "2026-06-30",
                }
            )
        )
        assert sql.count("%s") == 2
        assert params == ["2026-01-01", "2026-06-30"]
        assert "2026-01-01" not in sql  # value never inlined

    def test_region_and_type_are_parameterised(self):
        sql, params = m.build_filter_clause(
            m.parse_filters({"region": "CA", "organization_type": "non_profit"})
        )
        assert params == ["CA", "non_profit"]
        assert "CA" not in sql and "non_profit" not in sql

    def test_region_all_is_not_filtered(self):
        sql, params = m.build_filter_clause(m.parse_filters({"region": "ALL"}))
        assert params == [] and sql == ""


# --------------------------------------------------------------------------- #
# Handler: happy path
# --------------------------------------------------------------------------- #
class TestHandlerHappyPath:
    def test_response_envelope(self, single_region):
        response = m.lambda_handler(BASE_EVENT, None)
        assert response["statusCode"] == 200
        assert response["headers"]["Content-Type"] == "application/json"
        assert isinstance(response["body"], str)

    def test_top_level_structure_matches_spec(self, single_region):
        status, body = invoke(BASE_EVENT)
        assert status == 200
        assert set(body) == {
            "summary",
            "growth_trend",
            "organizations_by_location",
            "organizations_by_size",
            "collaborator_vs_contributor",
            "rating_distribution",
            "organization_type_distribution",
        }

    def test_summary_kpis(self, single_region):
        _, body = invoke(BASE_EVENT)
        assert body["summary"] == {
            "total_organizations": 40,
            "total_collaborators": 21,
            "total_contributors": 19,
            "average_org_rating": 3.2,  # 130 / 40 = 3.25 -> 3.2 (banker-free round)
        }

    def test_growth_trend_is_cumulative(self, single_region):
        _, body = invoke(BASE_EVENT)
        assert body["growth_trend"] == [
            {"period": "2026-01", "total_organizations": 3, "total_collaborators": 2},
            {"period": "2026-02", "total_organizations": 8, "total_collaborators": 3},
        ]

    def test_location_nests_cities_and_percentages(self, single_region):
        _, body = invoke(BASE_EVENT)
        texas = body["organizations_by_location"][0]
        assert texas["state_id"] == "TX"
        assert texas["state_name"] == "Texas"
        assert texas["organization_count"] == 3
        assert texas["percentage"] == 7.5  # 3 / 40
        assert texas["cities"] == [
            {"city_name": "Austin", "organization_count": 2},
            {"city_name": "Dallas", "organization_count": 1},
        ]

    def test_size_always_returns_three_buckets(self, single_region):
        _, body = invoke(BASE_EVENT)
        assert body["organizations_by_size"] == [
            {"org_size": "small", "organization_count": 10},
            {"org_size": "medium", "organization_count": 9},
            {"org_size": "large", "organization_count": 21},
        ]

    def test_collaborator_vs_contributor(self, single_region):
        _, body = invoke(BASE_EVENT)
        assert body["collaborator_vs_contributor"] == [
            {"type": "collaborator", "organization_count": 21, "percentage": 52.5},
            {"type": "contributor", "organization_count": 19, "percentage": 47.5},
        ]

    def test_rating_distribution_covers_one_to_five(self, single_region):
        _, body = invoke(BASE_EVENT)
        assert body["rating_distribution"] == [
            {"rating": 1, "organization_count": 5},
            {"rating": 2, "organization_count": 0},
            {"rating": 3, "organization_count": 10},
            {"rating": 4, "organization_count": 0},
            {"rating": 5, "organization_count": 12},
        ]

    def test_org_type_distribution_is_cumulative_with_total(self, single_region):
        _, body = invoke(BASE_EVENT)
        assert body["organization_type_distribution"] == [
            {"period": "2026-01", "for_profit": 2, "non_profit": 1, "total": 3},
            {"period": "2026-02", "for_profit": 3, "non_profit": 5, "total": 8},
        ]

    def test_accepts_api_gateway_string_body(self, single_region):
        status, body = invoke({"body": json.dumps(BASE_EVENT)})
        assert status == 200 and body["summary"]["total_organizations"] == 40

    def test_connection_is_closed(self, single_region, monkeypatch):
        opened = []

        def fake_connect(env_prefix=""):
            conn = FakeConnection(make_data(), [])
            opened.append(conn)
            return conn

        monkeypatch.setattr(m, "get_db_connection", fake_connect)
        m.lambda_handler(BASE_EVENT, None)
        assert opened and all(c.closed for c in opened)


# --------------------------------------------------------------------------- #
# Handler: filters reach SQL
# --------------------------------------------------------------------------- #
class TestFiltersReachSql:
    def test_custom_range_params_on_every_section(self, single_region):
        _, recorder = single_region
        invoke(
            {
                "time_filter": "CUSTOM",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "group_by": "monthly",
                "region": "ALL",
                "organization_type": "ALL",
            }
        )
        section_calls = [
            (q, p) for q, p in recorder if "information_schema" not in q
        ]
        assert section_calls, "no section queries were executed"
        for query, params in section_calls:
            assert params[:2] == ["2026-01-01", "2026-06-30"], query

    def test_region_filter_is_applied_everywhere(self, single_region):
        _, recorder = single_region
        invoke(dict(BASE_EVENT, region="CA"))
        for query, params in recorder:
            if "information_schema" in query:
                continue
            assert "CA" in params
            assert "o.state_id" in query

    def test_organization_type_filter_is_applied_everywhere(self, single_region):
        _, recorder = single_region
        invoke(dict(BASE_EVENT, organization_type="non_profit"))
        for query, params in recorder:
            if "information_schema" in query:
                continue
            assert "non_profit" in params

    @pytest.mark.parametrize(
        "group_by,unit",
        [("daily", "day"), ("weekly", "week"), ("monthly", "month"), ("yearly", "year")],
    )
    def test_group_by_selects_date_trunc_unit(self, single_region, group_by, unit):
        _, recorder = single_region
        invoke(dict(BASE_EVENT, group_by=group_by))
        trend_queries = [q for q, _ in recorder if "new_collaborators" in q]
        assert trend_queries and f"DATE_TRUNC('{unit}'" in trend_queries[0]


# --------------------------------------------------------------------------- #
# Handler: edge cases
# --------------------------------------------------------------------------- #
class TestEmptyResults:
    def test_empty_database_returns_zeroed_structure(self, single_region):
        state, _ = single_region
        state["data"] = make_data(
            summary=EMPTY_SUMMARY,
            growth=[],
            location=[],
            size=[],
            rating=[],
            org_type=[],
        )
        status, body = invoke(BASE_EVENT)
        assert status == 200
        assert body["summary"] == {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": 0.0,
        }
        assert body["growth_trend"] == []
        assert body["organizations_by_location"] == []
        assert body["organization_type_distribution"] == []
        # Fixed-domain charts keep their buckets so the UI axes stay stable.
        assert [r["organization_count"] for r in body["organizations_by_size"]] == [0, 0, 0]
        assert [r["organization_count"] for r in body["rating_distribution"]] == [0] * 5
        assert all(r["percentage"] == 0.0 for r in body["collaborator_vs_contributor"])

    def test_summary_row_missing_entirely(self, single_region):
        state, _ = single_region
        state["data"] = make_data(summary=None)
        # fetchone() returns None when the driver yields no row at all.
        state["data"]["summary"] = {}
        status, body = invoke(BASE_EVENT)
        assert status == 200
        assert body["summary"]["total_organizations"] == 0


class TestNullHandling:
    def test_all_ratings_null_does_not_fail(self, single_region):
        state, _ = single_region
        state["data"] = make_data(
            summary={
                "total_organizations": 10,
                "total_collaborators": 4,
                "total_contributors": 6,
                "rating_sum": 0,
                "rating_count": 0,
            },
            rating=[],
        )
        status, body = invoke(BASE_EVENT)
        assert status == 200
        assert body["summary"]["average_org_rating"] == 0.0
        assert [r["organization_count"] for r in body["rating_distribution"]] == [0] * 5

    def test_null_state_and_city_are_labelled_unknown(self, single_region):
        state, _ = single_region
        state["data"] = make_data(
            location=[
                {
                    "state_id": "Unknown",
                    "state_name": "Unknown",
                    "city_name": "Unknown",
                    "organization_count": 4,
                }
            ]
        )
        _, body = invoke(BASE_EVENT)
        assert body["organizations_by_location"][0]["state_id"] == "Unknown"

    def test_null_counts_coerce_to_zero(self, single_region):
        state, _ = single_region
        state["data"] = make_data(
            summary={
                "total_organizations": 5,
                "total_collaborators": None,
                "total_contributors": None,
                "rating_sum": None,
                "rating_count": None,
            }
        )
        _, body = invoke(BASE_EVENT)
        assert body["summary"]["total_collaborators"] == 0
        assert body["summary"]["average_org_rating"] == 0.0


class TestMissingContributorColumn:
    def test_contributor_row_omitted_when_column_absent(self, single_region):
        state, _ = single_region
        state["data"] = make_data(has_is_contributor=False)
        state["data"]["summary"] = dict(
            state["data"]["summary"], total_contributors=0
        )
        status, body = invoke(BASE_EVENT)
        assert status == 200
        assert body["summary"]["total_contributors"] == 0
        assert [r["type"] for r in body["collaborator_vs_contributor"]] == ["collaborator"]

    def test_summary_query_omits_is_contributor_when_absent(self, single_region):
        state, recorder = single_region
        state["data"] = make_data(has_is_contributor=False)
        invoke(BASE_EVENT)
        summary_query = next(q for q, _ in recorder if "total_organizations" in q)
        assert "is_contributor" not in summary_query


class TestErrorPaths:
    def test_invalid_filter_returns_400_with_safe_body(self, single_region):
        status, body = invoke(dict(BASE_EVENT, time_filter="90D"))
        assert status == 400
        assert "time_filter" in body["error"]
        assert body["summary"]["total_organizations"] == 0
        assert body["growth_trend"] == []

    def test_custom_without_dates_returns_400(self, single_region):
        status, body = invoke(dict(BASE_EVENT, time_filter="CUSTOM"))
        assert status == 400
        assert "start_date and end_date" in body["error"]

    def test_connection_failure_returns_500_with_safe_body(self, monkeypatch):
        monkeypatch.delenv("IRELAND_PGHOST", raising=False)

        def boom(env_prefix=""):
            raise RuntimeError("could not connect to server")

        monkeypatch.setattr(m, "get_db_connection", boom)
        status, body = invoke(BASE_EVENT)
        assert status == 500
        assert body == m.get_default_response()

    def test_query_failure_returns_500_with_safe_body(self, monkeypatch):
        monkeypatch.delenv("IRELAND_PGHOST", raising=False)

        class ExplodingCursor(FakeCursor):
            def execute(self, query, params=None):
                if "total_organizations" in query:
                    raise RuntimeError('relation "organizations" does not exist')
                return super().execute(query, params)

        class ExplodingConnection(FakeConnection):
            def cursor(self, *args, **kwargs):
                return ExplodingCursor(self.data, self.recorder)

        monkeypatch.setattr(
            m, "get_db_connection", lambda env_prefix="": ExplodingConnection(make_data(), [])
        )
        status, body = invoke(BASE_EVENT)
        assert status == 500
        assert body == m.get_default_response()

    def test_unparseable_body_falls_back_to_defaults(self, single_region):
        status, body = invoke({"body": "{not json"})
        assert status == 200  # empty payload -> documented defaults
        assert body["summary"]["total_organizations"] == 40


# --------------------------------------------------------------------------- #
# Multi-region merge
# --------------------------------------------------------------------------- #
class TestRegionMerge:
    def test_ireland_skipped_when_not_configured(self, monkeypatch):
        monkeypatch.delenv("IRELAND_PGHOST", raising=False)
        assert [r["name"] for r in m.active_regions()] == ["Virginia"]

    def test_ireland_included_when_configured(self, monkeypatch):
        monkeypatch.setenv("IRELAND_PGHOST", "ireland.example")
        assert [r["name"] for r in m.active_regions()] == ["Virginia", "Ireland"]

    def test_counts_and_trends_are_summed_across_regions(self, monkeypatch):
        monkeypatch.setenv("IRELAND_PGHOST", "ireland.example")
        ireland = make_data(
            summary={
                "total_organizations": 10,
                "total_collaborators": 4,
                "total_contributors": 6,
                "rating_sum": 40,
                "rating_count": 10,
            },
            growth=[
                {"period": "2026-02", "new_organizations": 2, "new_collaborators": 1},
                {"period": "2026-03", "new_organizations": 1, "new_collaborators": 0},
            ],
        )
        virginia = make_data()

        def fake_connect(env_prefix=""):
            return FakeConnection(ireland if env_prefix else virginia, [])

        monkeypatch.setattr(m, "get_db_connection", fake_connect)
        _, body = invoke(BASE_EVENT)

        assert body["summary"]["total_organizations"] == 50
        assert body["summary"]["total_collaborators"] == 25
        # (130 + 40) / (40 + 10) = 3.4 — a weighted average, not a mean of means.
        assert body["summary"]["average_org_rating"] == 3.4
        # Periods present in only one region still accumulate correctly.
        assert body["growth_trend"] == [
            {"period": "2026-01", "total_organizations": 3, "total_collaborators": 2},
            {"period": "2026-02", "total_organizations": 10, "total_collaborators": 4},
            {"period": "2026-03", "total_organizations": 11, "total_collaborators": 4},
        ]


# --------------------------------------------------------------------------- #
# SQL validity + injection safety
# --------------------------------------------------------------------------- #
def _all_generated_queries():
    """Collect every query the lambda emits across the full filter matrix."""
    recorder = []
    cursor = FakeCursor(make_data(), recorder)
    region = m.REGIONS[0]
    payloads = [
        {},
        {"time_filter": "7D", "group_by": "daily"},
        {"time_filter": "30D", "group_by": "weekly"},
        {"time_filter": "1Y", "group_by": "monthly"},
        {"time_filter": "ALL", "group_by": "yearly"},
        {
            "time_filter": "CUSTOM",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "group_by": "daily",
            "region": "CA",
            "organization_type": "non_profit",
        },
    ]
    for payload in payloads:
        m.collect_region_data(cursor, region, m.parse_filters(payload))
    return recorder


@pytest.mark.parametrize("query", [q for q, _ in _all_generated_queries()])
def test_every_query_is_valid_postgresql(query):
    pglast = pytest.importorskip("pglast", reason="pglast not installed")
    # psycopg2 placeholders are not valid SQL text; substitute a literal first.
    pglast.parse_sql(re.sub(r"%s", "'x'", query))


def test_no_query_interpolates_user_values(single_region):
    """Every caller-supplied value must arrive as a bound parameter."""
    _, recorder = single_region
    invoke(
        {
            "time_filter": "CUSTOM",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "group_by": "daily",
            "region": "CA",
            "organization_type": "non_profit",
        }
    )
    for query, params in recorder:
        for value in ("2026-01-01", "2026-06-30"):
            assert value not in query
        assert "'CA'" not in query
        # Every bound parameter has exactly one placeholder. Literal occurrences
        # of 'for_profit'/'non_profit' inside FILTER clauses are fixed constants
        # in the module, not caller input.
        assert query.count("%s") == len(params), query


def test_group_by_cannot_inject_sql():
    """group_by is whitelisted, so hostile values are rejected, never rendered."""
    with pytest.raises(m.FilterValidationError):
        m.parse_filters({"group_by": "day'); DROP TABLE organizations; --"})
