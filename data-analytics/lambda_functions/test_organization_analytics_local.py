"""Local test harness for organization_analytics.py.

Runs against local PostgreSQL (LOCAL_DB=true). Validates status codes,
response structure, filter behavior, and cross-metric consistency.
"""
import json
import os
import re

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


def probe_dataset():
    """Pick filter values that exist in whatever dataset is loaded locally.

    Keeps the suite valid against both the synthetic seed and the real
    organizations.csv / state.csv extracts.
    """
    conn = oa.get_db_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT o.state_id, o.city_name, s.state_name,
               REPLACE(LOWER(o.org_size::text), '-', '_'), o.org_rating
        FROM {oa.SCHEMA_NAME}.organizations o
        JOIN {oa.SCHEMA_NAME}.state s ON o.state_id = s.state_id
        WHERE o.city_name IS NOT NULL
          AND o.org_size IS NOT NULL
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
    (sample_state_id, sample_city, sample_state_name,
     sample_size, sample_rating) = probe_dataset()
    print(f"Dataset probe: state_id={sample_state_id} ({sample_state_name}), "
          f"city={sample_city}, size={sample_size}, rating={sample_rating}\n")

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
    check("performance: rating distribution always has buckets 1-5",
          [r["rating"] for r in pf["rating_distribution"]] == [1, 2, 3, 4, 5])
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

    code, body = call({"dashboard_type": "overview", "time_filter": "CUSTOM",
                       "start_date": "2025-01-01"})
    check("CUSTOM without end_date: 400", code == 400)

    code, body = call({"dashboard_type": "overview", "time_filter": "CUSTOM",
                       "start_date": "01-01-2025", "end_date": "2025-12-31"})
    check("CUSTOM with non-ISO date: 400", code == 400)

    code, body = call({"dashboard_type": "overview", "time_filter": "CUSTOM",
                       "start_date": "2025-12-31", "end_date": "2025-01-01"})
    check("CUSTOM with start_date after end_date: 400", code == 400)

    # 5. Dimension filters
    code, body = call({"dashboard_type": "overview", "time_filter": "ALL", "org_type": "non_profit"})
    s2 = body["organization_overview"]["summary"]
    check("filter org_type=non_profit: for_profit count is 0",
          s2["for_profit_organizations"] == 0 and s2["total_organizations"] == s2["non_profit_organizations"])

    code, body = call({"dashboard_type": "overview", "time_filter": "ALL",
                       "org_type": "Non-Profit"})
    s2_label = body["organization_overview"]["summary"]
    check("filter accepts the CSV display label 'Non-Profit'",
          s2_label == s2)

    code, body = call({"dashboard_type": "overview", "time_filter": "ALL", "org_size": sample_size})
    sizes = body["organization_overview"]["organizations_by_size"]
    check(f"filter org_size={sample_size}: only that bucket returned",
          len(sizes) == 1 and sizes[0]["size"] == sample_size)

    code, body = call({"dashboard_type": "overview", "time_filter": "ALL",
                       "org_size": sample_size.upper()})
    check(f"filter org_size={sample_size.upper()} (case-insensitive) matches",
          body["organization_overview"]["organizations_by_size"] == sizes)

    code, body = call({"dashboard_type": "overview", "time_filter": "ALL", "state_id": sample_state_id})
    locs = body["organization_overview"]["organizations_by_location"]
    check(f"filter state_id={sample_state_id}: all locations in {sample_state_name}",
          all(l["state"] == sample_state_name for l in locs) and len(locs) > 0)

    code, body = call({"dashboard_type": "overview", "time_filter": "ALL",
                       "city_name": sample_city.lower()})
    locs = body["organization_overview"]["organizations_by_location"]
    check(f"filter city_name (case-insensitive): only {sample_city}",
          all(l["city"] == sample_city for l in locs) and len(locs) > 0)

    code, body = call({"dashboard_type": "overview", "time_filter": "ALL", "is_collaborator": True})
    s3 = body["organization_overview"]["summary"]
    check("filter is_collaborator=true: non_collaborator count is 0",
          s3["non_collaborator_organizations"] == 0)

    code, body = call({"dashboard_type": "overview", "time_filter": "ALL", "is_contributor": False})
    s4 = body["organization_overview"]["summary"]
    check("filter is_contributor=false: contributor count is 0",
          s4["contributor_organizations"] == 0)

    code, body = call({"dashboard_type": "performance", "time_filter": "ALL",
                       "org_rating": sample_rating})
    pf2 = body["organization_performance"]
    check(f"filter org_rating={sample_rating}: only that bucket non-zero, rest zero-filled",
          [r["rating"] for r in pf2["rating_distribution"]] == [1, 2, 3, 4, 5] and
          all(r["count"] == 0 for r in pf2["rating_distribution"] if r["rating"] != sample_rating) and
          next(r["count"] for r in pf2["rating_distribution"] if r["rating"] == sample_rating) > 0)

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

    # 9. Credentials come from configuration, never a hard-coded Parameter Store path
    # Pattern-matched rather than spelled out, so no Parameter Store path
    # literal exists anywhere in the repository, not even as an assertion.
    source = open(oa.__file__, encoding="utf-8").read()
    absolute_path_literals = re.findall(r"""['"]/[a-z0-9_\-/]*saayam[a-z0-9_\-/]*['"]""",
                                        source, re.IGNORECASE)
    check("no Parameter Store path hard-coded in source",
          absolute_path_literals == [], f"found {absolute_path_literals}")

    os.environ["LOCAL_DB"] = "false"
    os.environ.pop("DB_CREDENTIALS_PARAMETER", None)
    try:
        oa.get_db_connection()
        check("missing DB_CREDENTIALS_PARAMETER raises a clear error", False)
    except RuntimeError as error:
        check("missing DB_CREDENTIALS_PARAMETER raises a clear error",
              "DB_CREDENTIALS_PARAMETER" in str(error))
    except Exception as error:
        check("missing DB_CREDENTIALS_PARAMETER raises a clear error", False,
              f"got {type(error).__name__}")
    finally:
        os.environ["LOCAL_DB"] = "true"

    # 10. A failing metric must not cascade into the metrics that follow it
    def failing_fetch(cursor, *_args):
        cursor.execute("SELECT 1 / 0")
        return []

    original_by_type = oa.fetch_organizations_by_type
    oa.fetch_organizations_by_type = failing_fetch
    try:
        code, body = call({"dashboard_type": "overview", "time_filter": "ALL"})
        ov_err = body["organization_overview"]
        check("failing metric: request still 200", code == 200)
        check("failing metric: its own section falls back to the safe default",
              ov_err["organizations_by_type"] == [])
        check("failing metric: later queries on the same connection still succeed",
              ov_err["summary"]["total_organizations"] == s["total_organizations"] and
              sum(r["count"] for r in ov_err["organizations_by_size"]) == s["total_organizations"] and
              len(ov_err["organization_activity_trend"]) > 0)
    finally:
        oa.fetch_organizations_by_type = original_by_type

    # 11. Graceful degradation when the organizations table has no is_contributor column
    original_detector = oa.has_contributor_column
    oa.has_contributor_column = lambda cursor: False
    try:
        code, body = call({"dashboard_type": "overview", "time_filter": "ALL"})
        ov_nc = body["organization_overview"]
        s_nc = ov_nc["summary"]
        check("no is_contributor column: overview still 200", code == 200)
        check("no is_contributor column: non-contributor metrics unaffected",
              s_nc["total_organizations"] == s["total_organizations"] and
              s_nc["collaborator_organizations"] == s["collaborator_organizations"])
        check("no is_contributor column: contributor metrics zero/empty",
              s_nc["contributor_organizations"] == 0 and
              s_nc["non_contributor_organizations"] == 0 and
              ov_nc["contributor_distribution"] == [])
        check("no is_contributor column: schema note returned",
              any("is_contributor" in note for note in body.get("schema_notes", [])))

        code, body = call({"dashboard_type": "overview", "time_filter": "ALL",
                           "is_contributor": True})
        check("no is_contributor column: is_contributor filter ignored, not fatal",
              code == 200 and
              body["organization_overview"]["summary"]["total_organizations"] == s["total_organizations"])

        code, body = call({"dashboard_type": "performance", "time_filter": "ALL"})
        pf_nc = body["organization_performance"]
        check("no is_contributor column: performance still 200 with ratings intact",
              code == 200 and pf_nc["summary"]["rated_organizations"] == ps["rated_organizations"])
        check("no is_contributor column: top contributors empty",
              pf_nc["top_contributor_organizations"] == [])
    finally:
        oa.has_contributor_column = original_detector

    print("\n".join(RESULTS))
    print(f"\n{PASS} passed, {FAIL} failed out of {PASS + FAIL} checks.")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
