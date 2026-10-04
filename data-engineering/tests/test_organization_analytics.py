from datetime import datetime
import os
os.environ.setdefault("SECRET_KEY", "test-secret")

import pytest
from flask import Flask
from fastapi.testclient import TestClient

import src.organization_analytics as organization_module
from src.organization_analytics import (
    build_analytics,
    build_organization_query,
    default_response,
    fetch_organization_rows,
    organization_analytics,
    parse_filters,
)
from src.main import app


def organization_row(**overrides):
    row = {
        "org_id": "ORG1",
        "city_name": "Austin",
        "state_id": "TX",
        "state_name": "Texas",
        "org_size": "Small",
        "org_rating": 5,
        "is_collaborator": True,
        "is_contributor": False,
        "org_type": "Non-Profit",
        "created_at": datetime(2026, 1, 15),
    }
    row.update(overrides)
    return row


class Cursor:
    def __init__(self, rows=None, first_error=None):
        self.rows = rows or []
        self.first_error = first_error
        self.calls = []

    def execute(self, query, params=()):
        self.calls.append((query, params))
        if self.first_error and len(self.calls) == 1:
            raise self.first_error

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeCursor:
    def __init__(self, fetchall_result=None, fetchone_result=None):
        self._fetchall_result = fetchall_result or []
        self._fetchone_result = fetchone_result
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchall(self):
        return self._fetchall_result

    def fetchone(self):
        return self._fetchone_result



def test_filters_and_parameterized_custom_dates():
    filters = parse_filters({"time_filter": "CUSTOM", "start_date": "2026-01-01", "end_date": "2026-06-30", "group_by": "monthly", "region": "California", "organization_type": "non_profit"})
    query, params = build_organization_query(filters)
    assert "%s" in query
    assert params == ("2026-01-01", "2026-06-30", "California", "California", "California", "non_profit")


@pytest.mark.parametrize("payload", [{"time_filter": "BAD"}, {"time_filter": "CUSTOM", "start_date": "2026-01-01"}, {"group_by": "hourly"}, {"organization_type": "charity"}])
def test_invalid_filters_are_rejected(payload):
    with pytest.raises(ValueError):
        parse_filters(payload)


def test_empty_result_has_complete_response_shape():
    assert build_analytics([]) == default_response()


def test_metrics_and_null_rating_are_safe():
    rows = [organization_row(), organization_row(org_id="ORG2", org_rating=None, is_collaborator=False, is_contributor=True, org_type="For-profit", created_at=datetime(2026, 2, 2))]
    response = build_analytics(rows)
    assert response["summary"] == {"total_organizations": 2, "total_collaborators": 1, "total_contributors": 1, "average_org_rating": 5.0}
    assert response["rating_distribution"] == [{"rating": 1, "organization_count": 0}, {"rating": 2, "organization_count": 0}, {"rating": 3, "organization_count": 0}, {"rating": 4, "organization_count": 0}, {"rating": 5, "organization_count": 1}]
    assert response["organization_type_distribution"][0]["total"] == 1


def test_missing_is_contributor_column_uses_compatibility_query():
    cursor = Cursor(rows=[organization_row(is_contributor=False)], first_error=RuntimeError("column is_contributor does not exist"))
    rows = fetch_organization_rows(cursor, parse_filters({}))
    assert len(cursor.calls) == 2
    assert "FALSE AS is_contributor" in cursor.calls[1][0]
    assert rows[0]["org_id"] == "ORG1"


def test_database_error_is_not_hidden_from_query_helper():
    cursor = Cursor(first_error=RuntimeError("database unavailable"))
    with pytest.raises(RuntimeError, match="database unavailable"):
        fetch_organization_rows(cursor, parse_filters({}))


