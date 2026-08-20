"""Live-database smoke test for steward_volunteer_review_api.py.

Unlike test_steward_volunteer_review_api_unit.py (fully mocked), this runs the real handler
against a real Postgres, so it proves the SQL actually parses and the join actually matches.

Setup:
    psql -h localhost -p 5432 -U postgres -d saayam_local \
         -f data-analytics/sql/steward_volunteer_review_local_setup.sql

Run:
    cd data-analytics/lambda_functions
    ../.venv/bin/python test_steward_volunteer_review_api.py

Connection settings come from data-analytics/.env (gitignored). Captured output is committed
as data-analytics/steward_volunteer_review_test_output.txt for PR evidence.

Against the seeded fixture (100 applications, 80 in review status) expect:
    total_records = 80, total_pages = 16 at 5 per page.
"""

import json

from steward_volunteer_review_api import lambda_handler

CASES = [
    ("Ticket sample payload", {"page": 1, "page_size": 5}),
    ("Empty payload falls back to defaults", {}),
    ("Second page (must not overlap page 1)", {"page": 2, "page_size": 5}),
    ("Larger rows-per-page selection", {"page": 1, "page_size": 10}),
    ("Final page (partial)", {"page": 16, "page_size": 5}),
    ("Page past the end -> empty array, still 200", {"page": 999, "page_size": 5}),
    ("Invalid page clamps to 1", {"page": 0, "page_size": 5}),
    ("Oversized page_size clamps to MAX_PAGE_SIZE", {"page": 1, "page_size": 9999}),
    ("Injection attempt is neutralized", {"page": "1; DROP TABLE users;--", "page_size": 5}),
]


def run_case(label, payload):
    print(f"\n=== {label} ===")
    print(f"Request: {json.dumps(payload)}")

    result = lambda_handler({"body": json.dumps(payload)}, None)
    body = json.loads(result["body"])

    print(f"statusCode: {result['statusCode']}")
    print(json.dumps(body, indent=2))
    return body


def main():
    bodies = {}
    for label, payload in CASES:
        bodies[label] = run_case(label, payload)

    # Checks that need to look across cases rather than at one response.
    print("\n\n=== Cross-case verification ===")

    page1 = bodies["Ticket sample payload"]["data"]
    page2 = bodies["Second page (must not overlap page 1)"]["data"]

    times = [row["updated_time"] for row in page1]
    print(f"page 1 sorted descending: {times == sorted(times, reverse=True)}")

    overlap = {r["user_id"] for r in page1} & {r["user_id"] for r in page2}
    print(f"page 1 / page 2 overlap:  {len(overlap)} (expect 0 -- the ORDER BY tiebreaker)")

    empty = bodies["Page past the end -> empty array, still 200"]
    print(f"past-the-end is empty:    {empty['data'] == []}")

    action_labels = {r["volunteer_review"] for r in page1}
    print(f"review action labels:     {action_labels or '(none - no rows)'}")

    pagination = bodies["Ticket sample payload"]["pagination"]
    print(f"total_records:            {pagination['total_records']} (expect 80)")
    print(f"total_pages:              {pagination['total_pages']} (expect 16)")


if __name__ == "__main__":
    main()
