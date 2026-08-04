# Organization Analytics API (#228)

Analytics API for the Organization dashboard, backed by
`virginia_dev_saayam_rdbms.organizations`. Follows the same conventions as the
existing analytics lambdas (`kpi_api_analytics.py`, `volunteer_application_analytics.py`):
`RealDictCursor`, a `build_response()` helper with CORS headers, and SSM
JSON-blob credentials with `sslmode="require"` when deployed.

## Endpoints

One handler routes on `dashboard_type` (the issue's "one endpoint with a
dashboard type" option):

```
POST /analytics/organizations   { "dashboard_type": "overview" | "performance", ... }
```

Thin wrappers are also exported if the team prefers two separate lambdas:
`overview_handler` and `performance_handler` for
`POST /analytics/organizations/overview` and `.../performance`.

## Request filters (common to both dashboards)

```json
{
  "dashboard_type": "overview",
  "time_filter": "30D",        // 7D | 30D | 1Y | ALL | CUSTOM
  "start_date": null,           // used only with CUSTOM
  "end_date": null,
  "org_type": null,             // "non_profit" | "for_profit"
  "org_size": null,             // "small" | "medium" | "large"
  "state_id": null,
  "city_name": null,
  "org_rating": null,           // 1..5
  "is_collaborator": null,      // true | false
  "is_contributor": null,       // true | false
  "group_by": "daily",          // daily | weekly | monthly | yearly (trend)
  "top_n": 10                   // size of the "top" lists (performance)
}
```

## Local testing (no AWS)

```bash
# 1. create + seed a local DB
createdb saayam_local
psql -d saayam_local -f local_setup.sql

# 2. point the code at it
export LOCAL_DB=true
export DB_SCHEMA=virginia_dev_saayam_rdbms   # set to "public" if your CSVs live there
export LOCAL_DB_NAME=saayam_local
export LOCAL_DB_USER=postgres
export LOCAL_DB_PASSWORD=postgres
export LOCAL_DB_HOST=localhost
export LOCAL_DB_PORT=5432

# 3. run the built-in demo, or the assertion tests
python organization_analytics.py
python test_organization_analytics_local.py     # 19 assertions
```

`local_setup.sql` seeds 20 organizations spanning every type, size, rating
(including unrated), collaborator/contributor flag (including NULL), state,
city, and registration date, so every metric and filter is exercised.
`sample_response_overview_30D.json` and `sample_response_performance_ALL.json`
are captured outputs from this seed.

## Design decisions / open questions for review

1. **`is_contributor` column.** Per the issue, `is_contributor` is an
   officially added field that is **not yet present in the current database**.
   `ddl_add_is_contributor.sql` adds it (mirroring `is_collaborator`) and should
   be raised as a **separate PR against `saayam-for-all/database`**. Until then,
   the API degrades gracefully: it runs each metric independently (autocommit),
   so if the column is absent, only the contributor summary fields, the
   `contributor_distribution`, and `top_contributor_organizations` stay empty —
   every other metric (totals, types, sizes, collaborator, ratings, trends)
   returns normally. Once the migration is applied, contributor metrics populate
   automatically with no code change.
2. **"Top collaborator / top contributor" = highest-rated flagged orgs.** There
   is no interaction-count column, so "top" is defined as flagged orgs ordered
   by `org_rating DESC`. Confirm this is the intended ranking.
3. **NULL boolean handling.** `non_collaborator` / `non_contributor` count NULL
   as "not true" (`IS DISTINCT FROM TRUE`). Confirm vs. excluding NULLs.
4. **Location covers state and city.** `organizations_by_location` is the state
   breakdown (joined to `state`); `organizations_by_city` is added so the
   required "City" metric is covered too.
5. **State table name.** Uses `state` (singular), matching `ddl_state.sql` and
   `volunteer_application_analytics.py`. The FK in `ddl_organizations.sql`
   references `states` (plural) — likely a DDL typo worth flagging.

## Files

| File | Purpose |
|---|---|
| `organization_analytics.py` | The API (goes in `data-analytics/lambda_functions/`) |
| `local_setup.sql` | Create schema + tables + seed for local testing |
| `ddl_add_is_contributor.sql` | Migration to add `is_contributor` (separate DB PR) |
| `test_organization_analytics_local.py` | 19 assertion-based local tests |
| `sample_response_overview_30D.json` | Captured sample output |
| `sample_response_performance_ALL.json` | Captured sample output |