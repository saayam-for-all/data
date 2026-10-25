# Organization Analytics API — implementation notes

`POST /analytics/organizations` → `data-analytics/lambda_functions/organization_analytics.py`

One request populates all three Organization Dashboard tabs plus the four common
KPI cards.

## Files

| File | Purpose |
|------|---------|
| `lambda_functions/organization_analytics.py` | The Lambda |
| `lambda_functions/tests/test_organization_analytics.py` | 102 mock-cursor unit tests (no DB required) |
| `lambda_functions/load_organizations.py` | Loads `sql/organizations.csv` + `sql/state.csv` into local Postgres |
| `lambda_functions/run_local_org_tests.py` | Live-DB harness; compares handler output to independent SQL |

## Request

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

| Field | Values | Default |
|-------|--------|---------|
| `time_filter` | `7D`, `30D`, `1Y`, `ALL`, `CUSTOM` (case-insensitive) | `ALL` |
| `group_by` | `daily`, `weekly`, `monthly`, `yearly` | `monthly` |
| `start_date` / `end_date` | `YYYY-MM-DD`; both required when `CUSTOM`, `end_date` inclusive | `null` |
| `region` | `ALL` or a state code such as `TX` (case-insensitive) | `ALL` |
| `organization_type` | `ALL`, `for_profit`, `non_profit` | `ALL` |

Invalid filters return **400** with an `error` message and an otherwise empty but
structurally valid body. Database failures return **500** with the same empty
body, so the dashboard degrades instead of breaking.

## Behaviour decisions

These were not derivable from the issue description and were confirmed before
implementation. Each is marked with a `DECISION:` comment in the source.

| Decision | Choice |
|---|---|
| Filter contract | The issue's sample payloads (`time_filter`/`group_by`/`region`/`organization_type`, flat response). This differs from the older KPI/volunteer lambdas, which take `time_range` and key the response by range. |
| DB credentials | Environment variables only (`PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD`/`PGSSLMODE`). No AWS Parameter Store, no `boto3` import. |
| Filter scope | Date range, region and organization type apply to **every** section, KPI cards included. |
| Growth trend | Cumulative running totals within the filtered window (matches the `100 → 108` example). Same for `organization_type_distribution`. |
| Percentages | Denominator is the filtered organization total; rounded to 1 decimal. |
| `region` | Matched against `organizations.state_id` (two-letter code). See Open question below. |
| Weekly / yearly labels | ISO week `2026-W03` and `2026`. |
| `is_contributor` | Detected via `information_schema` per request. When absent, `total_contributors` is `0` and the `contributor` row is omitted rather than reported as a real zero. |
| Value casing | `org_type` and `org_size` are normalised in SQL (`Non-Profit` → `non_profit`, `Small` → `small`), so a casing change in the DB cannot break the API. |
| Region scope | Virginia always; Ireland is queried and merged only when `IRELAND_PGHOST` is set. Trends are merged as per-period counts and cumulated afterwards, so a period present in only one region still accumulates correctly. |
| NULL ratings | Excluded from `average_org_rating` and from the 1–5 buckets rather than counted as zero. `average_org_rating` is `0.0` only when nothing is rated. |
| Fixed-domain charts | `organizations_by_size` always returns small/medium/large and `rating_distribution` always returns 1–5, zero-filled, so chart axes stay stable on empty result sets. |
| City data | Nested inside each state entry as `cities: [{city_name, organization_count}]`; the documented state-level fields are unchanged. |

## Running locally

```bash
brew services start postgresql@16             # if not already running
createdb saayam_local

cd data-analytics/lambda_functions
python load_organizations.py ../sql          # add --ireland to exercise the merge path
python run_local_org_tests.py                # live-DB validation
cd tests
pip install -r requirements-dev.txt
python -m pytest test_organization_analytics.py -q               # unit tests, no DB needed
```

Expect **102 passed**. If you see `60 passed, 42 skipped`, `pglast` is missing —
the 42 skips are the PostgreSQL grammar checks, one per generated query. They
skip gracefully rather than failing, so install it (`pip install pglast`) to get
that coverage.

