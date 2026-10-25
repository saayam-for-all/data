"""Local + cursor-based unit tests for steward_volunteer_review_api (issue #273).

The users/volunteers tables aren't reachable in CI, so these mock the DB layer
(connect_region) with a fake cursor that returns canned IN_REVIEW rows. Runs
two ways:

    pytest data-analytics/lambda_functions/test_steward_volunteer_review_api.py
    python  data-analytics/lambda_functions/test_steward_volunteer_review_api.py

The plain-python entrypoint lets contributors verify locally without pytest.
"""

import json
from datetime import datetime

import steward_volunteer_review_api as api


class FakeCursor:
    """Minimal psycopg2-cursor stand-in that records queries/params."""

    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


def _dt(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


# 20 IN_REVIEW rows so pagination math matches the issue example (page_size 5 -> 4 pages).
SAMPLE_ROWS = [
    (f"SID-00-000-000-{i:03d}", _dt(f"2026-05-{(i % 28) + 1:02d} 07:15:00"))
    for i in range(1, 21)
]


def _single_region(monkeypatch, rows):
    """Wire connect_region so only Virginia returns `rows`; Ireland is skipped."""
    cursor = FakeCursor(rows)
    conn = FakeConnection(cursor)

    def fake_connect(param_env_var):
        return conn if param_env_var == "VIRGINIA_DB_PARAM" else None

    monkeypatch.setattr(api, "connect_region", fake_connect)
    return conn, cursor


# --- pagination param handling ---------------------------------------------

def test_pagination_defaults():
    assert api.get_pagination_params({}) == (api.DEFAULT_PAGE, api.DEFAULT_PAGE_SIZE)


def test_pagination_clamps_bad_values():
    assert api.get_pagination_params({"page": 0, "page_size": -3}) == (1, 5)
    assert api.get_pagination_params({"page": "x", "page_size": "y"}) == (1, 5)
    assert api.get_pagination_params({"page_size": 9999})[1] == api.MAX_PAGE_SIZE


# --- happy path -------------------------------------------------------------

def test_returns_first_page_sorted_desc(monkeypatch):
    _single_region(monkeypatch, SAMPLE_ROWS)

    resp = api.lambda_handler({"page": 1, "page_size": 5}, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])

    assert body["pagination"] == {
        "current_page": 1,
        "page_size": 5,
        "total_records": 20,
        "total_pages": 4,
    }
    assert len(body["data"]) == 5

    # descending updated_time
    times = [row["updated_time"] for row in body["data"]]
    assert times == sorted(times, reverse=True)

    first = body["data"][0]
    assert set(first.keys()) == {"user_id", "updated_time", "volunteer_review"}
    assert first["volunteer_review"] == "Review"
    assert first["updated_time"].endswith("Z")


def test_query_is_parameterized_and_filters_review_status(monkeypatch):
    _, cursor = _single_region(monkeypatch, SAMPLE_ROWS)
    api.lambda_handler({"page": 1, "page_size": 5}, None)

    query, params = cursor.queries[0]
    assert params == (api.REVIEW_STATUS,)          # value passed out-of-band, not interpolated
    assert "application_status = %s" in query
    assert "ORDER BY va.last_updated_at DESC" in query


def test_second_page_offsets_correctly(monkeypatch):
    _single_region(monkeypatch, SAMPLE_ROWS)
    page1 = json.loads(api.lambda_handler({"page": 1, "page_size": 5}, None)["body"])["data"]
    page2 = json.loads(api.lambda_handler({"page": 2, "page_size": 5}, None)["body"])["data"]

    ids1 = {r["user_id"] for r in page1}
    ids2 = {r["user_id"] for r in page2}
    assert ids1.isdisjoint(ids2)


def test_connections_are_closed(monkeypatch):
    conn, _ = _single_region(monkeypatch, SAMPLE_ROWS)
    api.lambda_handler({"page": 1, "page_size": 5}, None)
    assert conn.closed is True


# --- merging two regions ----------------------------------------------------

def test_merges_and_sorts_across_regions(monkeypatch):
    va_rows = [("SID-VA-1", _dt("2026-05-10 10:00:00"))]
    ie_rows = [("SID-IE-1", _dt("2026-05-12 10:00:00"))]

    def fake_connect(param_env_var):
        if param_env_var == "VIRGINIA_DB_PARAM":
            return FakeConnection(FakeCursor(va_rows))
        if param_env_var == "IRELAND_DB_PARAM":
            return FakeConnection(FakeCursor(ie_rows))
        return None

    monkeypatch.setattr(api, "connect_region", fake_connect)

    body = json.loads(api.lambda_handler({"page": 1, "page_size": 5}, None)["body"])
    assert body["pagination"]["total_records"] == 2
    # Ireland row is newer, so it comes first after the cross-region sort.
    assert body["data"][0]["user_id"] == "SID-IE-1"
    assert body["data"][1]["user_id"] == "SID-VA-1"


# --- empty + error paths ----------------------------------------------------

def test_empty_results_return_ok_with_empty_array(monkeypatch):
    _single_region(monkeypatch, [])
    resp = api.lambda_handler({"page": 1, "page_size": 5}, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["data"] == []
    assert body["pagination"] == {
        "current_page": 1,
        "page_size": 5,
        "total_records": 0,
        "total_pages": 0,
    }


def test_db_error_returns_safe_response(monkeypatch):
    def boom(param_env_var):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(api, "connect_region", boom)
    resp = api.lambda_handler({"page": 1, "page_size": 5}, None)
    assert resp["statusCode"] == 500
    body = json.loads(resp["body"])
    assert body["data"] == []
    assert body["pagination"]["total_records"] == 0
    assert "error" in body


def test_string_body_is_parsed(monkeypatch):
    _single_region(monkeypatch, SAMPLE_ROWS)
    event = {"body": json.dumps({"page": 1, "page_size": 5})}
    resp = api.lambda_handler(event, None)
    assert resp["statusCode"] == 200
    assert len(json.loads(resp["body"])["data"]) == 5


# --- plain-python runner (no pytest) ----------------------------------------

class _MonkeyPatch:
    """Tiny monkeypatch shim so the tests run without pytest installed."""

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
    passed = 0
    failed = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        mp = _MonkeyPatch()
        try:
            if func.__code__.co_argcount:
                func(mp)
            else:
                func()
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
