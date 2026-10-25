"""
Local validation harness for organization_analytics.py.

Unlike the mock-cursor unit tests in tests/test_organization_analytics.py, this
runs the real handler against a real local PostgreSQL and compares every number
to ground truth computed with independent SQL — so it verifies the module's
queries rather than the module checking itself.

Usage:
    python load_organizations.py ../sql          # once
    python run_local_org_tests.py

DB connection uses the same libpq env vars the Lambda reads:
    PGHOST (localhost)  PGPORT (5432)  PGDATABASE (saayam_local)
    PGUSER (your OS username)  PGPASSWORD (unset)
"""
import json
import os
import re
import sys

import psycopg2

import organization_analytics as m
from organization_analytics import default_db_user

SCHEMA = "virginia_dev_saayam_rdbms"
ORGANIZATIONS = f"{SCHEMA}.organizations"

PERIOD_PATTERNS = {
    "daily": r"^\d{4}-\d{2}-\d{2}$",
    "weekly": r"^\d{4}-W\d{2}$",
    "monthly": r"^\d{4}-\d{2}$",
    "yearly": r"^\d{4}$",
}

FAILS = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail and not condition else ""))
    if not condition:
        FAILS.append(name)


def scalar(cursor, query, params=None):
    cursor.execute(query, params or [])
    row = cursor.fetchone()
    return row[0] if row else None


def invoke(payload):
    response = m.lambda_handler(payload, None)
    return response["statusCode"], json.loads(response["body"])


def payload(**overrides):
    base = {
        "time_filter": "ALL",
        "start_date": None,
        "end_date": None,
        "group_by": "monthly",
        "region": "ALL",
        "organization_type": "ALL",
    }
    base.update(overrides)
    return base


