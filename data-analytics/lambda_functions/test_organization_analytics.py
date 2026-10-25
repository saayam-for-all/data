"""
Manual/integration test runner for organization_analytics.py -- run against the
local Postgres setup (see sql/organizations_local_setup.sql, seeded from the
real data-analytics/sql/organizations.csv + state.csv). Output saved inside
data-analytics/org_alx_dashb_test_output.txt for the PR.

Cases below are the ticket's own "Sample Payloads for Local PR Testing", plus
one extra (#6) that exercises an empty result set: the real seed data's
created_at values top out around 2026-01, so a 7D window against "today"
legitimately returns nothing -- useful proof the API handles empty results
without erroring, which the ticket explicitly calls out as a required test.

For mocked/cursor-based unit tests (no live DB needed), see
test_organization_analytics_unit.py instead.
"""

import json

from organization_analytics import lambda_handler

CASES = [
    (
        "1. Standard Test (30D, daily, no filters)",
        {"time_filter": "30D", "start_date": None, "end_date": None, "group_by": "daily",
         "region": "ALL", "organization_type": "ALL"},
    ),
    (
        "2. Last 12 Months (1Y, monthly, no filters)",
        {"time_filter": "1Y", "start_date": None, "end_date": None, "group_by": "monthly",
         "region": "ALL", "organization_type": "ALL"},
    ),
    (
        "3. Filter by Region (California)",
        {"time_filter": "1Y", "start_date": None, "end_date": None, "group_by": "monthly",
         "region": "California", "organization_type": "ALL"},
    ),
    (
        "4. Filter by Organization Type (non_profit)",
        {"time_filter": "1Y", "start_date": None, "end_date": None, "group_by": "monthly",
         "region": "ALL", "organization_type": "non_profit"},
    ),
    (
        "5. Custom Date Range (2026-01-01 to 2026-06-30)",
        {"time_filter": "CUSTOM", "start_date": "2026-01-01", "end_date": "2026-06-30",
         "group_by": "monthly", "region": "ALL", "organization_type": "ALL"},
    ),
    (
        "6. Empty result set (7D -- real seed data has no orgs created this recently)",
        {"time_filter": "7D", "start_date": None, "end_date": None, "group_by": "daily",
         "region": "ALL", "organization_type": "ALL"},
    ),
]


if __name__ == "__main__":
    for label, payload in CASES:
        print(f"\n=== {label} ===")
        print(f"Request: {json.dumps(payload)}")
        event = {"body": json.dumps(payload)}
        result = lambda_handler(event, None)
        print(f"statusCode: {result['statusCode']}")
        print(json.dumps(json.loads(result["body"]), indent=2))
