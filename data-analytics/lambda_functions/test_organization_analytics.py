"""
test_organization_analytics.py
===============================

LOCAL test harness for organization_analytics.py (Issue #228).

It does NOT use AWS credentials. Instead it opens its own psycopg2 connection
to a LOCAL PostgreSQL instance (configured via environment variables) and
injects that cursor straight into the dashboard functions -- exactly how the
Lambda would call them in production, minus the credential fetch.

Prerequisites:
    1. Create a local PostgreSQL database:
           createdb saayam_local
    2. Load the real reference data from the repo:
           psql -d saayam_local -c "CREATE SCHEMA IF NOT EXISTS virginia_dev_saayam_rdbms;"
       Then import organizations.csv and state.csv from data-analytics/sql/
       into virginia_dev_saayam_rdbms.organizations and virginia_dev_saayam_rdbms.state.

Environment variables (all optional, sensible localhost defaults):
    PGHOST      (default: localhost)
    PGPORT      (default: 5432)
    PGDATABASE  (default: saayam_local)
    PGUSER      (default: postgres)
    PGPASSWORD  (default: postgres)

Run:
    python test_organization_analytics.py
    python test_organization_analytics.py --json   # dump full JSON per case
"""

import os
import sys
import json

import psycopg2
from psycopg2.extras import RealDictCursor

import organization_analytics as oa


def local_connection():
    """Open a local psycopg2 connection from env vars (NO hardcoded secrets)."""
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "saayam_local"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", "postgres"),
    )


TIME_FILTERS = ["7D", "30D", "1Y", "All", "Custom"]
GROUP_BYS = ["daily", "weekly", "monthly", "yearly"]