Run the unit tests by filename. A bare `pytest -q` in `tests/` aborts during
collection because `test_additional_request_details.py` imports
`additional_request_details`, which lives on branch `pranavrd_issue_203` and is
not present here. That is unrelated to this PR; `--ignore
=test_additional_request_details.py` also works.

`PGUSER` defaults to your OS username, which is what Homebrew and Postgres.app
create — they do not create a `postgres` role. Set `PGUSER` explicitly if your
server does have one. Other overrides: `PGHOST`, `PGPORT`, `PGDATABASE`,
`PGPASSWORD`.

Note that `tests/conftest.py` (from the `req_add_info` work) still defaults
`PGUSER` to `postgres` and will skip its DB-backed tests on a Homebrew install
unless `PGUSER` is exported. That is pre-existing and outside this PR.

`load_organizations.py --drop-is-contributor` reproduces a development database
that predates the `is_contributor` column.

## Test results

**Unit tests — 102 passed** (`tests/test_organization_analytics.py`), covering
filter validation, all four groupings, custom ranges, empty result sets, NULL
handling, the missing `is_contributor` column, connection and query failures,
multi-region merge, and parameterisation. Every generated query is additionally
parsed with `pglast` (the real PostgreSQL grammar) to catch syntax errors
without a live server.

**Data validation.** Handler output was executed against `sql/organizations.csv`
(40 rows) and `sql/state.csv` (51 rows) and compared to ground truth computed
independently with pandas — all checks passed:

- summary KPIs, size, rating, location and type distributions match independent counts
- location counts sum to the total; percentages sum to 100; nested city counts sum to their state
- growth trend is monotonic and its final period equals `total_organizations`
- all four `group_by` values produce well-formed labels and reach the same total
- `CUSTOM` ranges are inclusive of `end_date`; a single-day range works
- empty windows, all-NULL ratings, NULL state/city, and a dropped `is_contributor` column all return 200

## Sample responses

Generated from the sample CSVs. Long arrays truncated.

### All time

Request `{"time_filter": "ALL", "group_by": "monthly", "region": "ALL", "organization_type": "ALL"}` → **200**

```json
{
  "summary": {
    "total_organizations": 40,
    "total_collaborators": 21,
    "total_contributors": 19,
    "average_org_rating": 3.2
  },
  "growth_trend": [
    {"period": "2023-09", "total_organizations": 2, "total_collaborators": 1},
    {"period": "2023-11", "total_organizations": 3, "total_collaborators": 2}
  ],
  "organizations_by_location": [
    {
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 3,
      "percentage": 7.5,
      "cities": [
        {"city_name": "East Jenniferfort", "organization_count": 1},
        {"city_name": "Hortonberg", "organization_count": 1},
        {"city_name": "Victoriaport", "organization_count": 1}
      ]
    }
  ],
  "organizations_by_size": [
    {"org_size": "small", "organization_count": 10},
    {"org_size": "medium", "organization_count": 9},
    {"org_size": "large", "organization_count": 21}
  ],
  "collaborator_vs_contributor": [
    {"type": "collaborator", "organization_count": 21, "percentage": 52.5},
    {"type": "contributor", "organization_count": 19, "percentage": 47.5}
  ],
  "rating_distribution": [
    {"rating": 1, "organization_count": 5},
    {"rating": 2, "organization_count": 9},
    {"rating": 3, "organization_count": 10},
    {"rating": 4, "organization_count": 4},
    {"rating": 5, "organization_count": 12}
  ],
  "organization_type_distribution": [
    {"period": "2023-09", "for_profit": 1, "non_profit": 1, "total": 2},
    {"period": "2023-11", "for_profit": 1, "non_profit": 2, "total": 3}
  ]
}
```

### Filter by region

Request `{"time_filter": "ALL", "group_by": "monthly", "region": "TX", "organization_type": "ALL"}` → **200**