def main():
    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "saayam_local"),
        user=os.getenv("PGUSER") or default_db_user(),
        password=os.getenv("PGPASSWORD", ""),
    )
    cursor = conn.cursor()

    print("=" * 70)
    print("A) KPI summary vs independent SQL")
    print("=" * 70)
    status, body = invoke(payload())
    check("status is 200", status == 200, f"got {status}")

    total = scalar(cursor, f"SELECT COUNT(*) FROM {ORGANIZATIONS};")
    collaborators = scalar(
        cursor,
        f"SELECT COUNT(*) FROM {ORGANIZATIONS} WHERE UPPER(is_collaborator::text) = 'TRUE';",
    )
    average = scalar(
        cursor, f"SELECT ROUND(AVG(org_rating::numeric), 1) FROM {ORGANIZATIONS};"
    )
    check("total_organizations", body["summary"]["total_organizations"] == total,
          f"{body['summary']['total_organizations']} vs {total}")
    check("total_collaborators", body["summary"]["total_collaborators"] == collaborators,
          f"{body['summary']['total_collaborators']} vs {collaborators}")
    check("average_org_rating",
          body["summary"]["average_org_rating"] == float(average or 0),
          f"{body['summary']['average_org_rating']} vs {average}")

    print("=" * 70)
    print("B) Distributions sum back to the filtered total")
    print("=" * 70)
    check("size buckets sum to total",
          sum(r["organization_count"] for r in body["organizations_by_size"]) == total)
    check("location counts sum to total",
          sum(r["organization_count"] for r in body["organizations_by_location"]) == total)
    check("location percentages sum to ~100",
          abs(sum(r["percentage"] for r in body["organizations_by_location"]) - 100) < 1)
    check("nested cities sum to their state count",
          all(sum(c["organization_count"] for c in r["cities"]) == r["organization_count"]
              for r in body["organizations_by_location"]))
    rated = scalar(cursor, f"SELECT COUNT(*) FROM {ORGANIZATIONS} WHERE org_rating IS NOT NULL;")
    check("rating buckets sum to rated organizations",
          sum(r["organization_count"] for r in body["rating_distribution"]) == rated)
    check("rating distribution covers 1..5",
          [r["rating"] for r in body["rating_distribution"]] == [1, 2, 3, 4, 5])

    print("=" * 70)
    print("C) Growth trend is cumulative and lands on the total")
    print("=" * 70)
    trend = body["growth_trend"]
    check("trend is non-decreasing",
          all(a["total_organizations"] <= b["total_organizations"]
              for a, b in zip(trend, trend[1:])))
    check("final period equals total_organizations",
          bool(trend) and trend[-1]["total_organizations"] == total)
    check("final collaborators equals KPI collaborators",
          bool(trend) and trend[-1]["total_collaborators"] == collaborators)

    print("=" * 70)
    print("D) group_by period formats")
    print("=" * 70)
    for group_by, pattern in PERIOD_PATTERNS.items():
        _, grouped = invoke(payload(group_by=group_by))
        periods = [r["period"] for r in grouped["growth_trend"]]
        check(f"{group_by}: period label format",
              bool(periods) and all(re.match(pattern, p) for p in periods),
              f"sample={periods[:2]}")
        check(f"{group_by}: cumulative reaches total",
              bool(periods) and grouped["growth_trend"][-1]["total_organizations"] == total)

    print("=" * 70)
    print("E) organization_type filter")
    print("=" * 70)
    for org_type in ("for_profit", "non_profit"):
        expected = scalar(
            cursor,
            f"""SELECT COUNT(*) FROM {ORGANIZATIONS}
                WHERE REPLACE(LOWER(TRIM(org_type::text)), '-', '_') = %s;""",
            [org_type],
        )
        _, filtered = invoke(payload(organization_type=org_type))
        check(f"{org_type}: total matches independent count",
              filtered["summary"]["total_organizations"] == expected,
              f"{filtered['summary']['total_organizations']} vs {expected}")

    print("=" * 70)
    print("F) region filter")
    print("=" * 70)
    state_id = scalar(
        cursor,
        f"""SELECT state_id FROM {ORGANIZATIONS}
            WHERE state_id IS NOT NULL
            GROUP BY state_id ORDER BY COUNT(*) DESC, state_id LIMIT 1;""",
    )
    if state_id is None:
        print("  SKIPPED — no state_id values present")
    else:
        expected = scalar(
            cursor,
            f"SELECT COUNT(*) FROM {ORGANIZATIONS} WHERE UPPER(TRIM(state_id::text)) = UPPER(%s);",
            [state_id],
        )
        _, regional = invoke(payload(region=state_id))
        check(f"region={state_id}: total matches independent count",
              regional["summary"]["total_organizations"] == expected,
              f"{regional['summary']['total_organizations']} vs {expected}")
        check(f"region={state_id}: one state row returned",
              len(regional["organizations_by_location"]) == 1)
        _, lowered = invoke(payload(region=state_id.lower()))
        check("region filter is case-insensitive",
              lowered["summary"]["total_organizations"] == expected)

    print("=" * 70)
    print("G) CUSTOM date range")
    print("=" * 70)
    bounds = scalar(
        cursor,
        f"SELECT TO_CHAR(MIN(created_at), 'YYYY-MM-DD') || '/' "
        f"|| TO_CHAR(MAX(created_at), 'YYYY-MM-DD') FROM {ORGANIZATIONS};",
    )
    start, end = bounds.split("/")
    expected = scalar(
        cursor,
        f"""SELECT COUNT(*) FROM {ORGANIZATIONS}
            WHERE created_at >= %s::date AND created_at < (%s::date + INTERVAL '1 day');""",
        [start, end],
    )
    _, custom = invoke(payload(time_filter="CUSTOM", start_date=start, end_date=end))
    check("CUSTOM full-range total matches independent count",
          custom["summary"]["total_organizations"] == expected,
          f"{custom['summary']['total_organizations']} vs {expected}")
    check("CUSTOM end date is inclusive", custom["summary"]["total_organizations"] == total)

    _, empty = invoke(
        payload(time_filter="CUSTOM", start_date="1900-01-01", end_date="1900-12-31")
    )
    check("empty window returns zeroed summary",
          empty["summary"]["total_organizations"] == 0)
    check("empty window keeps fixed-domain buckets",
          [r["organization_count"] for r in empty["rating_distribution"]] == [0] * 5)
    check("empty window returns empty trend", empty["growth_trend"] == [])

    print("=" * 70)
    print("H) Invalid filters are rejected with 400")
    print("=" * 70)
    invalid = [
        ("unknown time_filter", payload(time_filter="90D")),
        ("unknown group_by", payload(group_by="hourly")),
        ("unknown organization_type", payload(organization_type="charity")),
        ("CUSTOM without dates", payload(time_filter="CUSTOM")),
        ("reversed range", payload(time_filter="CUSTOM", start_date="2026-06-30",
                                   end_date="2026-01-01")),
        ("malformed date", payload(time_filter="CUSTOM", start_date="06/30/2026",
                                   end_date="2026-01-01")),
    ]
    for label, bad in invalid:
        status, bad_body = invoke(bad)
        check(f"400 for {label}", status == 400 and "error" in bad_body, f"got {status}")

    print("=" * 70)
    print("I) is_contributor column detection")
    print("=" * 70)
    present = m.has_column(cursor, ORGANIZATIONS, "is_contributor")
    print(f"  is_contributor present in {ORGANIZATIONS}: {present}")
    types = [r["type"] for r in body["collaborator_vs_contributor"]]
    if present:
        contributors = scalar(
            cursor,
            f"SELECT COUNT(*) FROM {ORGANIZATIONS} WHERE UPPER(is_contributor::text) = 'TRUE';",
        )
        check("total_contributors matches independent count",
              body["summary"]["total_contributors"] == contributors,
              f"{body['summary']['total_contributors']} vs {contributors}")
        check("both types returned", types == ["collaborator", "contributor"])
    else:
        check("contributor row omitted when column absent", types == ["collaborator"])
        check("total_contributors reported as 0",
              body["summary"]["total_contributors"] == 0)

    print("=" * 70)
    print(f"RESULT: {'ALL PASS' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}")
    print("=" * 70)
    cursor.close()
    conn.close()
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
