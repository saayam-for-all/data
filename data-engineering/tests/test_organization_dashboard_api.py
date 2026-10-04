"""Tests for the consolidated Organization Dashboard endpoint (issue #228):
POST /analytics/organizations.

Mocks src.main.get_db_connection the same way test_organization_analytics.py
does, per CONTRIBUTING.md's guidance for local-only development (the real
organizations table isn't reachable in CI). For a real end-to-end check
against Postgres, run `docker compose -f infrastructure/docker-compose.yml up
db` (seeds infrastructure/db/init/001_organizations.sql) and hit the API with
a .env pointed at localhost:5432.
"""
import os
from datetime import datetime, timezone

os.environ.setdefault("SECRET_KEY", "test-secret")

import pytest
from fastapi.testclient import TestClient

from src.main import app


class SequencedFakeCursor:
    """Returns queued results in call order — one entry per cursor.execute(),
    regardless of whether the caller follows it with fetchone() or fetchall().
    """

    def __init__(self, results):
        self._results = list(results)
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def _next(self):
        return self._results.pop(0)

    def fetchone(self):
        return self._next()

    def fetchall(self):
        return self._next()

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


PERIOD_1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
PERIOD_2 = datetime(2026, 2, 1, tzinfo=timezone.utc)


def full_result_set():
    """One result per cursor.execute() call, in the order main.py issues them:
    summary(one), growth_trend(many), by_location(many), by_size(many),
    collaborator_vs_contributor(one), rating_distribution(many),
    org_type_distribution(many).
    """
    return [
        (126, 42, 84, 4.2),  # summary
        [(PERIOD_1, 100, 34), (PERIOD_2, 108, 36)],  # growth_trend
        [("CA", "California", 32, None), ("TX", "Texas", 24, None)],  # by_location
        [("Small", 50), ("Medium", 45), ("Large", 31)],  # by_size
        (42, 84),  # collaborator_vs_contributor
        [(1, 1), (2, 3), (3, 12), (4, 46), (5, 64)],  # rating_distribution
        [(PERIOD_1, 41, 68), (PERIOD_2, 43, 68)],  # org_type_distribution
    ]


def test_dashboard_requires_auth(client):
    resp = client.post("/analytics/organizations", json={})
    assert resp.status_code == 401


def test_dashboard_requires_admin_role(client):
    token = volunteer_token(client)
    resp = client.post("/analytics/organizations", json={}, headers=auth_headers(token))
    assert resp.status_code == 403


def test_dashboard_default_payload_returns_full_shape(client, monkeypatch):
    fake_cursor = SequencedFakeCursor(full_result_set())
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(fake_cursor))

    token = admin_token(client)
    resp = client.post(
        "/analytics/organizations",
        json={"time_filter": "30D", "group_by": "daily", "region": "ALL", "organization_type": "ALL"},
        headers=auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()

    assert body["summary"] == {
        "total_organizations": 126,
        "total_collaborators": 42,
        "total_contributors": 84,
        "average_org_rating": 4.2,
    }
    assert body["growth_trend"][0]["total_organizations"] == 100
    assert body["organizations_by_location"][0]["state_id"] == "CA"
    # 32 of 56 total location rows -> 57.1%
    assert body["organizations_by_location"][0]["percentage"] == pytest.approx(57.1, abs=0.05)
    assert body["organizations_by_size"] == [
        {"org_size": "Small", "organization_count": 50},
        {"org_size": "Medium", "organization_count": 45},
        {"org_size": "Large", "organization_count": 31},
    ]
    assert body["collaborator_vs_contributor"] == [
        {"type": "collaborator", "organization_count": 42, "percentage": 33.3},
        {"type": "contributor", "organization_count": 84, "percentage": 66.7},
    ]
    # All five star ratings always present, in order
    assert [r["rating"] for r in body["rating_distribution"]] == [1, 2, 3, 4, 5]
    assert body["organization_type_distribution"][1] == {
        "period": PERIOD_2.isoformat(),
        "for_profit": 43,
        "non_profit": 68,
        "total": 111,
    }


def test_dashboard_rating_distribution_fills_missing_stars_with_zero(client, monkeypatch):
    results = full_result_set()
    results[5] = [(4, 46), (5, 64)]  # only 4 and 5 stars present; nulls excluded upstream
    fake_cursor = SequencedFakeCursor(results)
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(fake_cursor))

    token = admin_token(client)
    resp = client.post("/analytics/organizations", json={}, headers=auth_headers(token))

    assert resp.status_code == 200
    ratings = {r["rating"]: r["organization_count"] for r in resp.json()["rating_distribution"]}
    assert ratings == {1: 0, 2: 0, 3: 0, 4: 46, 5: 64}


def test_dashboard_invalid_time_filter_is_rejected(client, monkeypatch):
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(SequencedFakeCursor([])))
    token = admin_token(client)

    resp = client.post(
        "/analytics/organizations",
        json={"time_filter": "NOT_A_FILTER"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


def test_dashboard_custom_time_filter_requires_dates(client, monkeypatch):
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(SequencedFakeCursor([])))
    token = admin_token(client)

    resp = client.post(
        "/analytics/organizations",
        json={"time_filter": "CUSTOM"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


def test_dashboard_custom_time_filter_with_dates_succeeds(client, monkeypatch):
    fake_cursor = SequencedFakeCursor(full_result_set())
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(fake_cursor))
    token = admin_token(client)

    resp = client.post(
        "/analytics/organizations",
        json={
            "time_filter": "CUSTOM",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "group_by": "monthly",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200


def test_dashboard_invalid_group_by_is_rejected(client, monkeypatch):
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(SequencedFakeCursor([])))
    token = admin_token(client)

    resp = client.post(
        "/analytics/organizations",
        json={"group_by": "fortnightly"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


def test_dashboard_empty_result_set_returns_safe_defaults(client, monkeypatch):
    empty_results = [
        (0, 0, 0, None),  # summary
        [],  # growth_trend
        [],  # by_location
        [],  # by_size
        (0, 0),  # collaborator_vs_contributor
        [],  # rating_distribution
        [],  # org_type_distribution
    ]
    fake_cursor = SequencedFakeCursor(empty_results)
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(fake_cursor))
    token = admin_token(client)

    resp = client.post("/analytics/organizations", json={}, headers=auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["average_org_rating"] is None
    assert body["organizations_by_location"] == []
    assert [r["organization_count"] for r in body["rating_distribution"]] == [0, 0, 0, 0, 0]
    assert body["collaborator_vs_contributor"][0]["percentage"] == 0.0


def test_dashboard_region_filter_binds_state_param(client, monkeypatch):
    fake_cursor = SequencedFakeCursor(full_result_set())
    monkeypatch.setattr("src.main.get_db_connection", lambda: FakeConnection(fake_cursor))
    token = admin_token(client)

    resp = client.post(
        "/analytics/organizations",
        json={"region": "California"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    # Every query after the region filter is built should carry the bound region params
    summary_query, summary_params = fake_cursor.queries[0]
    assert "state_name" in summary_query
    assert "California" in summary_params


def test_dashboard_db_connection_failure_returns_500(client, monkeypatch):
    monkeypatch.setattr("src.main.get_db_connection", lambda: None)
    token = admin_token(client)

    resp = client.post("/analytics/organizations", json={}, headers=auth_headers(token))
    assert resp.status_code == 500
