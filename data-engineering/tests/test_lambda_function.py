"""
Local unit tests for the Steward Dashboard - Review Volunteers lambda.
Matches the multi-region (Virginia + Ireland) schema confirmed in PR #298.

Run with: pytest test_lambda_function.py -v

Both regional DB connections are fully mocked - no real database or AWS
access needed, per the "local development first" rule in CONTRIBUTING.md.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import lambda_function


def _mock_conn(rows):
    """A fake single-region connection returning the given rows."""
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False

    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


def _mock_regions(virginia_rows, ireland_rows):
    return {
        "VIRGINIA": _mock_conn(virginia_rows),
        "IRELAND": _mock_conn(ireland_rows),
    }


@patch("lambda_function.get_region_connections")
def test_merges_and_sorts_across_regions(mock_get_regions):
    virginia_rows = [
        ("SID-00-000-000-001", datetime(2026, 5, 12, 7, 15, tzinfo=timezone.utc)),
        ("SID-00-000-000-003", datetime(2026, 5, 9, 3, 0, tzinfo=timezone.utc)),
    ]
    ireland_rows = [
        ("SID-00-000-000-002", datetime(2026, 5, 11, 10, 0, tzinfo=timezone.utc)),
    ]
    mock_get_regions.return_value = _mock_regions(virginia_rows, ireland_rows)

    result = lambda_function.lambda_handler({"page": 1, "page_size": 5}, None)

    assert result["statusCode"] == 200
    ids_in_order = [row["user_id"] for row in result["body"]["data"]]
    assert ids_in_order == [
        "SID-00-000-000-001",
        "SID-00-000-000-002",
        "SID-00-000-000-003",
    ]
    assert all(row["volunteer_review"] == "Review" for row in result["body"]["data"])
    assert result["body"]["pagination"]["total_records"] == 3


@patch("lambda_function.get_region_connections")
def test_returns_empty_array_when_no_records(mock_get_regions):
    mock_get_regions.return_value = _mock_regions([], [])

    result = lambda_function.lambda_handler({"page": 1, "page_size": 5}, None)

    assert result["statusCode"] == 200
    assert result["body"]["data"] == []
    assert result["body"]["pagination"]["total_pages"] == 0


@patch("lambda_function.get_region_connections")
def test_pagination_across_combined_results(mock_get_regions):
    virginia_rows = [
        (f"SID-{i}", datetime(2026, 5, i, tzinfo=timezone.utc)) for i in range(1, 5)
    ]
    mock_get_regions.return_value = _mock_regions(virginia_rows, [])

    result = lambda_function.lambda_handler({"page": 2, "page_size": 2}, None)

    assert len(result["body"]["data"]) == 2
    assert result["body"]["pagination"]["current_page"] == 2
    assert result["body"]["pagination"]["total_pages"] == 2


@patch("lambda_function.get_region_connections")
def test_defaults_invalid_pagination_params(mock_get_regions):
    mock_get_regions.return_value = _mock_regions([], [])

    result = lambda_function.lambda_handler({"page": -1, "page_size": "abc"}, None)

    assert result["body"]["pagination"]["current_page"] == 1
    assert result["body"]["pagination"]["page_size"] == 5


@patch("lambda_function.get_region_connections")
def test_db_error_returns_safe_500(mock_get_regions):
    mock_get_regions.side_effect = Exception("connection refused")

    result = lambda_function.lambda_handler({"page": 1, "page_size": 5}, None)

    assert result["statusCode"] == 500
    assert "error" in result["body"]
