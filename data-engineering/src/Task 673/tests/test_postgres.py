"""Real SQL + handler checks; only AWS SSM and GenAI are replaced."""

import json

import psycopg2
from psycopg2 import sql
import pytest

from harness import BASELINE_REF, ai_response, event, load_app
from local_postgres import fixture_schema, postgres_cluster


@pytest.fixture(scope="module")
def database():
    """Run actual PostgreSQL; missing binaries are a failure, never a silent skip."""
    with postgres_cluster() as dsn:
        connection = psycopg2.connect(dsn)
        try:
            yield connection
        finally:
            connection.close()


def assert_response_contract(response):
    """Validate wire JSON, field ordering, and actual boolean/null types."""
    assert response["statusCode"] == 200, response
    rows = json.loads(response["body"])
    json.dumps(rows, allow_nan=False)
    for row in rows:
        keys = list(row)
        assert keys[keys.index("collaborator") + 1] == "contributor"
        for field in ("collaborator", "contributor"):
            assert row[field] is None or type(row[field]) is bool
        assert not any(key.startswith("_geo_") for key in row)
    return rows


@pytest.mark.parametrize("column_present", [True, False])
@pytest.mark.parametrize("sort_by", [None, "distance"])
@pytest.mark.parametrize("ai_mode", ["available", "empty", "unavailable"])
def test_handler_matches_test_branch_except_contributor(database, column_present, sort_by, ai_mode):
    """Compare full handler output, including distances, against pinned test."""
    payload = {"available": ai_response(), "empty": ai_response([]),
               "unavailable": ai_response(status=502)}[ai_mode]
    with fixture_schema(database, column_present) as schema:
        with load_app(database, schema, payload, BASELINE_REF) as baseline:
            before = baseline.handler.lambda_handler(event(sort_by), None)
        with load_app(database, schema, payload) as changed:
            after = changed.handler.lambda_handler(event(sort_by), None)
            rows = assert_response_contract(after)
            # The cached connection remains usable across warm invocations.
            warm = changed.handler.lambda_handler(event(sort_by), None)
            assert json.loads(warm["body"]) == rows
        assert before["statusCode"] == after["statusCode"]
        assert before["headers"] == after["headers"]
        without_contributor = [{k: v for k, v in row.items() if k != "contributor"} for row in rows]
        assert without_contributor == json.loads(before["body"])
        expected_flags = {"Community Pantry": True, "Neighborhood Kitchen": False,
                          "Volunteer Groceries": None}
        db_rows = [row for row in rows if row["source"] == "db"]
        assert {row["name"] for row in db_rows} == set(expected_flags)
        for row in db_rows:
            assert row["contributor"] is (expected_flags[row["name"]] if column_present else None)
            assert row["distance_status"] == "ok"
        ai_rows = [row for row in rows if row["source"] == "ai"]
        assert len(ai_rows) == (1 if ai_mode == "available" else 0)
        for row in ai_rows:
            assert row["contributor"] is False
            assert row["collaborator"] is False
            assert row["distance"] > 0
        if sort_by == "distance":
            assert [row["distance"] for row in rows] == sorted(row["distance"] for row in rows)


@pytest.mark.parametrize("column_present", [True, False])
def test_real_queries_keep_city_category_and_distinct_filtering(database, column_present):
    """Both SQL branches tolerate the old schema without changing search scope."""
    with fixture_schema(database, column_present) as schema, load_app(database, schema) as app:
        in_city = app.helpers.get_orgs_from_db("Chicago, IL", "Food")
        all_cities = app.helpers.get_orgs_from_db("", "Food")
        other_category = app.helpers.get_orgs_from_db("Chicago", "Housing")
        assert set(in_city["org_id"]) == {"org-true", "org-false", "org-null"}
        assert len(in_city) == 3
        assert set(all_cities["org_id"]) == set(in_city["org_id"]) | {"org-other-city"}
        assert other_category["org_id"].tolist() == ["org-other-category"]
        assert ("is_contributor" in in_city.columns) is column_present


@pytest.mark.parametrize("ai_available", [True, False])
def test_no_matching_db_organizations(database, ai_available):
    """Empty DB results work for AI-only and fully empty responses."""
    payload = ai_response() if ai_available else ai_response([])
    with fixture_schema(database) as schema:
        with database.cursor() as cursor:
            cursor.execute(sql.SQL("DELETE FROM {}.org_skills").format(sql.Identifier(schema)))
        with load_app(database, schema, payload) as app:
            rows = assert_response_contract(app.handler.lambda_handler(event(), None))
        assert len(rows) == (1 if ai_available else 0)
        if rows:
            assert rows[0]["contributor"] is False


def test_column_can_be_added_during_warm_container(database):
    """No cached schema detection hides a contributor column after migration."""
    with fixture_schema(database, False) as schema, load_app(database, schema) as app:
        before = assert_response_contract(app.handler.lambda_handler(event(), None))
        assert all(row["contributor"] is None for row in before if row["source"] == "db")
        with database.cursor() as cursor:
            cursor.execute(sql.SQL("ALTER TABLE {}.organizations ADD COLUMN is_contributor BOOLEAN DEFAULT TRUE").format(sql.Identifier(schema)))
        after = assert_response_contract(app.handler.lambda_handler(event(), None))
        assert all(row["contributor"] is True for row in after if row["source"] == "db")
