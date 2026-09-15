"""Tests for the Organization Analytics API endpoints (issue #228).

The organizations table isn't reachable in CI, so these mock the DB layer
(src.main.get_db_connection) the same way CONTRIBUTING.md asks contributors
to mock AWS calls for local-only development. For a real end-to-end check
against Postgres, run `docker compose -f infrastructure/docker-compose.yml
up db` (seeds infrastructure/db/init/001_organizations.sql) and hit the API
with a .env pointed at localhost:5432.
"""
import os

os.environ.setdefault("SECRET_KEY", "test-secret")

import pytest
from fastapi.testclient import TestClient

from src.main import app


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

    def close(self):
        pass


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
