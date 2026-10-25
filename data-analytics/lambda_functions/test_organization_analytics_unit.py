"""Cursor-based / mock-database unit tests for organization_analytics.py.

No live PostgreSQL and no AWS are required: the DB layer (``get_db_connection``)
is replaced with a fake connection whose cursor returns canned rows routed by the
SQL each metric issues. Covers the happy path, empty result sets, invalid filters,
custom-date validation, query exceptions, and graceful is_contributor degradation.

Runs two ways:

    pytest data-analytics/lambda_functions/test_organization_analytics_unit.py
    python  data-analytics/lambda_functions/test_organization_analytics_unit.py
"""
import json

import organization_analytics as oa


# --- Fake DB layer ----------------------------------------------------------

class FakeCursor:
    """Routes each query to canned rows by a distinctive substring of its SQL."""

    def __init__(self, data, has_contributor=True, fail_on=None):
        self.data = data
        self.has_contributor = has_contributor
        self.fail_on = fail_on
        self.connection = None
        self._route = None
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if self.fail_on and self.fail_on in query:
            raise RuntimeError("simulated query failure")
        if "information_schema" in query:
            self._route = "contrib"
        elif "average_org_rating" in query:
            self._route = "summary"
        elif "new_organizations" in query:
            self._route = "growth"
        elif "city_name" in query:
            self._route = "location"
        elif "AS org_size" in query:
            self._route = "size"
        elif "AS collaborators" in query:
            self._route = "cvc"
        elif "generate_series" in query:
            self._route = "rating"
        elif "AS for_profit" in query:
            self._route = "typedist"
        else:
            self._route = None

    def fetchone(self):
        if self._route == "contrib":
            return {"exists": 1} if self.has_contributor else None
        return self.data.get(self._route)

    def fetchall(self):
        return self.data.get(self._route, [])

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False
        cursor.connection = self

    def cursor(self, cursor_factory=None):
        return self._cursor

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def wire(monkeypatch, data, has_contributor=True, fail_on=None):
    """Point get_db_connection at a fake connection with the given canned data."""
    cursor = FakeCursor(data, has_contributor=has_contributor, fail_on=fail_on)
    conn = FakeConnection(cursor)
    monkeypatch.setattr(oa, "get_db_connection", lambda: conn)
    return conn, cursor


# A small, internally consistent dataset: 10 orgs, 4 collaborators, 6 contributors.
FULL_DATA = {
    "summary": {
        "total_organizations": 10,
        "total_collaborators": 4,
        "total_contributors": 6,
        "average_org_rating": 4.2,
    },
    "growth": [
        {"period": "2026-01-01", "new_organizations": 6, "new_collaborators": 2},
        {"period": "2026-02-01", "new_organizations": 4, "new_collaborators": 2},
    ],
    "location": [
        {"state_id": "CA", "state_name": "California", "city_name": "San Jose", "organization_count": 4},
        {"state_id": "TX", "state_name": "Texas", "city_name": "Austin", "organization_count": 4},
        {"state_id": "CA", "state_name": "California", "city_name": "Los Angeles", "organization_count": 2},
    ],
    "size": [
        {"org_size": "small", "organization_count": 5},
        {"org_size": "large", "organization_count": 3},
        {"org_size": "medium", "organization_count": 2},
    ],
    "cvc": {"collaborators": 4, "contributors": 6},
    "rating": [
        {"rating": 1, "organization_count": 1},
        {"rating": 2, "organization_count": 1},
        {"rating": 3, "organization_count": 2},
        {"rating": 4, "organization_count": 2},
        {"rating": 5, "organization_count": 4},
    ],
    "typedist": [
        {"period": "2026-01-01", "for_profit": 2, "non_profit": 4},
        {"period": "2026-02-01", "for_profit": 1, "non_profit": 3},
    ],
}

# Empty dataset: no organizations match. generate_series still yields 5 zero
# rating buckets (that is exactly what the empty-result test must prove).
EMPTY_DATA = {
    "summary": {
        "total_organizations": 0,
        "total_collaborators": 0,
        "total_contributors": 0,
        "average_org_rating": None,
    },
    "growth": [],
    "location": [],
    "size": [],
    "cvc": {"collaborators": 0, "contributors": 0},
    "rating": [{"rating": r, "organization_count": 0} for r in range(1, 6)],
    "typedist": [],
}


def call():
    return oa.lambda_handler({"time_filter": "ALL", "group_by": "monthly"}, None)


# --- Happy path -------------------------------------------------------------

def test_full_structure_and_status(monkeypatch):
    wire(monkeypatch, FULL_DATA)
    resp = call()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    for key in ("summary", "growth_trend", "organizations_by_location",
                "organizations_by_size", "collaborator_vs_contributor",
                "rating_distribution", "organization_type_distribution"):
        assert key in body


def test_summary_values(monkeypatch):
    wire(monkeypatch, FULL_DATA)
    body = json.loads(call()["body"])
    assert body["summary"] == {
        "total_organizations": 10,
        "total_collaborators": 4,
        "total_contributors": 6,
        "average_org_rating": 4.2,
    }


def test_growth_trend_is_cumulative(monkeypatch):
    wire(monkeypatch, FULL_DATA)
    trend = json.loads(call()["body"])["growth_trend"]
    assert [r["total_organizations"] for r in trend] == [6, 10]
    assert [r["total_collaborators"] for r in trend] == [2, 4]