def test_post_endpoint_returns_dashboard_response(monkeypatch):
    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor(rows=[organization_row()])

        def cursor(self):
            return self.cursor_instance

        def close(self):
            pass

    monkeypatch.setattr(organization_module, "get_db_connection", lambda: Connection())
    app = Flask(__name__)
    app.register_blueprint(organization_analytics)

    response = app.test_client().post("/analytics/organizations", json={"time_filter": "ALL", "group_by": "monthly"})

    assert response.status_code == 200
    assert set(response.json) == set(default_response())
    assert response.json["summary"]["total_organizations"] == 1


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


@pytest.fixture
def client():
    return TestClient(app)


def admin_token(client):
    resp = client.post("/token", data={"username": "admin_user", "password": "x"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def volunteer_token(client):
    resp = client.post("/token", data={"username": "volunteer_user", "password": "x"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_summary_requires_auth(client):
    resp = client.get("/analytics/organizations/overview/summary")
    assert resp.status_code == 401


def test_summary_requires_admin_role(client):
    token = volunteer_token(client)
    resp = client.get("/analytics/organizations/overview/summary", headers=auth_headers(token))
    assert resp.status_code == 403


def test_summary_returns_counts(client, monkeypatch):
    fake_cursor = FakeCursor(fetchone_result=(10, 6, 4))
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(fake_cursor))

    token = admin_token(client)
    resp = client.get("/analytics/organizations/overview/summary", headers=auth_headers(token))

    assert resp.status_code == 200
    assert resp.json() == {
        "total_organizations": 10,
        "total_collaborators": 6,
        "total_contributors": 4,
    }


def test_summary_invalid_time_filter_is_rejected(client, monkeypatch):
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(FakeCursor()))
    token = admin_token(client)

    resp = client.get(
        "/analytics/organizations/overview/summary",
        headers=auth_headers(token),
        params={"time_filter": "NOT_A_FILTER"},
    )

    assert resp.status_code == 400


def test_custom_time_filter_requires_dates(client, monkeypatch):
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(FakeCursor()))
    token = admin_token(client)

    resp = client.get(
        "/analytics/organizations/overview/summary",
        headers=auth_headers(token),
        params={"time_filter": "CUSTOM"},
    )

    assert resp.status_code == 400


def test_types_groups_by_org_type(client, monkeypatch):
    fake_cursor = FakeCursor(fetchall_result=[("Nonprofit", 7), ("Community Group", 3)])
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(fake_cursor))

    token = admin_token(client)
    resp = client.get("/analytics/organizations/overview/types", headers=auth_headers(token))

    assert resp.status_code == 200
    assert resp.json() == [
        {"org_type": "Nonprofit", "total_organizations": 7},
        {"org_type": "Community Group", "total_organizations": 3},
    ]


def test_top_rated_respects_limit_param(client, monkeypatch):
    fake_cursor = FakeCursor(fetchall_result=[("Org A", "Nonprofit", 4.9)])
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(fake_cursor))

    token = admin_token(client)
    resp = client.get(
        "/analytics/organizations/performance/top_rated",
        headers=auth_headers(token),
        params={"limit": 1},
    )

    assert resp.status_code == 200
    assert resp.json() == [{"org_name": "Org A", "org_type": "Nonprofit", "rating": 4.9}]
    # limit is bound as the last query param
    _, params = fake_cursor.queries[-1]
    assert params[-1] == 1


def test_top_rated_limit_out_of_range_rejected(client, monkeypatch):
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(FakeCursor()))
    token = admin_token(client)

    resp = client.get(
        "/analytics/organizations/performance/top_rated",
        headers=auth_headers(token),
        params={"limit": 500},
    )

    assert resp.status_code == 422


def test_ratings_by_category_handles_null_average(client, monkeypatch):
    fake_cursor = FakeCursor(fetchall_result=[("Education", None, 2)])
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(fake_cursor))

    token = admin_token(client)
    resp = client.get("/analytics/organizations/performance/ratings_by_category", headers=auth_headers(token))

    assert resp.status_code == 200
    assert resp.json() == [{"category": "Education", "average_rating": None, "total_organizations": 2}]
