# Organization Analytics API — Test Cases & Acceptance Criteria (#228)

Format mirrors the team's volunteer analytics `Test Cases and Acceptance
Criteria` doc, adapted for the two organization dashboards. Every case below is
covered by `test_organization_analytics_local.py` (24 automated assertions);
run it against a local Postgres seeded with `local_setup.sql`.

Note: the source table uses `time_filter` (7D / 30D / 1Y / ALL / CUSTOM) and a
single `group_by`, so there is no separate location date filter (that was a
volunteer-only concept). Location here is state/city, not country.

## Overview dashboard

**TC1 — Default response**
`{ "dashboard_type": "overview" }`
Verify: `organization_overview` present with all keys (`summary`,
`organization_activity_trend`, `organizations_by_type`, `organizations_by_size`,
`organizations_by_location`, `organizations_by_city`, `collaborator_distribution`,
`contributor_distribution`). `collaborator + non_collaborator = total`;
`contributor + non_contributor = total`.

**TC2 — 7D / 30D / 1Y time filter**
`{ "dashboard_type": "overview", "time_filter": "7D" }`
Verify: only organizations registered in the window are counted; every breakdown
and the trend sum to the same filtered total; `7D total <= ALL total`.

**TC3 — Custom date range**
`{ "dashboard_type": "overview", "time_filter": "CUSTOM", "start_date": "2026-01-01", "end_date": "2026-05-31" }`
Verify: only organizations with `created_at` in range are counted.

**TC4 — Trend grouping**
`{ "dashboard_type": "overview", "group_by": "weekly" }` (also daily/monthly/yearly)
Verify: `organization_activity_trend` buckets by the requested unit; periods are
ordered ascending; counts sum to the filtered total.

**TC5 — Dimension filters** (`org_type`, `org_size`, `state_id`, `city_name`,
`org_rating`, `is_collaborator`, `is_contributor`)
`{ "dashboard_type": "overview", "org_type": "non_profit" }`
Verify: each filter narrows the whole dashboard consistently; e.g.
`is_contributor: true` makes `total == contributor_organizations`.

**TC6 — Filter combination**
`{ "dashboard_type": "overview", "time_filter": "1Y", "org_type": "non_profit", "state_id": "VA" }`
Verify: all filters apply together; totals remain internally consistent.

## Performance dashboard

**TC7 — Default response**
`{ "dashboard_type": "performance" }`
Verify: `organization_performance` present with all keys; `rated + unrated = total`;
`five_star <= rated`.

**TC8 — Rating distribution**
Verify: `rating_distribution` always returns buckets 1..5 (zero-filled) and sums
to `rated_organizations`.

**TC9 — Top lists & top_n**
`{ "dashboard_type": "performance", "top_n": 3 }`
Verify: `top_rated_organizations`, `top_collaborator_organizations`,
`top_contributor_organizations` are each capped at `top_n`; no unrated org
appears in `top_rated`.

**TC10 — Ratings by group**
Verify: `ratings_by_organization_type` and `ratings_by_organization_size` return
an average rating and rated count per group.

## Robustness

**TC11 — Zero-match / empty result**
`{ "dashboard_type": "overview", "state_id": "__no_such_state__" }`
Verify: returns 200 with `total = 0`, empty lists, and still-valid structure —
no crash.

**TC12 — DB unavailable (safe response)**
Verify: on a failed DB connection the handler returns a 500 with the safe default
response body; no exception propagates.

**TC13 — Connection closes cleanly**
Verify: active connection count does not grow after repeated calls (connections
are closed in `finally`).

**TC14 — Invalid input**
`{ "dashboard_type": "not_real" }`
Verify: falls back to the overview dashboard rather than erroring.

**TC15 — `is_contributor` not yet in DB (graceful degradation)**
Run against a database where the `is_contributor` column does not exist.
Verify: core metrics (totals, types, sizes, collaborator, ratings, trends)
return correctly; only `contributor_organizations` / `non_contributor_organizations`
(0), `contributor_distribution` (`[]`), and `top_contributor_organizations` (`[]`)
are blank. No crash, no zeroing of unrelated metrics. (Manually verified;
populates automatically once `ddl_add_is_contributor.sql` is applied.)

## Acceptance Criteria checklist

- [ ] `organization_overview` and `organization_performance` return with all required keys
- [ ] `7D`, `30D`, `1Y`, `CUSTOM`, `ALL` time filters work correctly
- [ ] Trend groups by `daily` / `weekly` / `monthly` / `yearly` as requested
- [ ] `org_type`, `org_size`, `state_id`, `city_name`, `org_rating`, `is_collaborator`, `is_contributor` filters each work
- [ ] Filter combinations apply together correctly
- [ ] `rating_distribution` covers 1..5; `top_n` respected; no unrated org in top-rated
- [ ] Cross-metric consistency (collaborator/contributor/rated splits sum to total)
- [ ] Safe default response returned when data is unavailable
- [ ] No crash on empty / zero-match data
- [ ] Database connection closes cleanly after execution
- [ ] Degrades gracefully if `is_contributor` column is absent (core metrics unaffected)

The first ten boxes are exercised by the 24 automated assertions; the last is
manually verified against a column-less database (see TC15).