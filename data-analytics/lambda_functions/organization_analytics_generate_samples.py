"""Regenerate the sample API responses committed alongside the Lambda.

Runs the handler against local PostgreSQL (LOCAL_DB=true) and writes one JSON
file per scenario, each recording the request, the status code and the response.
Scenarios mirror the "Sample Payloads for Local PR Testing" in issue #228.
"""
import json
import os

os.environ["LOCAL_DB"] = "true"

import organization_analytics as oa

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "organization_analytics_samples")

SCENARIOS = [
    # Full history — the primary showcase (all sections populated)
    ("sample_response_ALL_monthly.json",
     {"time_filter": "ALL", "start_date": None, "end_date": None,
      "group_by": "monthly", "region": "ALL", "organization_type": "ALL"}),
    # Standard test (issue sample payload; demonstrates empty-window handling)
    ("sample_response_30D_daily.json",
     {"time_filter": "30D", "start_date": None, "end_date": None,
      "group_by": "daily", "region": "ALL", "organization_type": "ALL"}),
    # Last 12 months
    ("sample_response_1Y_monthly.json",
     {"time_filter": "1Y", "start_date": None, "end_date": None,
      "group_by": "monthly", "region": "ALL", "organization_type": "ALL"}),
    # Filter by region (region accepts the state name or the state id)
    ("sample_response_ALL_region_texas.json",
     {"time_filter": "ALL", "start_date": None, "end_date": None,
      "group_by": "monthly", "region": "Texas", "organization_type": "ALL"}),
    # Filter by organization type (also demonstrates the CSV display label)
    ("sample_response_ALL_nonprofit.json",
     {"time_filter": "ALL", "start_date": None, "end_date": None,
      "group_by": "monthly", "region": "ALL", "organization_type": "non_profit"}),
    # Custom date range
    ("sample_response_custom_range.json",
     {"time_filter": "CUSTOM", "start_date": "2024-01-01", "end_date": "2024-12-31",
      "group_by": "monthly", "region": "ALL", "organization_type": "ALL"}),
]


def main():
    os.makedirs(SAMPLES_DIR, exist_ok=True)
    for filename, payload in SCENARIOS:
        result = oa.lambda_handler(payload, None)
        document = {
            "request": payload,
            "statusCode": result["statusCode"],
            "response": json.loads(result["body"]),
        }
        path = os.path.join(SAMPLES_DIR, filename)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2)
            handle.write("\n")
        print(f"Wrote {filename} (statusCode={result['statusCode']})")


if __name__ == "__main__":
    main()
