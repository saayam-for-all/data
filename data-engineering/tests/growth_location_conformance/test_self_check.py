"""Self-check for the #336 conformance fixture and oracle.

Doesn't require any candidate implementation to be merged -- validates that
the shared fixture and independent oracle (fixtures.py, oracle.py) are
internally consistent, so this suite has CI value on its own and a
regression here can't be blamed on someone else's Lambda code.
"""
from datetime import datetime, timezone

from tests.growth_location_conformance import fixtures, oracle


def _fixture(now=None):
    now = now or datetime(2026, 9, 21, tzinfo=timezone.utc)
    return fixtures.build(now), now


def test_fixture_has_expected_totals():
    (countries, states, orgs), _ = _fixture()
    assert len(orgs) == 26
    assert sum(1 for o in orgs if o[3]) == 5


def test_oracle_total_organizations_is_cumulative_across_windows():
    (countries, states, orgs), now = _fixture()
    result = oracle.compute_all_buckets(countries, states, orgs, now)

    grand_total = len(orgs)
    last_7d = result["7D"]["growth_trend"]["total_organizations"][-1]["count"]
    last_all = result["All"]["growth_trend"]["total_organizations"][-1]["count"]

    assert last_7d == grand_total, "7D's cumulative total must equal the all-time total"
    assert last_all == grand_total


def test_oracle_cumulative_series_is_non_decreasing():
    (countries, states, orgs), now = _fixture()
    result = oracle.compute_all_buckets(countries, states, orgs, now)

    counts = [x["count"] for x in result["All"]["growth_trend"]["total_organizations"]]
    assert counts == sorted(counts)


def test_oracle_gap_month_is_omitted_sparse():
    (countries, states, orgs), now = _fixture()
    result = oracle.compute_all_buckets(countries, states, orgs, now)

    periods = {x["period"] for x in result["All"]["growth_trend"]["collaborators"]}
    gap_month = oracle.calendar_months_back(now, 7)  # the deliberately-skipped month
    assert gap_month.strftime("%Y-%m") not in periods


def test_oracle_location_caps_at_top_4():
    (countries, states, orgs), now = _fixture()
    result = oracle.compute_all_buckets(countries, states, orgs, now)

    loc = result["All"]["organizations_by_location"]
    assert len(loc) <= 4
    counts = [x["count"] for x in loc]
    assert counts == sorted(counts, reverse=True)
    assert all(set(x.keys()) == {"country", "count"} for x in loc)


def test_write_csvs_round_trips_through_pandas():
    import os
    import tempfile

    import pandas as pd

    (countries, states, orgs), _ = _fixture()
    with tempfile.TemporaryDirectory() as tmp:
        fixtures.write_csvs(tmp, countries, states, orgs)
        orgs_df = pd.read_csv(os.path.join(tmp, "organizations.csv"))
        assert len(orgs_df) == len(orgs)
        assert list(orgs_df.columns) == [
            "org_id", "state_id", "city_name", "is_collaborator", "created_at",
        ]
