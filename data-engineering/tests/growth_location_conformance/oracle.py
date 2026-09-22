"""Independent ground-truth calculator for the #336 spec.

Computed straight from the raw fixture tuples in fixtures.py, not from any
candidate implementation, so there is something neutral to diff a
lambda_handler's output against.
"""
from datetime import datetime, timezone

import pandas as pd


def _to_df(countries, states, orgs):
    org_df = pd.DataFrame(
        orgs, columns=["org_id", "state_id", "city", "is_collaborator", "created_at"]
    )
    org_df["created_at"] = pd.to_datetime(org_df["created_at"], utc=True)
    state_df = pd.DataFrame(states, columns=["state_id", "state_name", "country_id"])
    country_df = pd.DataFrame(countries, columns=["country_id", "country_code"])
    return org_df.merge(state_df, on="state_id", how="left").merge(
        country_df, on="country_id", how="left"
    )


def calendar_months_back(now, n):
    """1st of the month that is (n-1) months before `now`'s month.

    Per the team lead's ruling (#336 WhatsApp, 2026-09-21): "1Y means
    trailing 12 calendar months."
    """
    y, m = now.year, now.month - (n - 1)
    while m < 1:
        m += 12
        y -= 1
    return datetime(y, m, 1, tzinfo=timezone.utc)


def windows(now):
    from datetime import timedelta

    return {
        "7D": (now - timedelta(days=7), now, "day"),
        "30D": (now - timedelta(days=30), now, "day"),
        "1Y": (calendar_months_back(now, 12), now, "month"),
        "All": (None, now, "month"),
    }


def _period_label(ts, granularity):
    return ts.strftime("%Y-%m-%d") if granularity == "day" else ts.strftime("%Y-%m")


def _bucket_result(df, window_start, window_end, granularity):
    upto_end = df[df["created_at"] <= window_end].copy()
    in_window = (
        upto_end[upto_end["created_at"] >= window_start].copy()
        if window_start is not None
        else upto_end.copy()
    )

    if in_window.empty:
        return {"total_organizations": [], "collaborators": []}, []

    in_window["period"] = in_window["created_at"].apply(lambda t: _period_label(t, granularity))
    periods = sorted(in_window["period"].unique())

    upto_end["period"] = upto_end["created_at"].apply(lambda t: _period_label(t, granularity))
    total_series = [
        {"period": p, "count": int((upto_end["period"] <= p).sum())} for p in periods
    ]

    collab = in_window[in_window["is_collaborator"] == True]  # noqa: E712
    collab_counts = collab.groupby("period").size().to_dict()
    collab_series = [{"period": p, "count": int(collab_counts.get(p, 0))} for p in periods]

    loc_counts = in_window.groupby("country_code").size().sort_values(ascending=False)
    top4 = [{"country": c, "count": int(n)} for c, n in loc_counts.head(4).items()]

    return {"total_organizations": total_series, "collaborators": collab_series}, top4


def compute_all_buckets(countries, states, orgs, now=None):
    if now is None:
        now = datetime.now(timezone.utc)
    df = _to_df(countries, states, orgs)
    result = {}
    for bucket, (start, end, gran) in windows(now).items():
        growth, loc = _bucket_result(df, start, end, gran)
        result[bucket] = {"growth_trend": growth, "organizations_by_location": loc}
    return result
