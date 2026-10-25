"""
Local test suite for organization_analytics.py (mock-data version).

Run directly:
    python test_organization_analytics.py

What it does:
  1. Loads the mock CSV data (mock_data/organizations.csv) — no AWS, SSM,
     or real DB connection involved, per review feedback on issue #228.
  2. Runs both dashboards through several filter scenarios (unfiltered,
     each time_filter, a few common-filter combinations, and a "both"
     dashboard_type call).
  3. Runs sanity assertions against the computed metrics (e.g. type/size/
     collaborator/rating breakdowns sum back to the scenario's total).
  4. Writes a human-readable results file to test_results.md with the
     full JSON response for every scenario plus a PASS/FAIL summary.
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from organization_analytics import (  # noqa: E402
    load_mock_data,
    get_organization_overview,
    get_organization_performance,
    lambda_handler,
)

RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_results.md")

SCENARIOS = [
    ("Overview - ALL time (unfiltered)", {"dashboard_type": "overview", "time_filter": "ALL", "group_by": "monthly"}),
    ("Overview - 7D", {"dashboard_type": "overview", "time_filter": "7D", "group_by": "daily"}),
    ("Overview - 30D", {"dashboard_type": "overview", "time_filter": "30D", "group_by": "daily"}),
    ("Overview - 1Y, grouped monthly", {"dashboard_type": "overview", "time_filter": "1Y", "group_by": "monthly"}),
    ("Overview - filtered (Non-Profit)", {
        "dashboard_type": "overview", "org_type": "Non-Profit", "time_filter": "ALL",
    }),
    ("Overview - filtered (is_collaborator=true)", {
        "dashboard_type": "overview", "is_collaborator": True, "time_filter": "ALL",
    }),
    ("Overview - filtered (is_contributor=true)", {
        "dashboard_type": "overview", "is_contributor": True, "time_filter": "ALL",
    }),
    ("Overview - CUSTOM date range", {
        "dashboard_type": "overview", "time_filter": "CUSTOM",
        "start_date": "2025-01-01", "end_date": "2025-12-31",
    }),
    ("Performance - ALL", {"dashboard_type": "performance", "time_filter": "ALL"}),
    ("Performance - filtered (org_rating=5)", {"dashboard_type": "performance", "org_rating": 5, "time_filter": "ALL"}),
    ("Performance - filtered (org_size=Large)", {"dashboard_type": "performance", "org_size": "Large", "time_filter": "ALL"}),
    ("Both dashboards - ALL", {"dashboard_type": "both", "time_filter": "ALL", "group_by": "monthly"}),
]


def run_scenario(org_df, filters):
    dashboard_type = filters.get("dashboard_type", "overview")
    result = {}
    if dashboard_type in ("overview", "both"):
        result["organization_overview"] = get_organization_overview(org_df, filters)
    if dashboard_type in ("performance", "both"):
        result["organization_performance"] = get_organization_performance(org_df, filters)
    return result


def check_overview_invariants(result, label, failures):
    overview = result.get("organization_overview")
    if overview is None:
        return
    summary = overview["summary"]
    total = summary["total_organizations"]

    if summary["non_profit_organizations"] + summary["for_profit_organizations"] != total:
        failures.append(f"[{label}] org_type breakdown does not sum to total_organizations")

    if summary["collaborator_organizations"] + summary["non_collaborator_organizations"] != total:
        failures.append(f"[{label}] collaborator breakdown does not sum to total_organizations")

    if summary["contributor_organizations"] + summary["non_contributor_organizations"] != total:
        failures.append(f"[{label}] contributor breakdown does not sum to total_organizations")

    for key in ("organizations_by_type", "organizations_by_size", "organizations_by_location", "organization_activity_trend"):
        subtotal = sum(row["count"] for row in overview[key])
        if subtotal != total:
            failures.append(f"[{label}] {key} does not sum to total_organizations ({subtotal} != {total})")


def check_performance_invariants(result, label, failures):
    performance = result.get("organization_performance")
    if performance is None:
        return
    summary = performance["summary"]

    if summary["rated_organizations"] + summary["unrated_organizations"] == 0 and summary["average_rating"] != 0:
        failures.append(f"[{label}] average_rating should be 0 when there are no rated organizations")

    dist_sum = sum(row["count"] for row in performance["rating_distribution"])
    if dist_sum != summary["rated_organizations"] + summary["unrated_organizations"]:
        failures.append(f"[{label}] rating_distribution does not sum to rated+unrated organizations")

    for row in performance["top_rated_organizations"]:
        if row["org_rating"] is None:
            failures.append(f"[{label}] top_rated_organizations contains an unrated organization")


def main():
    org_df = load_mock_data()

    lines = []
    lines.append("# Organization Analytics API — Local Test Results (mock data)\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"Mock organizations loaded: **{len(org_df)}** rows from `mock_data/organizations.csv`\n")
    lines.append(
        "No AWS/SSM/Postgres connection is used anywhere in this test run — "
        "all data comes from the mock CSV.\n"
    )

    all_failures = []

    for label, filters in SCENARIOS:
        result = run_scenario(org_df, filters)
        check_overview_invariants(result, label, all_failures)
        check_performance_invariants(result, label, all_failures)

        lines.append(f"## Scenario: {label}\n")
        lines.append(f"Request filters:\n```json\n{json.dumps(filters, indent=2)}\n```\n")
        lines.append(f"Response:\n```json\n{json.dumps(result, indent=2, default=str)}\n```\n")

    handler_event = {"body": json.dumps({"dashboard_type": "both", "time_filter": "ALL"})}
    handler_response = lambda_handler(handler_event, None)
    if handler_response["statusCode"] != 200:
        all_failures.append("lambda_handler did not return statusCode 200 for a valid 'both' request")
    lines.append("## Scenario: lambda_handler(event) end-to-end\n")
    lines.append(f"Event:\n```json\n{json.dumps(handler_event, indent=2)}\n```\n")
    lines.append(f"statusCode: {handler_response['statusCode']}\n")
    lines.append(f"Response body:\n```json\n{json.dumps(json.loads(handler_response['body']), indent=2)}\n```\n")

    invalid_response = lambda_handler({"body": json.dumps({"dashboard_type": "bogus"})}, None)
    if invalid_response["statusCode"] != 400:
        all_failures.append("lambda_handler did not return statusCode 400 for an invalid dashboard_type")
    lines.append("## Scenario: lambda_handler(event) with invalid dashboard_type\n")
    lines.append(f"statusCode: {invalid_response['statusCode']}\n")
    lines.append(f"Response body:\n```json\n{json.dumps(json.loads(invalid_response['body']), indent=2)}\n```\n")

    lines.append("## Summary\n")
    if all_failures:
        lines.append(f"**{len(all_failures)} check(s) FAILED:**\n")
        for failure in all_failures:
            lines.append(f"- ❌ {failure}")
    else:
        lines.append(f"✅ All {len(SCENARIOS) + 2} scenarios ran and all invariant checks passed.")

    with open(RESULTS_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Wrote results for {len(SCENARIOS) + 2} scenarios to {RESULTS_PATH}")
    if all_failures:
        print(f"\n{len(all_failures)} CHECK(S) FAILED:")
        for failure in all_failures:
            print(f"  - {failure}")
        sys.exit(1)
    else:
        print("All checks passed.")


if __name__ == "__main__":
    main()
