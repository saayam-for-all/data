"""Shared mock-data builder for the #336 Growth & Location Analytics spec.

Deliberately includes the edge cases the spec cares about:
  - a gap month with zero activity (tests that sparse arrays omit it)
  - five countries so the top-4 location cap has to actually truncate
  - a recency ladder that straddles the 7D / 30D / 1Y window boundaries

country_id/state_id are internally consistent here. The CSVs shipped for
#336 have all US states pointing at country_id=1, which is Afghanistan in
countries.csv, not the USA (country_id=233) -- confirmed as a data bug by
the team lead in the #336 WhatsApp thread on 2026-09-21, who said to build
our own correct test CSVs rather than rely on the shipped ones.
"""
import csv
import os
from datetime import datetime, timedelta, timezone


def _month_start(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _shift_months(dt, n):
    y, m = dt.year, dt.month + n
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return dt.replace(year=y, month=m)


def build(now=None, ts_style="date"):
    """Build (countries, states, orgs) tuples.

    ts_style: 'date' (YYYY-MM-DD, matching every other CSV in this repo) or
    'iso_z' (YYYY-MM-DDTHH:MM:SSZ). Use 'iso_z' to check timezone-aware
    timestamp handling -- some implementations assume naive dates and raise
    on tz-aware input.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    countries = [(1, "USA"), (2, "IND"), (3, "GBR"), (4, "CAN"), (5, "AUS")]
    states = [
        (1, "New York", 1), (2, "California", 1), (3, "Texas", 1),
        (4, "Delhi", 2), (5, "Maharashtra", 2),
        (6, "London", 3),
        (7, "Ontario", 4),
        (8, "Sydney", 5),
    ]

    orgs = []
    oid = 1

    def fmt(dt):
        if ts_style == "iso_z":
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return dt.strftime("%Y-%m-%d")

    def add(state_id, city, collab, dt):
        nonlocal oid
        orgs.append((oid, state_id, city, collab, fmt(dt)))
        oid += 1

    # 14 months of history, skipping month -6 (deliberate gap, sparse-array
    # check) and doubling month -3 with a second country.
    this_month = _month_start(now)
    for back in range(14, 0, -1):
        if back == 6:
            continue
        m = _shift_months(this_month, -back)
        collab = back in (14, 9, 3)
        add(1, "NY", collab, m + timedelta(days=2))
        if back == 3:
            add(6, "LON", False, m + timedelta(days=5))

    # Recency ladder relative to "now".
    add(1, "NY", False, now - timedelta(days=40))  # outside 30D, inside 1Y
    add(2, "LA", True, now - timedelta(days=20))    # inside 30D, outside 7D
    add(4, "DEL", False, now - timedelta(days=5))   # inside 7D
    add(7, "TOR", True, now - timedelta(days=1))    # inside 7D, collaborator
    add(1, "NY", False, now - timedelta(hours=2))   # inside 7D

    # Enough distinct countries to make the top-4 cap bite.
    add(1, "NY", False, now - timedelta(days=10))
    add(1, "NY", False, now - timedelta(days=11))
    add(2, "LA", False, now - timedelta(days=12))
    add(4, "DEL", False, now - timedelta(days=13))
    add(6, "LON", False, now - timedelta(days=14))
    add(7, "TOR", False, now - timedelta(days=15))
    add(8, "SYD", False, now - timedelta(days=16))  # 5th country -> dropped

    return countries, states, orgs


def write_csvs(target_dir, countries, states, orgs, collab_encoder=None):
    """Writes organizations.csv / states.csv / countries.csv to target_dir.

    collab_encoder(bool) -> str lets callers probe how an implementation
    handles different is_collaborator encodings (true/false, 1/0, Y/N, ...).
    Defaults to lowercase 'true'/'false'.
    """
    os.makedirs(target_dir, exist_ok=True)
    if collab_encoder is None:
        collab_encoder = lambda b: "true" if b else "false"  # noqa: E731

    with open(os.path.join(target_dir, "countries.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country_id", "country_code"])
        w.writerows(countries)

    with open(os.path.join(target_dir, "states.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["state_id", "state_name", "country_id"])
        w.writerows(states)

    with open(os.path.join(target_dir, "organizations.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["org_id", "state_id", "city_name", "is_collaborator", "created_at"])
        for oid, state_id, city, collab, ts in orgs:
            w.writerow([oid, state_id, city, collab_encoder(collab), ts])
