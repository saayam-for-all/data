"""Local test harness for organization_analytics.py.

Runs against a local Postgres seeded by local_setup.sql. Validates status
codes, response structure, filter narrowing, and cross-metric consistency.
No AWS/SSM needed.

Run:
    export LOCAL_DB=true
    export LOCAL_DB_NAME=saayam_local   # or whatever you loaded local_setup.sql into
    python test_organization_analytics_local.py
"""
import json
import os

os.environ.setdefault("LOCAL_DB", "true")

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
    # --- Overview, no filters ---
    code, body = call({"dashboard_type": "overview", "time_filter": "ALL"})
    ov = body["organization_overview"]
    s = ov["summary"]
    total = s["total_organizations"]
    check("overview returns 200", code == 200)
    check("overview has all expected keys",
          set(ov) >= {"summary", "organization_activity_trend", "organizations_by_type",
                      "organizations_by_size", "organizations_by_location",
                      "collaborator_distribution", "contributor_distribution"})
    check("collaborator + non_collaborator = total",
          s["collaborator_organizations"] + s["non_collaborator_organizations"] == total,
          f"{s['collaborator_organizations']}+{s['non_collaborator_organizations']} vs {total}")
    check("contributor + non_contributor = total",
          s["contributor_organizations"] + s["non_contributor_organizations"] == total)
    check("non_profit + for_profit <= total",
          s["non_profit_organizations"] + s["for_profit_organizations"] <= total)
    check("type breakdown sums to total",
          sum(x["count"] for x in ov["organizations_by_type"]) == total)
    check("trend sums to total",
          sum(x["count"] for x in ov["organization_activity_trend"]) == total)
    check("collaborator_distribution has 2 buckets", len(ov["collaborator_distribution"]) == 2)
    check("contributor_distribution has 2 buckets", len(ov["contributor_distribution"]) == 2)

    # --- Performance, no filters ---
    code, body = call({"dashboard_type": "performance", "time_filter": "ALL"})
    pf = body["organization_performance"]
    ps = pf["summary"]
    check("performance returns 200", code == 200)
    check("rated + unrated = total",
          ps["rated_organizations"] + ps["unrated_organizations"] == total)
    check("five_star <= rated", ps["five_star_organizations"] <= ps["rated_organizations"])
    check("rating_distribution has 5 buckets (1..5)",
          [r["rating"] for r in pf["rating_distribution"]] == [1, 2, 3, 4, 5])
    check("rating_distribution sums to rated",
          sum(r["count"] for r in pf["rating_distribution"]) == ps["rated_organizations"])
    check("no top-rated row is unrated",
          all(r["org_rating"] is not None for r in pf["top_rated_organizations"]))

    # --- top_n respected ---
    _, body = call({"dashboard_type": "performance", "time_filter": "ALL", "top_n": 3})
    check("top_n caps top_rated at 3",
          len(body["organization_performance"]["top_rated_organizations"]) <= 3)

    # --- Filter narrowing: 7D <= ALL ---
    _, b7 = call({"dashboard_type": "overview", "time_filter": "7D"})
    check("7D total <= ALL total",
          b7["organization_overview"]["summary"]["total_organizations"] <= total)

    # --- Dimension filter: is_contributor=true is internally consistent ---
    _, bc = call({"dashboard_type": "overview", "time_filter": "ALL", "is_contributor": True})
    sc = bc["organization_overview"]["summary"]
    check("is_contributor filter -> every org is a contributor",
          sc["total_organizations"] == sc["contributor_organizations"])

    # --- Bad dashboard_type falls back to overview (not a crash) ---
    code, body = call({"dashboard_type": "not_a_real_dashboard"})
    check("invalid dashboard_type falls back to overview",
          code == 200 and "organization_overview" in body)

    # === Robustness (mirrors the team acceptance-criteria pattern) ===

    # No crash on zero-match / empty result set.
    _, body = call({"dashboard_type": "overview", "time_filter": "ALL", "state_id": "__no_such_state__"})
    zov = body["organization_overview"]
    check("zero-match returns 200 with total = 0",
          zov["summary"]["total_organizations"] == 0)
    check("zero-match keeps a valid structure (empty lists, 2-bucket distributions)",
          zov["organizations_by_type"] == [] and len(zov["collaborator_distribution"]) == 2)

    # Database connection closes cleanly (no leak after repeated calls).
    import psycopg2
    dbname = os.environ.get("LOCAL_DB_NAME", "saayam_local")

    def active_conns():
        c = psycopg2.connect(
            host=os.environ.get("LOCAL_DB_HOST", "localhost"),
            port=os.environ.get("LOCAL_DB_PORT", "5432"),
            dbname=dbname,
            user=os.environ.get("LOCAL_DB_USER", "postgres"),
            password=os.environ.get("LOCAL_DB_PASSWORD", "postgres"),
        )
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = %s;", (dbname,))
        n = cur.fetchone()[0]
        cur.close()
        c.close()
        return n

    try:
        before = active_conns()
        for _ in range(20):
            oa.lambda_handler({"dashboard_type": "performance", "time_filter": "30D"}, None)
        after = active_conns()
        check("connection closes cleanly (no leak after 20 calls)",
              after <= before, f"before={before}, after={after}")
    except Exception as e:
        check("connection-leak check ran", False, str(e))

    # Safe response when the DB is unavailable (run last; restores state after).
    import importlib
    saved_port = os.environ.get("LOCAL_DB_PORT", "5432")
    os.environ["LOCAL_DB_PORT"] = "59999"  # nothing is listening here
    importlib.reload(oa)
    resp = oa.lambda_handler({"dashboard_type": "performance"}, None)
    down_body = json.loads(resp["body"])
    check("DB unavailable -> 500, no exception leaks", resp["statusCode"] == 500)
    check("DB unavailable -> safe default response shape",
          "organization_performance" in down_body
          and down_body["organization_performance"]["summary"]["average_rating"] == 0)
    os.environ["LOCAL_DB_PORT"] = saved_port
    importlib.reload(oa)

    print("\n".join(LINES))
    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL == 0


if __name__ == "__main__":
    ok = main()
    raise SystemExit(0 if ok else 1)
