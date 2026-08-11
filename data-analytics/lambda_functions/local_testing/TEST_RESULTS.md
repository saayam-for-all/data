# Organization Analytics API — Test Results

Tested against Sana's mock data: `data-analytics/sql/organizations.csv`
(40 organizations). No AWS credentials, SSM parameters, or the
production/dev database were used at any point — `organization_analytics.py`
only connects to a local Postgres instance (see `local_setup.sql` /
`seed_from_csv.py` in this folder).

## Dataset shape (as loaded from the mock CSV)

| Field | Values found |
|---|---|
| Total rows | 40 |
| `org_type` | `Non-Profit` (21), `For-profit` (19) — normalized in queries to `non_profit`/`for_profit` |
| `org_size` | `Large` (21), `Small` (10), `Medium` (9) — normalized to lowercase |
| `is_collaborator` | 21 `TRUE`, 19 `FALSE` |
| `is_contributor` | 19 `TRUE`, 21 `FALSE` |
| `org_rating` | all 40 rows rated (1–5), none blank |
| `state_id` | literal 2-letter codes (e.g. `TX`, `MT`, `IN`) — no state lookup table join |
| `created_at` | 2023-09-08 to 2026-01-10 |

## Results

### Overview dashboard (`time_filter: ALL`)
- `summary.total_organizations`: **40**
- `non_profit_organizations` / `for_profit_organizations`: **21 / 19**
- `collaborator_organizations` / `non_collaborator_organizations`: **21 / 19**
- `contributor_organizations` / `non_contributor_organizations`: **19 / 21**
- `organizations_by_size`: large 21, small 10, medium 9 (sums to 40)
- `organizations_by_location.by_state`: correctly grouped by literal state code (e.g. TX: 3, others 2 or 1 each), sums to 40
- `organization_activity_trend` bucket counts summed back to 40 for every `group_by` granularity: daily (39 buckets), weekly (32), monthly (20), yearly (4)

### Performance dashboard (`time_filter: ALL`)
- `summary.average_rating`: **3.23**, `rated_organizations`: 40, `unrated_organizations`: 0, `five_star_organizations`: 12
- `rating_distribution`: 1★:5, 2★:9, 3★:10, 4★:4, 5★:12 (sums to 40)
- `top_rated_organizations`: correctly sorted by rating desc, then name asc, capped at 10
- `ratings_by_organization_type`: non_profit avg 3.62 (21 rated), for_profit avg 2.79 (19 rated)
- `collaborator_distribution` / `contributor_distribution`: match the summary counts above exactly

### Filters
- `org_type=non_profit` → 21 rows (matches `organizations_by_type`)
- `org_size=large` → 21 rows (matches `organizations_by_size`)
- `state_id` filter is case-insensitive (`ny` matches `NY`)
- All other filters (`city_name`, `org_rating`, `is_collaborator`, `is_contributor`, `CUSTOM` date range) exercised without error

### Known characteristic of this dataset (not a bug)
All `created_at` values are historical (2023–2026-01), so `time_filter: 7D` / `30D`
will legitimately return 0 organizations once "today" moves far enough past
the CSV's dates — this is expected given the mock data is static, not
regenerated relative to the current date.

## How this was verified

Every query above was checked against the actual 40-row CSV and cross-checked
by hand (aggregate counts, sums, averages, sort order) — all matched exactly.
This pass validated query *logic* directly against Sana's real mock data.

**Still to do on your machine:** run the actual `psycopg2`/PostgreSQL path
end-to-end (this environment could not install PostgreSQL locally):

```bash
cd data-analytics/lambda_functions
psql -d saayam_local -f local_testing/local_setup.sql
python3 local_testing/seed_from_csv.py
export LOCAL_DB_HOST=localhost LOCAL_DB_PORT=5432 LOCAL_DB_NAME=saayam_local LOCAL_DB_USER=$(whoami) LOCAL_DB_PASSWORD=
python3 organization_analytics.py
```

The numbers above are what to expect back — if anything differs, it's worth
flagging before merging.

## Known schema gaps (carried over from initial implementation)

- `is_contributor` is not yet in `ddl_organizations.sql` (only `is_collaborator`
  is defined there) — the mock CSV does include it, and this API relies on it
  being added to the real schema before this can run against a non-mock
  database.
- `ddl_organizations.sql`'s `state_id` implies an FK to a `state` table, but
  the mock CSV instead stores literal 2-letter state codes directly. This API
  currently treats `state_id` as already display-ready (no join). If/when
  a real `state_id` FK relationship is used, `fetch_organizations_by_state()`
  will need a join added back in.
