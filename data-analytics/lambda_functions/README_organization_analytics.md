# Organization Analytics API

Analytics API for the Saayam **Organization Dashboard**, built on
`virginia_dev_saayam_rdbms.organizations` (+ `state` for readable location names).
Implemented as a single AWS Lambda (`organization_analytics.py`) following the same
structure and coding standards as `kpi_api_analytics.py`,
`volunteer_application_analytics.py`, and `beneficiariesTrendAnalysis.py`:

- `psycopg2` + `RealDictCursor`, schema constant `SCHEMA_NAME`
- Per-metric error isolation with a safe default so one failed query never takes
  down the whole dashboard. PostgreSQL aborts the surrounding transaction on error,
  so the connection runs in autocommit and `run_metric()` rolls back after a failure —
  otherwise the *next* metric would fail with `InFailedSqlTransaction` and the
  degradation would cascade instead of staying contained
- `build_response()` with CORS headers, `parse_event_body()` supporting both direct
  invocation and API-Gateway-style stringified bodies
- Parameterized SQL for every user-supplied filter value

## Endpoint

One endpoint populates all three dashboard tabs from a single response:

```
POST /analytics/organizations
```

### Request

```json
{
  "time_filter": "30D",
  "start_date": null,
  "end_date": null,
  "group_by": "daily",
  "region": "ALL",
  "organization_type": "ALL"
}
```

### Response structure

```json
{
  "summary": {
    "total_organizations": 0,
    "total_collaborators": 0,
    "total_contributors": 0,
    "average_org_rating": 0
  },
  "growth_trend": [],
  "organizations_by_location": [],
  "organizations_by_size": [],
  "collaborator_vs_contributor": [],
  "rating_distribution": [],
  "organization_type_distribution": []
}
```

`filters_applied` (echo of the normalized filters) is added for debugging.

## Sections

| Tab | Section | Contents |
|---|---|---|
| KPI cards | `summary` | total organizations, total collaborators, total contributors, average org rating |
| 1 · Growth & Location | `growth_trend` | cumulative `total_organizations` + `total_collaborators` per period (uses `created_at`, grouped by `group_by`) |
| 1 · Growth & Location | `organizations_by_location` | one row per state (`state_id`, `state_name`, `organization_count`, `percentage`) with a nested `cities` array (`city_name`, `organization_count`) — state **and** city in one section |
| 2 · Size & Contribution | `organizations_by_size` | `org_size` (small/medium/large) → `organization_count` |
| 2 · Size & Contribution | `collaborator_vs_contributor` | collaborator vs contributor `organization_count` + `percentage` |
| 3 · Ratings & Type | `rating_distribution` | ratings 1–5, always all five buckets (zero-filled), `organization_count` |
| 3 · Ratings & Type | `organization_type_distribution` | `for_profit` / `non_profit` / `total` per period (stacked bar over time) |

## Filters (common to all sections)

| Filter | Values | Default |
|---|---|---|
| `time_filter` | `7D`, `30D`, `1Y`, `ALL`, `CUSTOM` | `ALL` |
| `start_date` / `end_date` | ISO `YYYY-MM-DD`, required with `CUSTOM` | `null` |
| `region` | `ALL`, a state id (`TX`) **or** a state name (`Texas`), case-insensitive | `ALL` |
| `organization_type` | `ALL`, `non_profit`, `for_profit` | `ALL` |
| `group_by` | `daily`, `weekly`, `monthly`, `yearly` (affects the two time-series sections) | `daily` |

Unknown `time_filter` / `group_by` values are sanitized to defaults; `region` and
`organization_type` of `"ALL"` mean "no filter". Requests that cannot be honoured
return `400`: `time_filter=CUSTOM` without both dates, non-ISO dates, or
`start_date` later than `end_date`.

## Label normalization (org_type / org_size)

