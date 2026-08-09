# Organization Analytics API

Analytics API for the Saayam dashboard built on `virginia_dev_saayam_rdbms.organizations`
(+ `state` for location names). Implemented as a single AWS Lambda
(`organization_analytics.py`) following the same structure and coding standards as
`kpi_api_analytics.py`, `volunteer_application_analytics.py`, and
`beneficiariesTrendAnalysis.py` in `data-analytics/lambda_functions/`:

- `psycopg2` + `RealDictCursor`, schema constant `SCHEMA_NAME`
- Per-metric error isolation with a safe default response so one failed query never
  takes down the whole dashboard. PostgreSQL aborts the surrounding transaction on
  error, so the connection runs in autocommit and `run_metric()` rolls back after a
  failure — otherwise the *next* metric would fail with `InFailedSqlTransaction` and
  the degradation would cascade instead of staying contained
- `build_response()` with CORS headers, `parse_event_body()` supporting both
  direct invocation and API-Gateway-style stringified bodies
- Parameterized SQL for every user-supplied filter value

## Label normalization (org_type / org_size)

`ddl_organizations.sql` declares both columns as lowercase enums
(`non_profit`, `for_profit`, `small`, `medium`, `large`), but the source extracts
in `data-analytics/sql/organizations.csv` carry display labels (`Non-Profit`,
`For-profit`, `Small`). Matching on the raw value would silently report **0** for
every type bucket wherever the labelled form is stored.

Both sides are therefore normalized — the SQL applies
`REPLACE(LOWER(column::text), '-', '_')`, and incoming filter values go through the
same transform. `Non-Profit`, `non profit`, and `NON_PROFIT` all resolve to
`non_profit`, and the API always reports the enum form so the dashboard keys stay
stable regardless of how a given environment stores the data.

## Database credentials

**No Parameter Store path appears anywhere in the code.** The Lambda reads the
parameter *name* from an environment variable and resolves it at runtime:

| Env var | Purpose |
|---|---|
| `DB_CREDENTIALS_PARAMETER` | Parameter Store name holding the analytics DB credentials JSON |
| `AWS_REGION` | Region for the SSM client (defaults to `us-east-1`) |
| `LOCAL_DB=true` | Bypasses SSM entirely and connects to local PostgreSQL |
| `DB_HOST` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_PORT` | Local connection overrides |

If `DB_CREDENTIALS_PARAMETER` is unset outside local mode, the handler raises a
clear configuration error instead of falling back to a hard-coded path.

## Endpoint

Single endpoint with a dashboard selector (the alternative suggested in the task):

```
POST /analytics/organizations
{ "dashboard_type": "overview" | "performance", ...filters }
```

## Filters (both dashboards)

| Filter | Values | Default |
|---|---|---|
| `time_filter` | `7D`, `30D`, `1Y`, `ALL`, `CUSTOM` | `ALL` |
| `start_date` / `end_date` | ISO `YYYY-MM-DD`, required with `CUSTOM` | `null` |
| `org_type` | `non_profit`, `for_profit` | `null` |
| `org_size` | `small`, `medium`, `large` | `null` |
| `state_id` | two-letter id as in `state.csv`, e.g. `NY` | `null` |
| `city_name` | case-insensitive match | `null` |
| `org_rating` | 1–5 | `null` |
| `is_collaborator` / `is_contributor` | boolean | `null` |
| `group_by` | `daily`, `weekly`, `monthly`, `yearly` | `daily` |

Unknown values for `time_filter`, `group_by` and out-of-range `org_rating` are
sanitized to defaults. Requests that cannot be honoured return `400`:

- invalid `dashboard_type`
- `time_filter=CUSTOM` without both `start_date` and `end_date`
- dates that are not ISO `YYYY-MM-DD`, or `start_date` later than `end_date`

## Dashboard 1 — Overview

`summary` (total / non-profit / for-profit / collaborator / non-collaborator /
contributor / non-contributor counts), `organization_activity_trend`
(new + cumulative registrations per period via `DATE_TRUNC`),
`organizations_by_type`, `organizations_by_size`, `organizations_by_location`
(state + city), `collaborator_distribution`, `contributor_distribution`.

## Dashboard 2 — Performance

`summary` (average rating, rated/unrated, five-star count), `rating_distribution`
(always all five buckets 1–5, zero-filled via `generate_series` so the chart never
loses a bar), `top_rated_organizations` (top 10), `top_collaborator_organizations`,
`top_contributor_organizations`, `ratings_by_organization_type`,
`ratings_by_organization_size`.

## Schema note — `is_contributor`

`ddl_organizations.sql` currently has `is_collaborator` but **no `is_contributor`
column**, which the spec requires. Two things handle this:

1. `ddl_add_is_contributor.sql` — migration to be raised as a companion PR against
   `saayam-for-all/database` (same pattern as the earlier collaborator-flag change).
2. The Lambda detects the column at runtime via `information_schema.columns`. When
   it is missing, contributor counts return `0`, `contributor_distribution` and
   `top_contributor_organizations` return `[]`, the `is_contributor` filter is
   ignored, and the response carries a `schema_notes` entry explaining why. Every
   other metric is unaffected — so this deploys safely against the current dev DB
   and lights up automatically once the migration lands.

Also noted while reading the DDL: the FK in `ddl_organizations.sql` references
`states(state_id)` but `ddl_state.sql` creates the table as `state` — this API
joins on `state` to match the actual table definition.

## Local setup & testing

```bash
# 1. PostgreSQL schema + tables
psql -d saayam_local -f organization_analytics_local_setup.sql

