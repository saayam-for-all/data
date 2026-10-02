"""Local test harness for organization_analytics.py.

Runs against local PostgreSQL (LOCAL_DB=true). Validates status codes, the flat
single-endpoint response structure the Organization Dashboard expects, filter
behavior, and cross-metric consistency.
"""
import json
import os
import re

os.environ["LOCAL_DB"] = "true"

import organization_analytics as oa

PASS, FAIL = 0, 0
RESULTS = []

SECTION_KEYS = [
    "summary",
    "growth_trend",
    "organizations_by_location",
    "organizations_by_size",
    "collaborator_vs_contributor",
    "rating_distribution",
    "organization_type_distribution",
]


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


def probe_dataset():
    """Pick filter values that exist in whatever dataset is loaded locally.

    Keeps the suite valid against both the synthetic seed and the real
    organizations.csv / state.csv extracts.
    """
    conn = oa.get_db_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT o.state_id, s.state_name,
               REPLACE(LOWER(o.org_size::text), '-', '_'), o.org_rating
        FROM {oa.SCHEMA_NAME}.organizations o
        JOIN {oa.SCHEMA_NAME}.state s ON o.state_id = s.state_id
        WHERE o.org_size IS NOT NULL
          AND o.org_rating IS NOT NULL
        ORDER BY o.org_id
        LIMIT 1;
    """)
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row is None:
        raise SystemExit("No usable rows in the local organizations table — load data first.")
    return row


def main():
    sample_state_id, sample_state_name, sample_size, sample_rating = probe_dataset()
    print(f"Dataset probe: state_id={sample_state_id} ({sample_state_name}), "
          f"size={sample_size}, rating={sample_rating}\n")

    # 1. No filters — full structure + KPI consistency
    code, body = call({"time_filter": "ALL", "group_by": "monthly"})
    check("baseline: 200 OK", code == 200)
    check("baseline: all seven sections present",
          all(k in body for k in SECTION_KEYS),
          f"missing={[k for k in SECTION_KEYS if k not in body]}")
    s = body["summary"]
    total = s["total_organizations"]
    check("summary: collaborators <= total", s["total_collaborators"] <= total)
    check("summary: contributors <= total", s["total_contributors"] <= total)
    check("summary: 0 <= average_org_rating <= 5", 0 <= s["average_org_rating"] <= 5)

    # 2. Growth trend — cumulative, ends at the summary total
    trend = body["growth_trend"]
    check("growth_trend: cumulative organizations non-decreasing",
          all(trend[i]["total_organizations"] <= trend[i + 1]["total_organizations"]
              for i in range(len(trend) - 1)))
    check("growth_trend: final cumulative total matches summary",
          bool(trend) and trend[-1]["total_organizations"] == total)
    check("growth_trend: final cumulative collaborators matches summary",
          bool(trend) and trend[-1]["total_collaborators"] == s["total_collaborators"])

    # 3. Location — counts sum to total, percentages ~100
    locs = body["organizations_by_location"]
    check("location: organization_count sums to total",
          sum(r["organization_count"] for r in locs) == total)
    check("location: rows carry state_id, state_name, count, percentage, cities",
          all({"state_id", "state_name", "organization_count", "percentage", "cities"} <= set(r) for r in locs))
    check("location: each state's city counts sum to its organization_count",
          all(sum(c["organization_count"] for c in r["cities"]) == r["organization_count"] for r in locs))
    check("location: percentages sum to ~100",
          abs(sum(r["percentage"] for r in locs) - 100) <= 1.0 if locs else True)

    # 4. Size — buckets sum to total
    sizes = body["organizations_by_size"]
    check("size: organization_count sums to total",
          sum(r["organization_count"] for r in sizes) == total)

    # 5. Collaborator vs contributor
    cvc = body["collaborator_vs_contributor"]
    by_type = {r["type"]: r for r in cvc}
    check("collab_vs_contrib: exactly collaborator + contributor rows",
          set(by_type) == {"collaborator", "contributor"})
    check("collab_vs_contrib: counts match summary",
          by_type["collaborator"]["organization_count"] == s["total_collaborators"] and
          by_type["contributor"]["organization_count"] == s["total_contributors"])
    pct_sum = sum(r["percentage"] for r in cvc)
    check("collab_vs_contrib: percentages sum to ~100 (or 0 when both empty)",
          abs(pct_sum - 100) <= 0.2 or pct_sum == 0)

    # 6. Rating distribution — always buckets 1-5
    rd = body["rating_distribution"]
    check("rating: buckets 1-5 always present",
          [r["rating"] for r in rd] == [1, 2, 3, 4, 5])
    check("rating: organization_count sums to rated organizations (<= total)",
          sum(r["organization_count"] for r in rd) <= total)

    # 7. Type distribution — per-period rows, total == for_profit + non_profit
    otd = body["organization_type_distribution"]
    check("type_dist: each row total = for_profit + non_profit",
          all(r["total"] == r["for_profit"] + r["non_profit"] for r in otd))
    check("type_dist: summed totals do not exceed org total",
          sum(r["total"] for r in otd) <= total)

    # 8. Time filters monotonic
    totals = {}
    for tf in ["7D", "30D", "1Y", "ALL"]:
        code, body_tf = call({"time_filter": tf})
        totals[tf] = body_tf["summary"]["total_organizations"]
        check(f"time_filter {tf}: 200 OK", code == 200, f"total={totals[tf]}")
    check("time filters monotonic: 7D <= 30D <= 1Y <= ALL",
          totals["7D"] <= totals["30D"] <= totals["1Y"] <= totals["ALL"])

    # 9. CUSTOM date range
    code, body = call({"time_filter": "CUSTOM",
                       "start_date": "2025-01-01", "end_date": "2025-12-31"})
    check("CUSTOM range: 200 OK", code == 200,
          f"total={body['summary']['total_organizations']}")
    code, _ = call({"time_filter": "CUSTOM", "start_date": "2025-01-01"})
    check("CUSTOM without end_date: 400", code == 400)
    code, _ = call({"time_filter": "CUSTOM", "start_date": "01-01-2025", "end_date": "2025-12-31"})
    check("CUSTOM with non-ISO date: 400", code == 400)
    code, _ = call({"time_filter": "CUSTOM", "start_date": "2025-12-31", "end_date": "2025-01-01"})
    check("CUSTOM with start_date after end_date: 400", code == 400)

    # 10. organization_type filter (accepts enum and display label)
    code, body = call({"time_filter": "ALL", "organization_type": "non_profit"})
    otd_np = body["organization_type_distribution"]
    check("filter organization_type=non_profit: no for_profit counts",
          all(r["for_profit"] == 0 for r in otd_np))
    code, body_label = call({"time_filter": "ALL", "organization_type": "Non-Profit"})
    check("filter accepts the CSV display label 'Non-Profit'",
          body_label["summary"] == body["summary"])

    # 11. region filter (by state name and by state id)
    code, body = call({"time_filter": "ALL", "region": sample_state_name})
    locs = body["organizations_by_location"]
    check(f"filter region={sample_state_name}: only that state returned",
          len(locs) >= 1 and all(l["state_name"] == sample_state_name for l in locs))
    code, body_id = call({"time_filter": "ALL", "region": sample_state_id})
    check("filter region by state_id matches region by state_name",
          body_id["summary"] == body["summary"])
    code, body_all = call({"time_filter": "ALL", "region": "ALL"})
    check("region=ALL behaves as no region filter",
          body_all["summary"]["total_organizations"] == total)

    # 12. group_by variants populate the time-series sections
    for gb in ["daily", "weekly", "monthly", "yearly"]:
        code, body = call({"time_filter": "1Y", "group_by": gb})
        check(f"group_by {gb}: 200 OK with trend + type-dist rows",
              code == 200 and len(body["growth_trend"]) >= 1 and
              len(body["organization_type_distribution"]) >= 1,
              f"trend={len(body['growth_trend'])}")

    # 13. Invalid inputs sanitized to defaults
    code, body = call({"time_filter": "INVALID", "group_by": "hourly",
                       "region": "ALL", "organization_type": "ALL"})
    check("invalid filter values sanitized: 200", code == 200)

    # 14. API-Gateway-style event (stringified body)
    code, body = call({"body": json.dumps({"time_filter": "30D", "group_by": "daily"})})
    check("API Gateway string body parsed: 200", code == 200)

    # 15. No AWS Parameter Store / SSM anywhere in the source, no hard-coded path
    source = open(oa.__file__, encoding="utf-8").read()
    check("no boto3 / SSM import in source",
          "boto3" not in source and "ssm" not in source.lower())
    absolute_path_literals = re.findall(r"""['"]/[a-z0-9_\-/]*saayam[a-z0-9_\-/]*['"]""",
                                        source, re.IGNORECASE)
    check("no Parameter Store path hard-coded in source",
          absolute_path_literals == [], f"found {absolute_path_literals}")

    # 16. A failing metric must not cascade into the metrics that follow it
    def failing_fetch(cursor, *_args):
        cursor.execute("SELECT 1 / 0")
        return []

    original_by_size = oa.fetch_organizations_by_size
    oa.fetch_organizations_by_size = failing_fetch
    try:
        code, body = call({"time_filter": "ALL"})
        check("failing metric: request still 200", code == 200)
        check("failing metric: its own section falls back to the safe default",
              body["organizations_by_size"] == [])
        check("failing metric: later queries on the same connection still succeed",
              body["summary"]["total_organizations"] == total and
              sum(r["organization_count"] for r in body["organizations_by_location"]) == total)
    finally:
        oa.fetch_organizations_by_size = original_by_size

    # 17. Graceful degradation when the organizations table has no is_contributor column
    original_detector = oa.has_contributor_column
    oa.has_contributor_column = lambda cursor: False
    try:
        code, body = call({"time_filter": "ALL"})
        s_nc = body["summary"]
        check("no is_contributor column: still 200", code == 200)
        check("no is_contributor column: non-contributor metrics unaffected",
              s_nc["total_organizations"] == total and
              s_nc["total_collaborators"] == s["total_collaborators"])
        check("no is_contributor column: contributor metrics zero",
              s_nc["total_contributors"] == 0 and
              next(r["organization_count"] for r in body["collaborator_vs_contributor"]
                   if r["type"] == "contributor") == 0)
        check("no is_contributor column: schema note returned",
              any("is_contributor" in note for note in body.get("schema_notes", [])))
    finally:
        oa.has_contributor_column = original_detector

    print("\n".join(RESULTS))
    print(f"\n{PASS} passed, {FAIL} failed out of {PASS + FAIL} checks.")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
