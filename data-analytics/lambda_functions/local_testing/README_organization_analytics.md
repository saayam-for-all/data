# Organization Dashboard API (#228 — updated spec)

Single-endpoint analytics API for the Organization Dashboard's three UI tabs,
backed by `virginia_dev_saayam_rdbms.organizations` and `...states`.

**This replaces the earlier two-endpoint (`overview`/`performance`) version.**
The task was updated to a single flat response, different filters, and formal
Development & Testing Requirements; see "What changed" at the bottom.

## Endpoint

```
POST /analytics/organizations
```
One response populates all three dashboard tabs (Growth & Location, Size &
Contribution, Ratings & Type).

## Request filters

```json
{
  "time_filter": "30D",     // 7D | 30D | 1Y | ALL | CUSTOM
  "start_date": null,        // required with CUSTOM
  "end_date": null,
  "group_by": "daily",       // daily | weekly | monthly | yearly
  "region": "ALL",           // "ALL" or a state name/id, e.g. "California"
  "organization_type": "ALL" // "ALL" | "non_profit" | "for_profit"
}
```

No other filters are introduced, per the issue's instruction to reuse the
existing common filtering behavior.

## Credentials — no AWS Parameter Store

Per the issue, this file does **not** use SSM/Parameter Store anywhere.
Credentials come from environment variables only:

```
DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT, DB_SSLMODE (optional)
```
(`LOCAL_DB_*` variants are also accepted as a fallback, purely for
convenience if you're re-using an earlier local setup.)

## Testing (two suites, both included)

**1. Cursor-mocked unit tests — no database required.**
`local_testing/test_organization_analytics_unit_mock.py` mocks the DB cursor
directly (`unittest.mock`), so it runs with zero DB configuration. 18 tests,
covering every item in the Development & Testing Requirements:
- Valid filters (region, organization_type, custom dates) — and confirms
  filter values are passed as bound `%s` parameters, never inlined into the
  SQL string (parameterized-query check)
- Invalid filters (garbage `time_filter`/`group_by` fall back to safe
  defaults; a nonsense `region`/`organization_type` matches zero rows rather
  than crashing)
- Custom date ranges (both dates present vs. one/none missing)
- Empty result sets (every field returns a safe zero/empty value — including
  the fixed-size buckets that must still appear at 0)
- Database/query exceptions (a failing single query degrades only that one
  field to defaults, status stays 200; a failing connection returns 500 with
  the full default body; cursor/connection are always closed, even on error)
- Response structure validation against every field in the acceptance
  criteria (4 KPI cards, growth trend fields, location state+city, exactly
  small/medium/large, exactly collaborator+contributor, exactly ratings 1-5,
  type-trend fields)

Run:
```bash
python -m unittest local_testing.test_organization_analytics_unit_mock -v
```

**2. Integration tests — against a local Postgres with the real sample data.**
`local_testing/test_organization_analytics_local.py`, 24 tests, run against
the actual `organizations.csv`/`state.csv` referenced by the issue (see setup
below). Confirms real end-to-end behavior: real `org_type` value normalization
("Non-Profit" → `non_profit`), real NULL-rating handling, real region/type
filtering, real DB-unavailable degradation.

```bash
createdb saayam_local
psql -d saayam_local -f local_testing/local_setup_schema.sql
psql -d saayam_local -c "\copy virginia_dev_saayam_rdbms.states(state_id,country_id,state_name,state_code,last_update_date) FROM 'local_testing/state.csv' WITH (FORMAT csv, HEADER true)"
psql -d saayam_local -c "\copy virginia_dev_saayam_rdbms.organizations(org_id,org_name,street,city_name,state_id,zip_code,mission,web_url,phone,email,org_type,org_size,org_rating,is_collaborator,is_contributor,created_at,last_updated_at) FROM 'local_testing/organizations.csv' WITH (FORMAT csv, HEADER true)"

export DB_HOST=localhost DB_PORT=5432 DB_NAME=saayam_local DB_USER=postgres DB_PASSWORD=postgres
export DB_SCHEMA=virginia_dev_saayam_rdbms
export PYTHONPATH="."

python organization_analytics.py
python local_testing/test_organization_analytics_local.py
```

`organizations.csv` and `state.csv` in `local_testing/` are the **real sample
files** linked from the issue (`data-analytics/sql/organizations.csv` and
`data-analytics/sql/state.csv`), not synthetic data.

The 5 sample-payload responses from the issue are captured as
`sample_response_*.json` in `local_testing/`, generated from this real data.

**Total: 42 passing assertions (18 mock + 24 integration), no AWS used anywhere.**

## Design decisions / notes for the reviewer

1. **Table name: `states` vs `state`.** The issue text says
   `virginia_dev_saayam_rdbms.states` (plural). The actual CSV file in the
   repo is named `state.csv` (singular), matching the earlier `ddl_state.sql`
   convention. This implementation creates the table as `states` (plural),
   following the issue's explicit text. Please confirm which the real Aurora
   schema actually uses — if it's `state` (singular), only the `states` string
   in `BASE_FROM` needs to change.
2. **`org_type` value format.** The real `organizations.csv` stores
   `"Non-Profit"` / `"For-profit"` (mixed case, hyphenated), while the issue's
   filter examples pass `"non_profit"` (snake_case). The code normalizes both
   sides for comparison (case-insensitive, hyphens/spaces → underscores) and
   always returns the snake_case form in responses, matching the issue's
   example JSON.
3. **`is_contributor` not yet in the live DB.** Per the issue's note, this
   column may be missing from the current database. The connection runs in
   autocommit mode and every metric query is wrapped independently, so if the
   column is absent, only `total_contributors` and the "contributor" entry in
   `collaborator_vs_contributor` degrade to 0 — every other metric is
   unaffected. (The real sample CSV already includes the column, so this is a
   forward-looking safeguard, verified by dropping the column and re-running
   the manual checks.)
4. **`collaborator_vs_contributor` is not mutually exclusive.** An
   organization can be both a collaborator and a contributor (or neither), so
   the two counts do not need to sum to `total_organizations` — this matches
   the issue's model (`is_collaborator` and `is_contributor` are independent
   booleans), unlike the earlier version's collaborator/non-collaborator split.
5. **`growth_trend` and `organization_type_distribution` count per-period
   registrations** (organizations created within each period), not a running
   cumulative total. The issue's example values increase period-over-period,
   which is consistent with either interpretation on that specific sample —
   flagging the assumption in case cumulative was intended.
6. **`organizations_by_location` now includes both state and city**, grouped
   by state+city combination, satisfying the acceptance criterion
   "Organizations by Location supports state/city data" while staying inside
   the single `organizations_by_location` key given in the suggested response
   structure (no extra top-level key invented).
7. **`organizations_by_size` always returns exactly 3 buckets** (small,
   medium, large), zero-filled if a size has no matching organizations —
   satisfying "returns Small, Medium, and Large distributions" as an always-
   present set, the same zero-fill pattern used for `rating_distribution`.

## What changed from the first version of this PR

The task was revised after the first implementation was already tested and a
PR (#247) opened. Key differences: one endpoint instead of two, a flat
response instead of nested `organization_overview`/`organization_performance`,
different filters (`region`/`organization_type` instead of
`org_size`/`state_id`/`city_name`/`org_rating`/`is_collaborator`), a
non-mutually-exclusive collaborator/contributor model, a time-series
`organization_type_distribution` instead of a static snapshot, and an explicit
ban on AWS Parameter Store. This version is a full rewrite to match the
updated spec, tested against the real sample CSVs.
