# Organization Analytics API

Analytics API for the Saayam dashboard built on `virginia_dev_saayam_rdbms.organizations`
(+ `state` for location names). Implemented as a single AWS Lambda
(`organization_analytics.py`) following the same structure and coding standards as
`kpi_api_analytics.py`, `volunteer_application_analytics.py`, and
`beneficiariesTrendAnalysis.py` in `data-analytics/lambda_functions/`:

- `psycopg2` + `RealDictCursor`, schema constant `SCHEMA_NAME`
- DB credentials from SSM parameter `/dev/saayam/db/Virginia/Analytics/user`
  (with a `LOCAL_DB=true` env override for local PostgreSQL testing — no AWS needed)
- Per-metric `try/except` with safe default response so one failed query never
  takes down the whole dashboard
- `build_response()` with CORS headers, `parse_event_body()` supporting both
  direct invocation and API-Gateway-style stringified bodies
- Parameterized SQL for every user-supplied filter value

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
| `start_date` / `end_date` | ISO dates, used with `CUSTOM` | `null` |
| `org_type` | `non_profit`, `for_profit` | `null` |
| `org_size` | `small`, `medium`, `large` | `null` |
| `state_id` | e.g. `ST-NY` | `null` |
| `city_name` | case-insensitive match | `null` |
| `org_rating` | 1–5 | `null` |
| `is_collaborator` / `is_contributor` | boolean | `null` |
| `group_by` | `daily`, `weekly`, `monthly`, `yearly` | `daily` |

Invalid values are sanitized to defaults; invalid `dashboard_type` returns 400.

## Dashboard 1 — Overview

`summary` (total / non-profit / for-profit / collaborator / non-collaborator /
contributor / non-contributor counts), `organization_activity_trend`
(new + cumulative registrations per period via `DATE_TRUNC`),
`organizations_by_type`, `organizations_by_size`, `organizations_by_location`
(state + city), `collaborator_distribution`, `contributor_distribution`.

## Dashboard 2 — Performance

`summary` (average rating, rated/unrated, five-star count), `rating_distribution`
(1–5), `top_rated_organizations` (top 10), `top_collaborator_organizations`,
`top_contributor_organizations`, `ratings_by_organization_type`,
`ratings_by_organization_size`.

## Schema note — `is_contributor` (needs reviewer decision)

`ddl_organizations.sql` currently has `is_collaborator` but **no `is_contributor`
column**, which the spec requires. Included `ddl_add_is_contributor.sql` as a
migration (same pattern as the earlier collaborator-flag change). A companion PR
against `saayam-for-all/database` is needed before deploying this Lambda to dev.

Also noted while reading the DDL: the FK in `ddl_organizations.sql` references
`states(state_id)` but `ddl_state.sql` creates the table as `state` — this API
joins on `state` to match the actual table definition.

## Local setup & testing

```bash
# 1. PostgreSQL schema + tables
psql -d saayam_local -f local_setup.sql

# 2. Seed 120 mock organizations
python3 seed_mock_data.py

# 3. Run the API locally
LOCAL_DB=true python3 organization_analytics.py

# 4. Full test suite
LOCAL_DB=true python3 test_organization_analytics_local.py
```

## Test results

**39/39 checks passed** on local PostgreSQL 16 with 120 seeded organizations:

- Both dashboards return 200 with the full suggested response structure
- Cross-metric consistency: collaborator + non-collaborator = total; contributor +
  non-contributor = total; type/size/location distributions each sum to total;
  rating distribution sums to rated count; five-star summary matches distribution;
  cumulative trend total matches summary total
- Time filters monotonic (7D=2 ≤ 30D=14 ≤ 1Y=105 ≤ ALL=120); CUSTOM range works
- Every dimension filter verified (org_type, org_size, state_id, case-insensitive
  city_name, org_rating, is_collaborator, is_contributor)
- All four `group_by` granularities produce correct bucket counts
  (daily=94, weekly=48, monthly=13, yearly=2 over 1Y window)
- Invalid `dashboard_type` → 400; invalid filter values sanitized → 200
- API-Gateway-style stringified body parsed correctly

Sample responses: `sample_response_overview_30D.json`,
`sample_response_overview_ALL_monthly.json`, `sample_response_performance_ALL.json`,
`sample_response_performance_filtered_nonprofit_NY.json`.