`ddl_organizations.sql` declares both columns as lowercase enums (`non_profit`,
`for_profit`, `small`, `medium`, `large`), but the source extracts in
`data-analytics/sql/organizations.csv` carry display labels (`Non-Profit`,
`For-profit`, `Small`). Matching on the raw value would silently report **0** for a
bucket wherever the labelled form is stored. Both sides are therefore normalized —
the SQL applies `REPLACE(LOWER(column::text), '-', '_')`, and incoming
`organization_type` filter values go through the same transform. `Non-Profit`,
`non profit`, and `NON_PROFIT` all resolve to `non_profit`.

## Database credentials

**No AWS Parameter Store / SSM, and no `boto3`.** The task forbids Parameter Store,
so the Lambda connects straight from environment variables — injected by the Lambda
configuration in deployment, or exported locally:

| Env var | Purpose | Default |
|---|---|---|
| `DB_HOST` | Database host | `localhost` |
| `DB_NAME` | Database name | `saayam_local` |
| `DB_USER` | Database user | `saayam` |
| `DB_PASSWORD` | Database password | `saayam_local` |
| `DB_PORT` | Database port | `5432` |
| `DB_SSLMODE` | psycopg2 sslmode (e.g. `require`); passed only when set | *(unset)* |

No credential value or Parameter Store path is hard-coded anywhere — the test suite
asserts the source contains no `boto3`/SSM reference and no `/…/saayam/…` path literal.

## Schema note — `is_contributor`

`ddl_organizations.sql` currently has `is_collaborator` but the analytics spec also
needs `is_contributor`. Two things handle this:

1. `ddl_add_is_contributor.sql` — migration to be raised as a companion PR against
   `saayam-for-all/database` (same pattern as the earlier collaborator-flag change).
2. The Lambda detects the column at runtime via `information_schema.columns`. When it
   is missing, `total_contributors` and the contributor row return `0`, and the
   response carries a `schema_notes` entry explaining why. Every other metric is
   unaffected — so this deploys safely against the current dev DB and lights up
   automatically once the migration lands.

## Tests

Two suites:

- **`test_organization_analytics_unit.py`** — cursor-based / **mock-database** unit
  tests. No PostgreSQL and no AWS required: the DB layer is replaced with a fake
  cursor returning canned rows. Covers the happy path, **empty result sets**,
  invalid/sanitized filters, custom-date validation (`400`), DB-exception → `500`,
  per-metric failure isolation, and `is_contributor` degradation. Run with
  `pytest test_organization_analytics_unit.py` or plain `python
  test_organization_analytics_unit.py`.
- **`test_organization_analytics_local.py`** — end-to-end suite against a local
  PostgreSQL loaded with the real extracts (below).

### Local end-to-end run

```bash
# 1. PostgreSQL schema + tables
psql -d saayam_local -f organization_analytics_local_setup.sql

# 2a. Load the real source extracts (../sql/organizations.csv, ../sql/state.csv)
python3 organization_analytics_load_csv.py

# 2b. Optional: 120 synthetic organizations for denser recent-window coverage
python3 organization_analytics_seed_data.py

# 3. Run the API locally (DB_* env vars, defaults connect to saayam_local)
python3 organization_analytics.py

# 4. End-to-end test suite (works against either dataset)
python3 test_organization_analytics_local.py

# 5. Regenerate the committed sample responses
python3 organization_analytics_generate_samples.py
```

The end-to-end suite probes the loaded data for a state, size and rating that
actually exist before asserting on them, so it is valid against the real extract
and the synthetic seed alike.

## Sample responses

Generated from the 40-row real extract (`../sql/organizations.csv` + `state.csv`),
in `organization_analytics_samples/`:

| File | Scenario |
|---|---|
| `sample_response_ALL_monthly.json` | full history, all sections populated (40 orgs) |
| `sample_response_30D_daily.json` | issue "Standard Test" payload — empty recent window, shows empty-set handling |
| `sample_response_1Y_monthly.json` | last 12 months (11 orgs) |
| `sample_response_ALL_region_texas.json` | `region` filter (Texas) |
| `sample_response_ALL_nonprofit.json` | `organization_type=non_profit` filter (21 orgs) |
| `sample_response_custom_range.json` | `CUSTOM` range 2024-01-01 → 2024-12-31 (15 orgs) |
