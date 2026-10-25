"""Growth & Location tab data for the Organization Analytics dashboard (issue #336).

Returns all time buckets (7D/30D/1Y/All/Custom) in one response so each chart's
range control works client-side without another API call. Growth Trend and
Organizations By Location have independent Custom date ranges.
"""

import json
import os
from datetime import datetime, timedelta

import pandas as pd
from dateutil.relativedelta import relativedelta


_HERE = os.path.dirname(os.path.abspath(__file__))
# Data lookup: MOCK_DATA_DIR env var, then a local mock_data/, then repo sql/.
DATA_DIR = (
    os.environ.get("MOCK_DATA_DIR")
    or (os.path.join(_HERE, "mock_data") if os.path.isdir(os.path.join(_HERE, "mock_data")) else None)
    or os.path.join(_HERE, "..", "sql")
)

TOP_N_LOCATIONS = 4


class ValidationError(Exception):
    pass


def load_organizations(data_dir=DATA_DIR):
    """Load organizations joined to their country via state_id -> country_id -> country_code."""
    def find(*names):
        for name in names:
            path = os.path.join(data_dir, name)
            if os.path.exists(path):
                return path
        raise FileNotFoundError(f"None of {names} found in {data_dir}")

    orgs = pd.read_csv(find("organizations.csv"), dtype=str)
    states = pd.read_csv(find("states.csv", "state.csv"), dtype=str)
    countries = pd.read_csv(find("countries.csv", "country.csv"), dtype=str)

    for df in (orgs, states, countries):
        df.columns = [c.strip().lower() for c in df.columns]

    for col in ("org_id", "state_id", "city_name", "is_collaborator", "created_at"):
        if col not in orgs.columns:
            orgs[col] = pd.Series(dtype="object")

    orgs["created_at"] = pd.to_datetime(orgs["created_at"], errors="coerce")
    orgs = orgs[orgs["created_at"].notna()].copy()
    orgs["is_collaborator"] = (
        orgs["is_collaborator"].astype(str).str.strip().str.lower().isin(("true", "1", "t", "yes"))
    )

    for df, col in ((orgs, "state_id"), (states, "state_id"), (states, "country_id"), (countries, "country_id")):
        df[col] = df[col].astype(str).str.strip()

    orgs = orgs.merge(states[["state_id", "country_id"]], on="state_id", how="left")
    orgs = orgs.merge(countries[["country_id", "country_code"]], on="country_id", how="left")
    orgs["country_code"] = orgs["country_code"].fillna("Unknown")
    return orgs


def build_response(orgs, custom, now=None):
    """Assemble all five buckets. `custom` carries the two independent Custom date pairs."""
    now = now or datetime.now()

    def window(start, end):
        w = orgs
        if start is not None:
            w = w[w["created_at"] >= start]
        if end is not None:
            w = w[w["created_at"] <= end]
        return w

    def growth_trend(start, end, monthly):
        # total_organizations is all-time cumulative; collaborators is per-period in the window.
        fmt = "%Y-%m" if monthly else "%Y-%m-%d"
        w = window(start, end)
        if w.empty:
            return {"total_organizations": [], "collaborators": []}

        periods = sorted(set(w["created_at"].dt.strftime(fmt)))

        all_counts = orgs["created_at"].dt.strftime(fmt).value_counts().to_dict()
        cumulative, running = {}, 0
        for p in sorted(all_counts):
            running += all_counts[p]
            cumulative[p] = running

        collab = w[w["is_collaborator"]]["created_at"].dt.strftime(fmt).value_counts().to_dict()
        return {
            "total_organizations": [{"period": p, "count": int(cumulative[p])} for p in periods],
            "collaborators": [{"period": p, "count": int(collab[p])} for p in periods if p in collab],
        }

    def by_location(start, end):
        # Top countries by org count in the window; orgs roll up state -> country.
        w = window(start, end)
        if w.empty:
            return []
        counts = (
            w.groupby("country_code")["org_id"].count()
            .reset_index(name="count")
            .sort_values(["count", "country_code"], ascending=[False, True])
            .head(TOP_N_LOCATIONS)
        )
        return [{"country": r["country_code"], "count": int(r["count"])} for _, r in counts.iterrows()]

    fixed = {
        "7D": (now - timedelta(days=7), now, False),
        "30D": (now - timedelta(days=30), now, False),
        "1Y": (now - relativedelta(years=1), now, True),
        "All": (None, None, True),
    }
    response = {
        bucket: {"growth_trend": growth_trend(start, end, monthly),
                 "organizations_by_location": by_location(start, end)}
        for bucket, (start, end, monthly) in fixed.items()
    }

    # Custom charts populate only when their own range is supplied (daily grouping).
    gt_s, gt_e = custom["gt_start"], custom["gt_end"]
    loc_s, loc_e = custom["loc_start"], custom["loc_end"]
    response["Custom"] = {
        "growth_trend": (growth_trend(gt_s, gt_e, monthly=False)
                         if gt_s and gt_e else {"total_organizations": [], "collaborators": []}),
        "organizations_by_location": (by_location(loc_s, loc_e) if loc_s and loc_e else []),
    }
    return response


def lambda_handler(event, context=None):
    def valid_range(start, end, sf, ef):
        if start is None and end is None:
            return None, None
        if start is None or end is None:
            raise ValidationError(f"Both '{sf}' and '{ef}' must be provided together.")
        try:
            s, e = datetime.strptime(start, "%Y-%m-%d"), datetime.strptime(end, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise ValidationError(f"Invalid date in '{sf}'/'{ef}'. Expected YYYY-MM-DD.")
        if s > e:
            raise ValidationError(f"'{sf}' ({start}) must not be after '{ef}' ({end}).")
        return s, e

    try:
        event = event or {}
        body = event.get("body")
        if isinstance(body, str):
            body = json.loads(body) if body else {}
        params = dict(body) if isinstance(body, dict) else {}
        for key in ("start_date", "end_date", "location_start_date", "location_end_date"):
            if key in event:
                params[key] = event[key]

        gt_s, gt_e = valid_range(params.get("start_date"), params.get("end_date"),
                                 "start_date", "end_date")
        loc_s, loc_e = valid_range(params.get("location_start_date"), params.get("location_end_date"),
                                   "location_start_date", "location_end_date")

        result = build_response(load_organizations(), {
            "gt_start": gt_s, "gt_end": gt_e, "loc_start": loc_s, "loc_end": loc_e,
        })
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"},
                "body": json.dumps(result)}
    except (ValidationError, json.JSONDecodeError) as exc:
        message = "Request body is not valid JSON." if isinstance(exc, json.JSONDecodeError) else str(exc)
        return {"statusCode": 400, "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": message})}


if __name__ == "__main__":
    def show(label, event):
        resp = lambda_handler(event)
        print(f"\n--- {label} (HTTP {resp['statusCode']}) ---")
        print(json.dumps(json.loads(resp["body"]), indent=2))

    print(f"Data dir: {DATA_DIR}")
    show("no body", {})
    show("growth-trend custom only", {"start_date": "2026-01-01", "end_date": "2026-06-30"})
    show("location custom only", {"location_start_date": "2025-01-01", "location_end_date": "2025-12-31"})
    show("both ranges", {
        "start_date": "2026-01-01", "end_date": "2026-06-30",
        "location_start_date": "2025-01-01", "location_end_date": "2025-12-31",
    })
    show("bad date format", {"start_date": "01-01-2026", "end_date": "2026-06-30"})
    show("start after end", {"start_date": "2026-06-30", "end_date": "2026-01-01"})