# 2a. Load the real source extracts (../sql/organizations.csv, ../sql/state.csv)
python3 organization_analytics_load_csv.py

# 2b. Optional: 120 synthetic organizations for denser recent-window coverage
python3 organization_analytics_seed_data.py

# 3. Run the API locally
LOCAL_DB=true python3 organization_analytics.py

# 4. Full test suite (works against either dataset)
LOCAL_DB=true python3 test_organization_analytics_local.py

# 5. Regenerate the committed sample responses
LOCAL_DB=true python3 organization_analytics_generate_samples.py
```

The suite probes the loaded data for a state, city, size and rating that actually
exist before asserting on them, so it is valid against the real extract and the
synthetic seed alike.

## Test results

**57/57 checks passed on both datasets** — the 40-row real extract
(`organizations.csv` + `state.csv`) and the 120-row synthetic seed:

- Both dashboards return 200 with the full suggested response structure
- Cross-metric consistency: collaborator + non-collaborator = total; contributor +
  non-contributor = total; type/size/location distributions each sum to total;
  rating distribution sums to rated count; five-star summary matches distribution;
  cumulative trend total matches summary total
- Real extract: 40 organizations split 21 non-profit / 19 for-profit, 21 collaborators,
  19 contributors, average rating 3.23, 12 five-star — matching the CSV row counts
- Time filters monotonic on both datasets (real extract 7D=0 ≤ 30D=0 ≤ 1Y=11 ≤ ALL=40;
  synthetic seed 7D=2 ≤ 30D=14 ≤ 1Y=105 ≤ ALL=120); CUSTOM range works
- Display labels accepted: `org_type="Non-Profit"` returns the same summary as
  `org_type="non_profit"`, and `org_size="LARGE"` the same as `large`
- CUSTOM rejected with 400 when `end_date` is missing, when a date is not ISO, and
  when `start_date` is after `end_date`
- Every dimension filter verified (org_type, org_size, state_id, case-insensitive
  city_name, org_rating, is_collaborator, is_contributor)
- `rating_distribution` always returns buckets 1–5, including zeros
- All four `group_by` granularities produce correct bucket counts over the 1Y window
  (real extract daily=11, weekly=8, monthly=5, yearly=2)
- Invalid `dashboard_type` → 400; invalid filter values sanitized → 200
- API-Gateway-style stringified body parsed correctly
- No Parameter Store path present in the source (asserted by pattern, so no such
  literal exists in the tests either); missing `DB_CREDENTIALS_PARAMETER` raises a
  clear configuration error
- Failure isolation: with one metric forced to raise a live SQL error, the request
  still returns 200, that section falls back to its default, and every later metric
  on the same connection still returns correct data
- Graceful degradation with `is_contributor` absent: overview and performance still
  return 200, non-contributor metrics unchanged, contributor metrics zero/empty,
  `schema_notes` present, `is_contributor` filter ignored rather than fatal

Sample responses (generated from the real extract):
`sample_response_overview_ALL_monthly.json`,
`sample_response_overview_1Y_daily.json`,
`sample_response_performance_ALL.json`,
`sample_response_performance_filtered_nonprofit_large.json`.