def test_location_nests_cities_by_state(monkeypatch):
    wire(monkeypatch, FULL_DATA)
    locs = json.loads(call()["body"])["organizations_by_location"]
    by_state = {r["state_id"]: r for r in locs}
    assert by_state["CA"]["organization_count"] == 6
    assert by_state["CA"]["percentage"] == 60.0
    assert sum(c["organization_count"] for c in by_state["CA"]["cities"]) == 6
    # cities sorted high-to-low within the state
    assert [c["city_name"] for c in by_state["CA"]["cities"]] == ["San Jose", "Los Angeles"]


def test_collaborator_vs_contributor_percentages(monkeypatch):
    wire(monkeypatch, FULL_DATA)
    cvc = {r["type"]: r for r in json.loads(call()["body"])["collaborator_vs_contributor"]}
    assert cvc["collaborator"]["organization_count"] == 4
    assert cvc["collaborator"]["percentage"] == 40.0
    assert cvc["contributor"]["percentage"] == 60.0


def test_rating_distribution_has_all_five_buckets(monkeypatch):
    wire(monkeypatch, FULL_DATA)
    rd = json.loads(call()["body"])["rating_distribution"]
    assert [r["rating"] for r in rd] == [1, 2, 3, 4, 5]
    assert sum(r["organization_count"] for r in rd) == 10


def test_type_distribution_totals(monkeypatch):
    wire(monkeypatch, FULL_DATA)
    otd = json.loads(call()["body"])["organization_type_distribution"]
    assert all(r["total"] == r["for_profit"] + r["non_profit"] for r in otd)
    assert otd[0]["total"] == 6


def test_queries_are_parameterized(monkeypatch):
    _, cursor = wire(monkeypatch, FULL_DATA)
    oa.lambda_handler({"time_filter": "ALL", "organization_type": "non_profit"}, None)
    # the organization_type filter value is passed out-of-band, never interpolated
    assert any(params and "non_profit" in params for _q, params in cursor.queries)


# --- Empty result set -------------------------------------------------------

def test_empty_result_set(monkeypatch):
    wire(monkeypatch, EMPTY_DATA)
    resp = call()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["summary"] == {
        "total_organizations": 0,
        "total_collaborators": 0,
        "total_contributors": 0,
        "average_org_rating": 0,
    }
    assert body["growth_trend"] == []
    assert body["organizations_by_location"] == []
    assert body["organizations_by_size"] == []
    assert body["organization_type_distribution"] == []
    # rating chart never loses its five bars, even with no data
    assert [r["rating"] for r in body["rating_distribution"]] == [1, 2, 3, 4, 5]
    assert all(r["organization_count"] == 0 for r in body["rating_distribution"])
    cvc = {r["type"]: r for r in body["collaborator_vs_contributor"]}
    assert cvc["collaborator"]["organization_count"] == 0
    assert cvc["collaborator"]["percentage"] == 0


# --- Filter validation & sanitizing ----------------------------------------

def test_custom_without_dates_returns_400(monkeypatch):
    wire(monkeypatch, FULL_DATA)
    resp = oa.lambda_handler({"time_filter": "CUSTOM"}, None)
    assert resp["statusCode"] == 400
    assert "error" in json.loads(resp["body"])


def test_custom_start_after_end_returns_400(monkeypatch):
    wire(monkeypatch, FULL_DATA)
    resp = oa.lambda_handler(
        {"time_filter": "CUSTOM", "start_date": "2026-06-30", "end_date": "2026-01-01"}, None)
    assert resp["statusCode"] == 400


def test_invalid_filter_values_sanitized(monkeypatch):
    wire(monkeypatch, FULL_DATA)
    resp = oa.lambda_handler(
        {"time_filter": "NOPE", "group_by": "hourly", "region": "ALL",
         "organization_type": "ALL"}, None)
    assert resp["statusCode"] == 200


def test_string_body_is_parsed(monkeypatch):
    wire(monkeypatch, FULL_DATA)
    resp = oa.lambda_handler({"body": json.dumps({"time_filter": "30D"})}, None)
    assert resp["statusCode"] == 200


# --- Failure paths ----------------------------------------------------------

def test_db_connection_failure_returns_500(monkeypatch):
    def boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(oa, "get_db_connection", boom)
    resp = call()
    assert resp["statusCode"] == 500
    body = json.loads(resp["body"])
    assert body["summary"]["total_organizations"] == 0


def test_one_failing_metric_does_not_cascade(monkeypatch):
    # Force the size query to raise; every other section must still return.
    wire(monkeypatch, FULL_DATA, fail_on="AS org_size")
    resp = call()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["organizations_by_size"] == []            # failed section: safe default
    assert body["summary"]["total_organizations"] == 10   # later metrics unaffected
    assert len(body["rating_distribution"]) == 5


def test_missing_is_contributor_column_degrades(monkeypatch):
    data = dict(EMPTY_DATA)  # summary/cvc already show 0 contributors
    wire(monkeypatch, data, has_contributor=False)
    body = json.loads(call()["body"])
    assert body["summary"]["total_contributors"] == 0
    assert any("is_contributor" in note for note in body.get("schema_notes", []))


# --- plain-python runner (no pytest) ---------------------------------------

class _MonkeyPatch:
    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value):
        old = getattr(target, name)
        self._undo.append((target, name, old))
        setattr(target, name, value)

    def undo(self):
        for target, name, old in reversed(self._undo):
            setattr(target, name, old)
        self._undo.clear()


def _run_local():
    passed = failed = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        mp = _MonkeyPatch()
        try:
            func(mp) if func.__code__.co_argcount else func()
            print(f"PASS {name}")
            passed += 1
        except AssertionError as exc:
            print(f"FAIL {name}: {exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR {name}: {exc}")
            failed += 1
        finally:
            mp.undo()
    print(f"\n{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    import sys

    sys.exit(1 if _run_local() else 0)