```json
{
  "summary": {
    "total_organizations": 3,
    "total_collaborators": 1,
    "total_contributors": 2,
    "average_org_rating": 2.0
  },
  "organizations_by_location": [
    {"state_id": "TX", "state_name": "Texas", "organization_count": 3, "percentage": 100.0,
     "cities": [{"city_name": "East Jenniferfort", "organization_count": 1},
                {"city_name": "Hortonberg", "organization_count": 1},
                {"city_name": "Victoriaport", "organization_count": 1}]}
  ],
  "collaborator_vs_contributor": [
    {"type": "collaborator", "organization_count": 1, "percentage": 33.3},
    {"type": "contributor", "organization_count": 2, "percentage": 66.7}
  ]
}
```

### Filter by organization type

Request `{"time_filter": "1Y", "group_by": "monthly", "region": "ALL", "organization_type": "non_profit"}` → **200**

```json
{
  "summary": {
    "total_organizations": 8,
    "total_collaborators": 4,
    "total_contributors": 4,
    "average_org_rating": 3.0
  },
  "organizations_by_size": [
    {"org_size": "small", "organization_count": 1},
    {"org_size": "medium", "organization_count": 1},
    {"org_size": "large", "organization_count": 6}
  ],
  "organization_type_distribution": [
    {"period": "2025-09", "for_profit": 0, "non_profit": 2, "total": 2},
    {"period": "2025-10", "for_profit": 0, "non_profit": 3, "total": 3}
  ]
}
```

### Custom date range

Request `{"time_filter": "CUSTOM", "start_date": "2026-01-01", "end_date": "2026-06-30", "group_by": "monthly", "region": "ALL", "organization_type": "ALL"}` → **200**

```json
{
  "summary": {
    "total_organizations": 1,
    "total_collaborators": 0,
    "total_contributors": 1,
    "average_org_rating": 1.0
  },
  "growth_trend": [{"period": "2026-01", "total_organizations": 1, "total_collaborators": 0}],
  "collaborator_vs_contributor": [
    {"type": "collaborator", "organization_count": 0, "percentage": 0.0},
    {"type": "contributor", "organization_count": 1, "percentage": 100.0}
  ]
}
```

### Invalid filter

Request `{"time_filter": "CUSTOM", "start_date": null, "end_date": null, ...}` → **400**

```json
{
  "summary": {"total_organizations": 0, "total_collaborators": 0, "total_contributors": 0, "average_org_rating": 0.0},
  "growth_trend": [],
  "organizations_by_location": [],
  "organizations_by_size": [],
  "collaborator_vs_contributor": [],
  "rating_distribution": [],
  "organization_type_distribution": [],
  "error": "start_date and end_date are both required when time_filter is CUSTOM."
}
```

> The sample CSV's newest `created_at` is 2026-01-10, so `7D` and `30D` return
> zeros against it. That is the data, not a defect — `run_local_org_tests.py`
> derives its windows from the actual `created_at` range for this reason.

## Open questions for review

1. **`region` value format.** This implementation matches `state_id` (`"TX"`).
   The issue's third sample payload sends `"region": "California"`, which returns
   0 organizations under state-code matching. Either the sample payload should
   read `"CA"`, or the filter should also accept `state_name`. Confirm which,
   and I'll adjust in one line.
2. **Filter contract divergence.** The org API uses `time_filter`/`group_by`;
   the KPI and volunteer lambdas use `time_range` with a range-keyed response.
   If the intent is one shared filter contract across dashboards, that is a
   separate refactor of the existing lambdas, not something this PR should do
   unilaterally.
3. **No shared filter module exists.** `get_grouping` / `build_date_filter` are
   currently copy-pasted per lambda and already disagree with each other (`All`
   means "last 2 years" in `kpi_api_analytics.py` and "no limit" in
   `volunteer_application_analytics.py`). Worth extracting into a shared helper
   as follow-up work.
4. **Ireland organizations.** The merge path is implemented and unit-tested but
   has never run against real Ireland data — the issue names only the Virginia
   tables and no Ireland sample data exists.
5. **Dashboard UI reference.** The issue says "Refer Dashboard UI -" with
   nothing after it. A mockup would confirm the city breakdown shape and whether
   the growth trend is meant to be cumulative.
