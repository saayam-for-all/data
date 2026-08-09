"""Regenerate the sample API responses committed alongside the Lambda.

Runs the handler against local PostgreSQL (LOCAL_DB=true) and writes one JSON
file per scenario, each recording the request, the status code and the response.
"""
import json
import os

os.environ["LOCAL_DB"] = "true"

import organization_analytics as oa

SCENARIOS = [
    ("sample_response_overview_ALL_monthly.json",
     {"dashboard_type": "overview", "time_filter": "ALL", "group_by": "monthly"}),
    ("sample_response_overview_1Y_daily.json",
     {"dashboard_type": "overview", "time_filter": "1Y", "group_by": "daily"}),
    ("sample_response_performance_ALL.json",
     {"dashboard_type": "performance", "time_filter": "ALL"}),
    # Also demonstrates that the CSV display label is accepted for org_type.
    ("sample_response_performance_filtered_nonprofit_large.json",
     {"dashboard_type": "performance", "time_filter": "ALL",
      "org_type": "Non-Profit", "org_size": "Large"}),
]


def main():
    for filename, payload in SCENARIOS:
        result = oa.lambda_handler(payload, None)
        document = {
            "request": payload,
            "statusCode": result["statusCode"],
            "response": json.loads(result["body"])
        }
        with open(filename, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2)
            handle.write("\n")
        print(f"Wrote {filename} (statusCode={result['statusCode']})")


if __name__ == "__main__":
    main()
