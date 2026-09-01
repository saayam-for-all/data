"""
Steward Dashboard - Review Volunteers API
AWS Lambda entry point.

Schema/behavior matches PR #298 (BVSSUMANTH):
    - Table: volunteer_applications (there is no `volunteers_details` table)
    - Status column: application_status, enum value 'IN_REVIEW'
    - Timestamp column: last_updated_at
    - volunteer_review is a fixed "Review" action label, not a DB column
    - The review queue spans two regional databases (Virginia + Ireland);
      results are merged and re-sorted before pagination is applied,
      since a global sort across two DBs can't be done with per-region
      LIMIT/OFFSET.

Returns only: user_id, updated_time, volunteer_review - sorted by
updated_time descending, paginated, empty array when nothing found.
"""

import json
import logging
import math
from typing import Any, Dict, List, Tuple

from db_client import get_region_connections

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 5
MAX_PAGE_SIZE = 100

APPLICATION_STATUS_IN_REVIEW = "IN_REVIEW"
VOLUNTEER_REVIEW_ACTION = "Review"

SELECT_QUERY = """
    SELECT
        u.user_id,
        va.last_updated_at
    FROM users u
    JOIN volunteer_applications va ON u.user_id = va.user_id
    WHERE va.application_status = %s
"""


def _parse_pagination(payload: Dict[str, Any]) -> Tuple[int, int]:
    """Validate and normalize page / page_size from the request payload."""
    page = payload.get("page", DEFAULT_PAGE)
    page_size = payload.get("page_size", DEFAULT_PAGE_SIZE)

    if not isinstance(page, int) or page < 1:
        page = DEFAULT_PAGE
    if not isinstance(page_size, int) or page_size < 1:
        page_size = DEFAULT_PAGE_SIZE
    page_size = min(page_size, MAX_PAGE_SIZE)

    return page, page_size


def _fetch_region_rows(conn) -> List[Tuple[str, Any]]:
    """Run the parameterized query against one region's connection."""
    with conn.cursor() as cur:
        cur.execute(SELECT_QUERY, (APPLICATION_STATUS_IN_REVIEW,))
        return cur.fetchall()


def _fetch_all_reviews() -> List[Dict[str, Any]]:
    """Query every configured region, merge results, and sort by
    updated_time descending in Python (a cross-region global sort can't
    be pushed down to per-region SQL LIMIT/OFFSET)."""
    connections = get_region_connections()
    combined_rows: List[Tuple[str, Any]] = []
    try:
        for conn in connections.values():
            combined_rows.extend(_fetch_region_rows(conn))
    finally:
        for conn in connections.values():
            conn.close()

    combined_rows.sort(key=lambda row: row[1], reverse=True)

    return [
        {
            "user_id": row[0],
            "updated_time": row[1].isoformat() if hasattr(row[1], "isoformat") else row[1],
            "volunteer_review": VOLUNTEER_REVIEW_ACTION,
        }
        for row in combined_rows
    ]


def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {"statusCode": status_code, "body": body}


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda entry point.

    Accepts either a raw payload dict (local/manual invocation, matches
    the issue's example: {"page": 1, "page_size": 5}) or an API Gateway
    proxy-style event with a JSON-encoded "body" key.
    """
    try:
        raw_body = event.get("body", event)
        if isinstance(raw_body, str):
            raw_body = json.loads(raw_body) if raw_body else {}
        raw_body = raw_body or {}

        page, page_size = _parse_pagination(raw_body)

        all_reviews = _fetch_all_reviews()
        total_records = len(all_reviews)
        total_pages = math.ceil(total_records / page_size) if total_records else 0

        start = (page - 1) * page_size
        end = start + page_size
        page_data = all_reviews[start:end]

        return _response(200, {
            "data": page_data,
            "pagination": {
                "current_page": page,
                "page_size": page_size,
                "total_records": total_records,
                "total_pages": total_pages,
            },
        })

    except Exception:
        # Never leak DB internals/stack traces to the caller.
        logger.exception("Failed to retrieve volunteer review records")
        return _response(500, {
            "error": "Unable to retrieve volunteer review data at this time.",
        })
