"""Local + cursor-based unit tests for steward_volunteer_review_api (issue #273).

Runs with no AWS or DB access: a fake cursor returns canned UNDER_REVIEW rows,
so pagination, sorting, formatting, and the empty case are all exercised.

    pytest data-analytics/lambda_functions/test_steward_volunteer_review_api.py
    python  data-analytics/lambda_functions/test_steward_volunteer_review_api.py
"""

from datetime import datetime

import steward_volunteer_review_api as api


class FakeCursor:
    """Returns canned rows regardless of the query; records params passed."""

    def __init__(self, rows):
        self._rows = rows
        self.executed_params = None

    def execute(self, query, params=None):
        self.executed_params = params

    def fetchall(self):
        return self._rows

    def close(self):
        pass


def _dt(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


def test_fetch_uses_review_status_param():
    cur = FakeCursor([])
    api.fetch_review_requests(cur, "u", "va")
    assert cur.executed_params == (api.REVIEW_STATUS,)


def test_pagination_and_sorting():
    rows = [
        ("SID-1", _dt("2026-05-12 07:15:00")),
        ("SID-2", _dt("2026-05-13 09:00:00")),
        ("SID-3", _dt("2026-05-11 06:00:00")),
    ]
    rows.sort(key=lambda r: (r[1] is not None, r[1]), reverse=True)
    result = api.paginate(rows, page=1, page_size=2)

    assert [d["user_id"] for d in result["data"]] == ["SID-2", "SID-1"]
    assert result["data"][0]["updated_time"] == "2026-05-13T09:00:00Z"
    assert result["data"][0]["volunteer_review"] == "Review"
    assert result["pagination"] == {
        "current_page": 1,
        "page_size": 2,
        "total_records": 3,
        "total_pages": 2,
    }


def test_empty_returns_ok_with_empty_array():
    result = api.paginate([], page=1, page_size=5)
    assert result["data"] == []
    assert result["pagination"]["total_records"] == 0
    assert result["pagination"]["total_pages"] == 0


def test_pagination_params_are_clamped():
    assert api.get_pagination_params({"page": -3, "page_size": 9999}) == (
        1,
        api.MAX_PAGE_SIZE,
    )
    assert api.get_pagination_params({}) == (
        api.DEFAULT_PAGE,
        api.DEFAULT_PAGE_SIZE,
    )
    assert api.get_pagination_params({"page": "x", "page_size": "y"}) == (
        api.DEFAULT_PAGE,
        api.DEFAULT_PAGE_SIZE,
    )


if __name__ == "__main__":
    test_fetch_uses_review_status_param()
    test_pagination_and_sorting()
    test_empty_returns_ok_with_empty_array()
    test_pagination_params_are_clamped()
    print("All tests passed.")