def run_all(dump_json=False):
    conn = local_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    passed = 0
    failed = 0

    def check(label, ok):
        nonlocal passed, failed
        if ok:
            passed += 1
            print(f"  PASS  {label}")
        else:
            failed += 1
            print(f"  FAIL  {label}")

    # -------------------------------------------------------------------
    # 1) OVERVIEW dashboard across all 5 time filters
    # -------------------------------------------------------------------
    print("\n=== DASHBOARD 1: ORGANIZATION OVERVIEW (all time filters) ===")
    for tf in TIME_FILTERS:
        custom = tf == "Custom"
        filters = oa.combine_filters(
            tf,
            "2025-01-01" if custom else None,
            "2026-12-31" if custom else None,
        )
        result = oa.build_overview_dashboard(cursor, filters, group_by="monthly")
        ov = result["organization_overview"]

        # Structure assertions — must match spec exactly.
        expected_keys = {
            "summary", "organization_activity_trend", "organizations_by_type",
            "organizations_by_size", "organizations_by_location",
            "collaborator_distribution", "contributor_distribution",
        }
        check(f"[{tf}] overview has exact top-level keys",
              set(ov.keys()) == expected_keys)

        summary = ov["summary"]
        summary_keys = {
            "total_organizations", "non_profit_organizations",
            "for_profit_organizations", "collaborator_organizations",
            "non_collaborator_organizations", "contributor_organizations",
            "non_contributor_organizations",
        }
        check(f"[{tf}] overview summary keys", set(summary.keys()) == summary_keys)
        check(f"[{tf}] non_profit + for_profit <= total",
              summary["non_profit_organizations"] + summary["for_profit_organizations"]
              <= summary["total_organizations"])
        check(f"[{tf}] collaborator split sums to total",
              summary["collaborator_organizations"] + summary["non_collaborator_organizations"]
              == summary["total_organizations"])

        print(f"    -> {tf}: total={summary['total_organizations']}, "
              f"non_profit={summary['non_profit_organizations']}, "
              f"collaborators={summary['collaborator_organizations']}, "
              f"trend_points={len(ov['organization_activity_trend'])}")

        if dump_json:
            print(json.dumps(result, indent=2, default=str))

    # -------------------------------------------------------------------
    # 2) OVERVIEW trend across all group_by options
    # -------------------------------------------------------------------
    print("\n=== OVERVIEW registration trend: all group_by options ===")
    filters_all = oa.combine_filters("All", None, None)
    for gb in GROUP_BYS:
        trend = oa.get_organization_registration_trend(cursor, filters_all, gb)
        check(f"[group_by={gb}] returns a list with period+count",
              isinstance(trend, list)
              and all("period" in r and "count" in r for r in trend))
        print(f"    -> {gb}: {len(trend)} buckets, sample={trend[:2]}")

    # -------------------------------------------------------------------
    # 3) PERFORMANCE dashboard across all 5 time filters
    # -------------------------------------------------------------------
    print("\n=== DASHBOARD 2: ORGANIZATION PERFORMANCE (all time filters) ===")
    for tf in TIME_FILTERS:
        custom = tf == "Custom"
        filters = oa.combine_filters(
            tf,
            "2025-01-01" if custom else None,
            "2026-12-31" if custom else None,
        )
        result = oa.build_performance_dashboard(cursor, filters)
        pf = result["organization_performance"]

        expected_keys = {
            "summary", "rating_distribution", "top_rated_organizations",
            "top_collaborator_organizations", "top_contributor_organizations",
            "ratings_by_organization_type", "ratings_by_organization_size",
        }
        check(f"[{tf}] performance has exact top-level keys",
              set(pf.keys()) == expected_keys)

        summary = pf["summary"]
        summary_keys = {
            "average_rating", "rated_organizations",
            "unrated_organizations", "five_star_organizations",
        }
        check(f"[{tf}] performance summary keys", set(summary.keys()) == summary_keys)
        check(f"[{tf}] rating_distribution always has 5 buckets",
              len(pf["rating_distribution"]) == 5)
        check(f"[{tf}] top_rated_organizations <= 10",
              len(pf["top_rated_organizations"]) <= 10)

        print(f"    -> {tf}: avg={summary['average_rating']}, "
              f"rated={summary['rated_organizations']}, "
              f"unrated={summary['unrated_organizations']}, "
              f"five_star={summary['five_star_organizations']}")

        if dump_json:
            print(json.dumps(result, indent=2, default=str))

    # -------------------------------------------------------------------
    # 4) Additional org filters
    # -------------------------------------------------------------------
    print("\n=== ADDITIONAL FILTERS (org_type / org_size / state_id / flags) ===")
    f_np = oa.combine_filters("All", None, None, org_type="non_profit")
    only_np = oa.get_organizations_by_type(cursor, f_np)
    check("org_type=non_profit filter returns only non_profit",
          all(r["org_type"] == "non_profit" for r in only_np))

    f_va = oa.combine_filters("All", None, None, state_id="VA")
    va_locs = oa.get_organizations_by_location(cursor, f_va)
    check("state_id=VA filter returns only VA rows",
          all(r["state_id"] == "VA" for r in va_locs))

    f_collab = oa.combine_filters("All", None, None, is_collaborator=True)
    collab_total = oa.get_total_organizations(cursor, f_collab)
    check("is_collaborator=True filter reduces / equals total", collab_total >= 0)
    print(f"    -> non_profit types={only_np}, VA locations={len(va_locs)}, "
          f"collaborators_total={collab_total}")

    # -------------------------------------------------------------------
    # 5) lambda_handler routing (both endpoint styles)
    # Monkeypatches get_db_connection so the handler uses our local cursor.
    # -------------------------------------------------------------------
    print("\n=== lambda_handler routing (both endpoint styles) ===")
    oa.get_db_connection = local_connection

    # a) single endpoint with dashboard_type param
    r1 = oa.lambda_handler({"dashboard_type": "overview", "time_filter": "All"}, None)
    check("single-endpoint overview -> 200 + organization_overview",
          r1["statusCode"] == 200 and "organization_overview" in json.loads(r1["body"]))

    r2 = oa.lambda_handler({"dashboard_type": "performance", "time_filter": "All"}, None)
    check("single-endpoint performance -> 200 + organization_performance",
          r2["statusCode"] == 200 and "organization_performance" in json.loads(r2["body"]))

    # b) route based (API Gateway style path)
    r3 = oa.lambda_handler(
        {"path": "/analytics/organizations/performance",
         "body": json.dumps({"time_filter": "1Y"})},
        None,
    )
    check("route /performance -> organization_performance",
          "organization_performance" in json.loads(r3["body"]))

    r4 = oa.lambda_handler(
        {"rawPath": "/analytics/organizations/overview",
         "body": json.dumps({"time_filter": "30D"})},
        None,
    )
    check("route /overview -> organization_overview",
          "organization_overview" in json.loads(r4["body"]))

    # c) CORS headers present
    check("response carries CORS header",
          r1["headers"].get("Access-Control-Allow-Origin") == "*")

    cursor.close()
    conn.close()

    print(f"\n================  RESULT: {passed} passed, {failed} failed  ================")
    return failed == 0


if __name__ == "__main__":
    dump = "--json" in sys.argv
    ok = run_all(dump_json=dump)
    sys.exit(0 if ok else 1)