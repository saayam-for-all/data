"""
Smoke test / demo - run the Lambda handler against fully hardcoded fake
data across two mocked regions. No database, no AWS, no network calls
of any kind.

Run with: python smoke_test.py
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import lambda_function

# Hand-written fake rows: (user_id, last_updated_at)
VIRGINIA_ROWS = [
    ("SID-00-000-000-001", datetime(2026, 5, 12, 7, 15, tzinfo=timezone.utc)),
    ("SID-00-000-000-004", datetime(2026, 5, 11, 18, 40, tzinfo=timezone.utc)),
    ("SID-00-000-000-007", datetime(2026, 5, 8, 14, 30, tzinfo=timezone.utc)),
]
IRELAND_ROWS = [
    ("SID-00-000-000-002", datetime(2026, 5, 10, 9, 5, tzinfo=timezone.utc)),
    ("SID-00-000-000-009", datetime(2026, 5, 9, 22, 0, tzinfo=timezone.utc)),
]


def _fake_conn(rows):
    """A fake single-region connection - never actually connects anywhere,
    just returns the hardcoded rows above."""
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False

    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


def _fake_regions(virginia_rows, ireland_rows):
    return {
        "VIRGINIA": _fake_conn(virginia_rows),
        "IRELAND": _fake_conn(ireland_rows),
    }


def run(page: int, page_size: int):
    with patch(
        "lambda_function.get_region_connections",
        return_value=_fake_regions(VIRGINIA_ROWS, IRELAND_ROWS),
    ):
        event = {"page": page, "page_size": page_size}
        result = lambda_function.lambda_handler(event, None)
        print(f"\n--- page={page}, page_size={page_size} (merged across both regions) ---")
        print(json.dumps(result, indent=2, default=str))


def run_empty():
    with patch(
        "lambda_function.get_region_connections",
        return_value=_fake_regions([], []),
    ):
        result = lambda_function.lambda_handler({"page": 1, "page_size": 5}, None)
        print("\n--- empty result set ---")
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    run(page=1, page_size=3)
    run(page=2, page_size=3)
    run_empty()
