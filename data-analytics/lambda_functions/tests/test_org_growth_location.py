"""Local tests for organization_growth_location_analytics (no DB needed).

Run: python3 -m pytest tests/test_org_growth_location.py
Optionally set ORG_CSV_DIR to a folder with organizations/states/countries CSVs
to also smoke-test against real sample files.
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import organization_growth_location_analytics as m

TODAY = date(2026, 9, 29)


def org(created, collab=False, country="USA"):
    return {"created": created, "is_collaborator": collab, "country": country}


ORGS = [
    org(date(2025, 1, 15), True, "USA"),
    org(date(2026, 3, 10), False, "IND"),
    org(date(2026, 9, 25), True, "USA"),
    org(date(2026, 9, 29), False, "MEX"),
    org(date(2026, 9, 29), True, "IND"),
    org(date(2026, 9, 1), False, "CAN"),
    org(date(2026, 9, 2), False, "BRA"),
]


def test_five_top_level_keys():
    assert list(m.build_analytics(ORGS, TODAY)) == ["7D", "30D", "1Y", "All", "Custom"]


def test_7d_daily_buckets_and_running_total():
    g = m.build_analytics(ORGS, TODAY)["7D"]["growth_trend"]
    assert [p["period"] for p in g][0] == "2026-09-23" and len(g) == 7
    # Total is all-time: 4 orgs existed before the window opened (9/23).
    assert g[0]["total_organizations"] == 4
    assert g[-1]["total_organizations"] == 7
    assert g[-1]["collaborators"] == 1
    assert sum(p["collaborators"] for p in g) == 2


def test_1y_and_all_use_months():
    b = m.build_analytics(ORGS, TODAY)
    assert len(b["1Y"]["growth_trend"]) == 12
    assert b["1Y"]["growth_trend"][0]["period"] == "2025-10"
    assert b["1Y"]["growth_trend"][0]["total_organizations"] == 1  # pre-window org counted
    assert b["All"]["growth_trend"][0]["period"] == "2025-01"
    assert b["All"]["growth_trend"][-1]["total_organizations"] == 7


def test_location_max_four_no_other_sorted():
    loc = m.build_analytics(ORGS, TODAY)["All"]["organizations_by_location"]
    assert len(loc) == 4
    assert loc[0] == {"country": "IND", "count": 2} or loc[0]["count"] == 2
    assert all(r["country"] != "Other" for r in loc)


def test_custom_independent_ranges():
    ev = {
        "growth_start_date": "2026-09-01", "growth_end_date": "2026-09-03",
        "location_start_date": "2026-03-01", "location_end_date": "2026-03-31",
    }
    c = m.build_analytics(ORGS, TODAY, ev)["Custom"]
    assert [p["period"] for p in c["growth_trend"]] == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert c["growth_trend"][0]["total_organizations"] == 3
    assert c["organizations_by_location"] == [{"country": "IND", "count": 1}]


def test_custom_missing_or_bad_input():
    assert m.build_analytics(ORGS, TODAY)["Custom"] == {"growth_trend": [], "organizations_by_location": []}
    with pytest.raises(ValueError):
        m.build_analytics(ORGS, TODAY, {"growth_start_date": "bad", "growth_end_date": "2026-01-01"})
    with pytest.raises(ValueError):
        m.build_analytics(ORGS, TODAY, {"growth_start_date": "2026-02-01", "growth_end_date": "2026-01-01"})


def test_empty_orgs():
    b = m.build_analytics([], TODAY)
    assert b["All"]["organizations_by_location"] == []
    assert b["7D"]["growth_trend"][-1]["total_organizations"] == 0


@pytest.mark.skipif(not os.environ.get("ORG_CSV_DIR"), reason="ORG_CSV_DIR not set")
def test_csv_smoke():
    d = os.environ["ORG_CSV_DIR"]
    orgs = m.load_csv_data(f"{d}/organizations.csv", f"{d}/states.csv", f"{d}/countries.csv")
    b = m.build_analytics(orgs, TODAY)
    assert b["All"]["growth_trend"][-1]["total_organizations"] == len(orgs)
    assert len(b["All"]["organizations_by_location"]) <= 4
