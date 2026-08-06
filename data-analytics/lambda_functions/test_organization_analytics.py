"""
Manual test runner for organization_analytics.py -- run against the local
Postgres setup (see sql/organizations_local_setup.sql)
Output saved inside (data-analytics/org_alx_dashb_test_output.txt)
"""

import json
from datetime import date, timedelta

from organization_analytics import lambda_handler

CASES = [
    ("1. Overview - defaults (no filters)", {}),
    ("2. Overview - time_filter=7D", {"time_filter": "7D"}),
    ("3. Overview - time_filter=1Y, group_by=yearly", {"time_filter": "1Y", "group_by": "yearly"}),
    ("4. Overview - time_filter=ALL, group_by=weekly", {"time_filter": "ALL", "group_by": "weekly"}),
    ("5. Overview - org_type=for_profit", {"time_filter": "ALL", "org_type": "for_profit"}),
    (
        "6. Overview - org_size=large + state_id=CA",
        {"time_filter": "ALL", "org_size": "large", "state_id": "CA"},
    ),
    (
        "7. Overview - city_name=chicago (lowercase, tests ILIKE)",
        {"time_filter": "ALL", "city_name": "chicago"},
    ),
    (
        "8. Overview - is_collaborator=false + is_contributor=true",
        {"time_filter": "ALL", "is_collaborator": False, "is_contributor": True},
    ),
    (
        "9. Performance - org_rating=5",
        {"dashboard_type": "performance", "time_filter": "ALL", "org_rating": 5},
    ),
    (
        "10. Performance - time_filter=CUSTOM (last 30 days) + is_collaborator=true",
        {
            "dashboard_type": "performance",
            "time_filter": "CUSTOM",
            # Computed relative to today (not hardcoded) for the same reason the seed
            # data in organizations_local_setup.sql uses relative intervals -- a fixed
            # date range goes stale the moment "today" moves past it.
            "start_date": str(date.today() - timedelta(days=30)),
            "end_date": str(date.today()),
            "is_collaborator": True,
        },
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
