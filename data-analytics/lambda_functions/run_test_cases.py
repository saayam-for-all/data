#!/usr/bin/env python3
"""
run_test_cases.py

Runs all 16 test cases from "Test Cases and Acceptance Criteria.docx"
against volunteer_application_analytics.lambda_handler(), using the
local Postgres DB (LOCAL_TESTING=true).

Usage:
    Set the LOCAL_DB_* env vars (or rely on the defaults baked into
    get_db_config), then run:

        python run_test_cases.py

Each test case prints:
  - its name and event payload
  - statusCode
  - top-level shape of the response (counts, not full dumps, to keep
    output readable) plus the full JSON if you need to inspect it
"""
import os
import json

os.environ["LOCAL_TESTING"] = "true"
os.environ.setdefault("LOCAL_DB_HOST", "127.0.0.1")
os.environ.setdefault("LOCAL_DB_PORT", "5433")
os.environ.setdefault("LOCAL_DB_NAME", "saayam_local")
os.environ.setdefault("LOCAL_DB_USER", "postgres")
os.environ.setdefault("LOCAL_DB_PASSWORD", "postgres")

from volunteer_application_analytics import lambda_handler

TEST_CASES = [
    {"name": "Test Case 1 - Default response", "event": {}},
    {"name": "Test Case 2 - 7D trend filter", "event": {"time_range": "7D"}},
    {"name": "Test Case 3 - 30D trend filter", "event": {"time_range": "30D"}},
    {"name": "Test Case 4 - 1Y trend filter", "event": {"time_range": "1Y"}},
    {"name": "Test Case 5 - Custom trend date filter (implicit)",
     "event": {"start_date": "2026-01-01", "end_date": "2026-05-31"}},
    {"name": "Test Case 6 - 7D location filter", "event": {"time_range_location": "7D"}},
    {"name": "Test Case 7 - 30D location filter", "event": {"time_range_location": "30D"}},
    {"name": "Test Case 8 - 1Y location filter", "event": {"time_range_location": "1Y"}},
    {"name": "Test Case 9 - Custom location date filter (implicit)",
     "event": {"start_date_location": "2026-01-01", "end_date_location": "2026-05-31"}},
    {"name": "Test Case 10 - Country filter", "event": {"country": "UNITED_STATES_OF_AMERICA"}},
    {"name": "Test Case 11 - Skill filter", "event": {"skill": "TUTORING"}},
    {"name": "Test Case 12 - Country + location date filter",
     "event": {"country": "UNITED_STATES_OF_AMERICA", "time_range_location": "1Y"}},
    {"name": "Test Case 13 - Skill + location date filter",
     "event": {"skill": "TUTORING", "time_range_location": "1Y"}},
    {"name": "Test Case 14 - Country + skill + location date filter",
     "event": {"country": "UNITED_STATES_OF_AMERICA", "skill": "TUTORING", "time_range_location": "1Y"}},
    {"name": "Test Case 15 - Custom location date + country filter",
     "event": {"country": "UNITED_STATES_OF_AMERICA",
               "start_date_location": "2026-01-01", "end_date_location": "2026-05-31"}},
    {"name": "Test Case 16 - Custom location date + skill filter",
     "event": {"skill": "TUTORING",
               "start_date_location": "2026-01-01", "end_date_location": "2026-05-31"}},
    # --- Bonus sanity check (not one of the official 16) ---
    # Tests 10/12/14/15 send country as a country_name-style value
    # ("UNITED_STATES_OF_AMERICA"), but the query filters on country_code
    # (known, pre-approved limitation -- see code comment). This case uses
    # an actual seeded country_code so we can positively confirm the
    # country-filter SQL itself works correctly.
    {"name": "BONUS - Country filter using real country_code (AFG)",
     "event": {"country": "AFG"}},
]


def summarize(body_dict):
    trend = body_dict.get("volunteer_activity_trend", {})
    loc = body_dict.get("volunteers_by_location", [])
    return {
        "new_volunteers_rows": len(trend.get("new_volunteers", [])),
        "active_volunteers_rows": len(trend.get("active_volunteers", [])),
        "total_volunteers_rows": len(trend.get("total_volunteers", [])),
        "location_rows": len(loc),
        "location_sample": loc[:3],
        "trend_sample": trend.get("new_volunteers", [])[:3],
    }


def main():
    results = []
    for case in TEST_CASES:
        print("=" * 80)
        print(case["name"])
        print("event:", json.dumps(case["event"]))
        result = lambda_handler(case["event"], None)
        status = result.get("statusCode")
        print("statusCode:", status)
        try:
            body = json.loads(result.get("body", "{}"))
        except json.JSONDecodeError:
            body = {}
        summary = summarize(body)
        print("summary:", json.dumps(summary, indent=2))
        print()
        results.append((case["name"], status, summary))

    # ---- Final compact summary table (screenshot this for the PR) ----
    print("=" * 80)
    print("FINAL SUMMARY".center(80))
    print("=" * 80)
    header = f'{"Test Case":<48} {"Status":<8} {"Trend rows":<11} {"Loc rows":<9}'
    print(header)
    print("-" * 80)
    all_ok = True
    for name, status, summary in results:
        ok = status == 200
        all_ok = all_ok and ok
        mark = "PASS" if ok else "FAIL"
        short_name = name.replace("Test Case ", "TC").replace("BONUS", "BONUS")
        print(f'{short_name:<48} {mark:<8} {summary["new_volunteers_rows"]:<11} {summary["location_rows"]:<9}')
    print("-" * 80)
    print(f'ALL {len(results)} CASES RETURNED statusCode 200: {"YES" if all_ok else "NO"}')
    print("=" * 80)


if __name__ == "__main__":
    main()
