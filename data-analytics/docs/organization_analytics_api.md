# Organization Analytics API

Single endpoint backing all three tabs of the Organization Dashboard (issue #228).

```http
POST /analytics/organizations
```

Handler: `data-analytics/lambda_functions/organization_analytics.py`
Tests: `data-analytics/lambda_functions/test_organization_analytics.py`

Source tables: `virginia_dev_saayam_rdbms.organizations`, `virginia_dev_saayam_rdbms.state`

---

## Local setup

The handler connects to a **local PostgreSQL** instance through environment
variables. AWS Parameter Store is not used anywhere in this module.

| Variable | Default |
| --- | --- |
| `DB_HOST` | `localhost` |
| `DB_PORT` | `5432` |
| `DB_NAME` | `saayam` |
| `DB_USER` | `postgres` |
| `DB_PASSWORD` | *(empty)* |
| `DB_SSLMODE` | `prefer` |
| `DB_SCHEMA` | `virginia_dev_saayam_rdbms` |

Create the tables and load the sample data:

```bash
createdb saayam_local
psql -d saayam_local -f data-analytics/sql/organization_analytics_local_setup.sql
psql -d saayam_local -c "\copy virginia_dev_saayam_rdbms.state FROM 'data-analytics/sql/state.csv' WITH (FORMAT csv, HEADER true, NULL '')"
psql -d saayam_local -c "\copy virginia_dev_saayam_rdbms.organizations FROM 'data-analytics/sql/organizations.csv' WITH (FORMAT csv, HEADER true, NULL '')"
```

Then run the handler against the sample payloads:

```bash
DB_NAME=saayam_local DB_USER=postgres DB_PASSWORD=postgres \
  python data-analytics/lambda_functions/organization_analytics.py
```

---

## Request

Same common filter structure as the Request, Volunteer, Beneficiary and KPI dashboards.

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
| --- | --- | --- |
| `time_filter` | `7D`, `30D`, `1Y`, `ALL`, `CUSTOM` | `ALL` |
| `start_date` / `end_date` | `YYYY-MM-DD`, both required when `time_filter` is `CUSTOM` | `null` |
| `group_by` | `daily`, `weekly`, `monthly`, `yearly` | `monthly` |
| `region` | state name or state code, or `ALL` | `ALL` |
| `organization_type` | `for_profit`, `non_profit`, or `ALL` | `ALL` |

All values are case-insensitive, and `Non-Profit` is accepted as `non_profit`.
Date windows are applied to `organizations.created_at`. `CUSTOM` is inclusive of
both endpoints.

Both a plain payload and an API Gateway event (`{"body": "<json string>"}`) are accepted.

### Validation

A rejected filter returns **HTTP 400** with the full empty response shape plus an
`error` field, and never opens a database connection:

```json
{ "error": "Invalid time_filter '90D'. Supported values: 7D, 30D, 1Y, ALL, CUSTOM." }
```

---

## Response

```json
{
  "summary": {
    "total_organizations": 40,
    "total_collaborators": 21,
    "total_contributors": 19,
    "average_org_rating": 3.2
  },
  "growth_trend": [
    { "period": "2025", "total_organizations": 39, "total_collaborators": 21 },
    { "period": "2026", "total_organizations": 40, "total_collaborators": 21 }
  ],
  "organizations_by_location": [
    {
      "state_id": "TX",
      "state_name": "Texas",
      "organization_count": 3,
      "percentage": 7.5,
      "cities": [
        { "city_name": "East Jenniferfort", "organization_count": 1 },
        { "city_name": "Hortonberg", "organization_count": 1 },
        { "city_name": "Victoriaport", "organization_count": 1 }
      ]
    }
  ],
  "organizations_by_size": [
    { "org_size": "small", "organization_count": 10 },
    { "org_size": "medium", "organization_count": 9 },
    { "org_size": "large", "organization_count": 21 }
  ],
  "collaborator_vs_contributor": [
    { "type": "collaborator", "organization_count": 21, "percentage": 52.5 },
    { "type": "contributor", "organization_count": 19, "percentage": 47.5 }
  ],
  "rating_distribution": [
    { "rating": 1, "organization_count": 5 },
    { "rating": 2, "organization_count": 9 },
    { "rating": 3, "organization_count": 10 },
    { "rating": 4, "organization_count": 4 },
    { "rating": 5, "organization_count": 12 }
  ],
  "organization_type_distribution": [
    { "period": "2025", "for_profit": 19, "non_profit": 20, "total": 39 },
    { "period": "2026", "for_profit": 19, "non_profit": 21, "total": 40 }
  ],
  "filters_applied": { "...": "the normalised filters that produced this response" }
}
```

### Which tab reads what

| Tab | Section |
| --- | --- |
| *(header)* | `summary` |
| 1 – Growth & Location | `growth_trend`, `organizations_by_location` |
| 2 – Size & Contribution | `organizations_by_size`, `collaborator_vs_contributor` |
| 3 – Ratings & Type | `rating_distribution`, `organization_type_distribution` |

---

## Behaviour notes

**Trends are cumulative.** `growth_trend` and `organization_type_distribution`
report running totals per period, so "Total Organizations" grows over the window
rather than resetting each period. This keeps the two charts reconcilable: the
last period of `organization_type_distribution.total` equals
`growth_trend.total_organizations` and `summary.total_organizations`.

**`organizations_by_location` nests cities inside states.** The state fields match
the shape in the issue; the `cities` array is added underneath so one section can
serve both the state and city breakdowns without a second round trip. States are
ordered by descending count, and `percentage` is the state's share of all
organizations in the window.

**Fixed-scale widgets always return their full scale.** `organizations_by_size`
always returns `small`/`medium`/`large` (zero-filled, with any unexpected stored
value appended after them) and `rating_distribution` always returns ratings 1–5.
The dashboard therefore never has to fill gaps itself.

**`percentage` in `collaborator_vs_contributor`** is each type's share of the two
combined, not of all organizations — an organization can in principle be both.

**Stored values are normalised in SQL.** The sample data holds `Non-Profit` /
`For-profit` and `Small` / `Medium` / `Large`; these are lowercased and
hyphen-normalised inside the query, so grouping and filtering are case-insensitive.

**The schema is probed before querying.** Two things the issue flags as unstable
are detected at request time via `information_schema` and degraded rather than
allowed to fail:

- `is_contributor` may not exist yet in dev. When absent, contributor counts
  return `0` and every other metric is unaffected.
- The state lookup is named `states` in the issue but `state` in the sample data
  and the existing analytics APIs. Either is used, and if neither exists the state
  code is returned in place of the state name.

**NULL handling.** Organizations with a `NULL` `org_rating` are excluded from
`rating_distribution` and from the average; if every rating is NULL the average
returns `0.0`. NULL cities and states are reported as `Unknown`.

**One failing widget does not fail the dashboard.** Each section runs in its own
try/except (same pattern as `kpi_api_analytics.py`); a broken query yields that
section's empty value while the rest of the response returns normally with HTTP 200.
Only a connection failure returns HTTP 500, and it still returns the full empty shape.

**All filter values are bound parameters.** No user-supplied value is ever
interpolated into SQL — including the `DATE_TRUNC` unit and `TO_CHAR` format,
which are bound rather than formatted in.

---

## Tests

```bash
python -m unittest discover -s data-analytics/lambda_functions -p "test_organization_analytics.py"
```

62 tests, no database and no third-party runner required — they drive a mock
cursor that records the generated SQL. Coverage: valid filters, invalid filters,
custom ranges, empty result sets, query exceptions, connection failure, NULL
handling, missing `is_contributor`, missing state lookup, parameterised SQL and
an injection attempt, response structure, and the environment-driven DB config.
