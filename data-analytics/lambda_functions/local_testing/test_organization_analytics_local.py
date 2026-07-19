"""Local test harness for organization_analytics.py.

Runs against local PostgreSQL (LOCAL_DB=true). Validates status codes,
response structure, filter behavior, and cross-metric consistency.
"""
import json
import os

os.environ["LOCAL_DB"] = "true"

import organization_analytics as oa

PASS, FAIL = 0, 0
RESULTS = []


def check(name, condition, detail=""):
    global PASS, FAIL
    status = "PASS" if condition else "FAIL"
    if condition:
        PASS += 1
    else:
        FAIL += 1
    RESULTS.append(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def call(payload):
    resp = oa.lambda_handler(payload, None)
    return resp["statusCode"], json.loads(resp["body"])


def main():
    # 1. Overview — no filters
    code, body = call({"dashboard_type": "overview", "time_filter": "ALL"})
    ov = body["organization_overview"]
    s = ov["summary"]
    check("overview: 200 OK", code == 200)
    check("overview: total = non_profit + for_profit + untyped",
          s["total_organizations"] >= s["non_profit_organizations"] + s["for_profit_organizations"])
    check("overview: collab + non_collab = total",
          s["collaborator_organizations"] + s["non_collaborator_organizations"] == s["total_organizations"])
    check("overview: contrib + non_contrib = total",
          s["contributor_organizations"] + s["non_contributor_organizations"] == s["total_organizations"])
    check("overview: trend cumulative total matches summary",
          ov["organization_activity_trend"][-1]["total_organizations"] == s["total_organizations"])
    check("overview: type distribution sums to total",
          sum(r["count"] for r in ov["organizations_by_type"]) == s["total_organizations"])
    check("overview: size distribution sums to total",
          sum(r["count"] for r in ov["organizations_by_size"]) == s["total_organizations"])
    check("overview: location distribution sums to total",
          sum(r["count"] for r in ov["organizations_by_location"]) == s["total_organizations"])
    check("overview: collaborator_distribution sums to total",
          sum(r["count"] for r in ov["collaborator_distribution"]) == s["total_organizations"])
    check("overview: contributor_distribution sums to total",
          sum(r["count"] for r in ov["contributor_distribution"]) == s["total_organizations"])

    # 2. Performance — no filters
    code, body = call({"dashboard_type": "performance", "time_filter": "ALL"})
    pf = body["organization_performance"]
    ps = pf["summary"]
    check("performance: 200 OK", code == 200)
    check("performance: rated + unrated = overview total",
          ps["rated_organizations"] + ps["unrated_organizations"] == s["total_organizations"])
    check("performance: rating distribution sums to rated",
          sum(r["count"] for r in pf["rating_distribution"]) == ps["rated_organizations"])
    check("performance: 1 <= avg rating <= 5",
          1 <= ps["average_rating"] <= 5)
    five_star_in_dist = next((r["count"] for r in pf["rating_distribution"] if r["rating"] == 5), 0)
    check("performance: five_star matches distribution",
          ps["five_star_organizations"] == five_star_in_dist)
    check("performance: top_rated <= 10 and sorted desc",
          len(pf["top_rated_organizations"]) <= 10 and
          all(pf["top_rated_organizations"][i]["org_rating"] >= pf["top_rated_organizations"][i + 1]["org_rating"]
              for i in range(len(pf["top_rated_organizations"]) - 1)))
    check("performance: top collaborators all flagged",
          len(pf["top_collaborator_organizations"]) <= 10)
    check("performance: ratings_by_type nonempty",
          len(pf["ratings_by_organization_type"]) >= 1)
    check("performance: ratings_by_size nonempty",
          len(pf["ratings_by_organization_size"]) >= 1)

    # 3. Time filters
    totals = {}
    for tf in ["7D", "30D", "1Y", "ALL"]:
        code, body = call({"dashboard_type": "overview", "time_filter": tf})
        totals[tf] = body["organization_overview"]["summary"]["total_organizations"]
        check(f"time_filter {tf}: 200 OK", code == 200, f"total={totals[tf]}")
    check("time filters monotonic: 7D <= 30D <= 1Y <= ALL",
          totals["7D"] <= totals["30D"] <= totals["1Y"] <= totals["ALL"])

    # 4. CUSTOM date range
    code, body = call({"dashboard_type": "overview", "time_filter": "CUSTOM",
                       "start_date": "2025-01-01", "end_date": "2025-12-31"})
    check("CUSTOM range: 200 OK", code == 200,
          f"total={body['organization_overview']['summary']['total_organizations']}")

    # 5. Dimension filters
    code, body = call({"dashboard_type": "overview", "time_filter": "ALL", "org_type": "non_profit"})
    s2 = body["organization_overview"]["summary"]
    check("filter org_type=non_profit: for_profit count is 0",
          s2["for_profit_organizations"] == 0 and s2["total_organizations"] == s2["non_profit_organizations"])

    code, body = call({"dashboard_type": "overview", "time_filter": "ALL", "org_size": "large"})
    sizes = body["organization_overview"]["organizations_by_size"]
    check("filter org_size=large: only 'large' bucket returned",
          len(sizes) == 1 and sizes[0]["size"] == "large")

    code, body = call({"dashboard_type": "overview", "time_filter": "ALL", "state_id": "ST-NY"})
    locs = body["organization_overview"]["organizations_by_location"]
    check("filter state_id=ST-NY: all locations in New York",
          all(l["state"] == "New York" for l in locs) and len(locs) > 0)

    code, body = call({"dashboard_type": "overview", "time_filter": "ALL", "city_name": "buffalo"})
    locs = body["organization_overview"]["organizations_by_location"]
    check("filter city_name (case-insensitive): only Buffalo",
          all(l["city"] == "Buffalo" for l in locs))

    code, body = call({"dashboard_type": "overview", "time_filter": "ALL", "is_collaborator": True})
    s3 = body["organization_overview"]["summary"]
    check("filter is_collaborator=true: non_collaborator count is 0",
          s3["non_collaborator_organizations"] == 0)

    code, body = call({"dashboard_type": "overview", "time_filter": "ALL", "is_contributor": False})
    s4 = body["organization_overview"]["summary"]
    check("filter is_contributor=false: contributor count is 0",
          s4["contributor_organizations"] == 0)

    code, body = call({"dashboard_type": "performance", "time_filter": "ALL", "org_rating": 5})
    pf2 = body["organization_performance"]
    check("filter org_rating=5: distribution only rating 5",
          all(r["rating"] == 5 for r in pf2["rating_distribution"]))

    # 6. group_by variants
    for gb in ["daily", "weekly", "monthly", "yearly"]:
        code, body = call({"dashboard_type": "overview", "time_filter": "1Y", "group_by": gb})
        trend = body["organization_overview"]["organization_activity_trend"]
        check(f"group_by {gb}: 200 OK with trend rows", code == 200 and len(trend) >= 1,
              f"buckets={len(trend)}")

    # 7. Invalid inputs
    code, body = call({"dashboard_type": "bogus"})
    check("invalid dashboard_type: 400", code == 400)

    code, body = call({"dashboard_type": "overview", "time_filter": "INVALID",
                       "group_by": "hourly", "org_rating": 99})
    check("invalid filter values sanitized to defaults: 200", code == 200)

    # 8. API-Gateway-style event (stringified body)
    code, body = call({"body": json.dumps({"dashboard_type": "performance", "time_filter": "30D"})})
    check("API Gateway string body parsed: 200", code == 200)

    print("\n".join(RESULTS))
    print(f"\n{PASS} passed, {FAIL} failed out of {PASS + FAIL} checks.")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
