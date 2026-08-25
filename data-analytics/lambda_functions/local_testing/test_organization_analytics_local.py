"""Local test harness for organization_analytics.py (v2 spec: single endpoint,
flat response). Run against a local Postgres loaded with the real sample CSVs
(organizations.csv, state.csv) from data-analytics/sql/.

Run:
    export DB_HOST=... DB_PORT=... DB_NAME=... DB_USER=... DB_PASSWORD=...
    export DB_SCHEMA=virginia_dev_saayam_rdbms
    python test_organization_analytics_local.py
"""
import json

import organization_analytics as oa

PASS = FAIL = 0
LINES = []


def check(name, condition, detail=""):
    global PASS, FAIL
    ok = bool(condition)
    PASS += ok
    FAIL += (not ok)
    LINES.append(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def call(payload):
    resp = oa.lambda_handler(payload, None)
    return resp["statusCode"], json.loads(resp["body"])


def main():
    # --- Default / ALL ---
    code, body = call({"time_filter": "ALL", "region": "ALL", "organization_type": "ALL"})
    total = body["summary"]["total_organizations"]
    check("returns 200", code == 200)
    check("has all required top-level keys",
          set(body) >= {"summary", "growth_trend", "organizations_by_location",
                        "organizations_by_size", "collaborator_vs_contributor",
                        "rating_distribution", "organization_type_distribution"})
    check("summary has all 4 KPI fields",
          set(body["summary"]) == {"total_organizations", "total_collaborators",
                                    "total_contributors", "average_org_rating"})

    # --- Region filter narrows and is consistent ---
    _, ca = call({"time_filter": "ALL", "region": "California"})
    check("region filter narrows total (<=)", ca["summary"]["total_organizations"] <= total)
    check("region filter: every location row matches CA",
          all(l["state_id"] == "CA" for l in ca["organizations_by_location"]))

    # --- organization_type filter narrows and only shows that type in trend ---
    _, np = call({"time_filter": "ALL", "organization_type": "non_profit"})
    check("organization_type filter narrows total (<=)", np["summary"]["total_organizations"] <= total)
    check("organization_type filter: type distribution shows only non_profit",
          all(p["for_profit"] == 0 for p in np["organization_type_distribution"]))

    # --- collaborator_vs_contributor is NOT mutually exclusive (can exceed structure of a simple split) ---
    cvc = {row["type"]: row["organization_count"] for row in body["collaborator_vs_contributor"]}
    check("collaborator_vs_contributor has both types", set(cvc) == {"collaborator", "contributor"})
    check("collaborator/contributor counts match summary totals",
          cvc["collaborator"] == body["summary"]["total_collaborators"]
          and cvc["contributor"] == body["summary"]["total_contributors"])

    # --- rating_distribution: 5 buckets, NULL-safe (doesn't error, doesn't inflate buckets) ---
    check("rating_distribution has exactly 5 buckets (1..5)",
          [r["rating"] for r in body["rating_distribution"]] == [1, 2, 3, 4, 5])
    rated_sum = sum(r["organization_count"] for r in body["rating_distribution"])
    check("rating_distribution sum <= total (NULL ratings safely excluded)", rated_sum <= total)

    # --- organizations_by_size percentages/labels ---
    check("organizations_by_size values are lowercase (small/medium/large)",
          all(row["org_size"] in ("small", "medium", "large") for row in body["organizations_by_size"]))

    # --- organization_type_distribution is a per-period trend, each row sums correctly ---
    check("organization_type_distribution rows: for_profit + non_profit == total",
          all(p["for_profit"] + p["non_profit"] == p["total"] for p in body["organization_type_distribution"]))

    # --- group_by variants all return without error ---
    for gb in ("daily", "weekly", "monthly", "yearly"):
        c, b = call({"time_filter": "ALL", "group_by": gb})
        check(f"group_by={gb} returns 200 with a non-crashing trend",
              c == 200 and isinstance(b["growth_trend"], list))

    # --- CUSTOM date range ---
    c, custom = call({"time_filter": "CUSTOM", "start_date": "2026-01-01", "end_date": "2026-06-30"})
    check("CUSTOM time_filter returns 200", c == 200)
    check("CUSTOM total <= ALL total", custom["summary"]["total_organizations"] <= total)

    # --- Zero-match region: no crash, clean empty structure ---
    c, zero = call({"time_filter": "ALL", "region": "NoSuchPlaceAtAll"})
    check("zero-match region returns 200 with total = 0",
          c == 200 and zero["summary"]["total_organizations"] == 0)
    check("zero-match region keeps valid structure (empty lists)",
          zero["organizations_by_location"] == [] and zero["growth_trend"] == [])

    # --- DB unavailable: safe response, no exception leak ---
    import os
    saved = os.environ.get("DB_PORT")
    os.environ["DB_PORT"] = "59999"
    import importlib
    importlib.reload(oa)
    resp = oa.lambda_handler({"time_filter": "ALL"}, None)
    down = json.loads(resp["body"])
    check("DB unavailable -> 500, no exception leaks", resp["statusCode"] == 500)
    check("DB unavailable -> safe default response shape",
          "summary" in down and down["summary"]["average_org_rating"] == 0)
    if saved is not None:
        os.environ["DB_PORT"] = saved
    importlib.reload(oa)

    # --- No AWS Parameter Store / SSM anywhere in the module source ---
    import inspect
    src = inspect.getsource(oa).lower()
    check("no functional SSM/boto3 usage (only explanatory comments, if any)",
          "boto3." not in src and "get_parameter(" not in src)

    print("\n".join(LINES))
    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL == 0


if __name__ == "__main__":
    ok = main()
    raise SystemExit(0 if ok else 1)
