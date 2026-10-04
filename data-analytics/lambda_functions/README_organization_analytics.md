# Organization Analytics API

Implements issue #228 over
`virginia_dev_saayam_rdbms.organizations` and
`virginia_dev_saayam_rdbms.state`. It follows the existing analytics Lambda
pattern: API Gateway-compatible responses, `psycopg2`/`RealDictCursor`, one
query helper per metric, parameterized filters, and per-metric failure
isolation.

## Endpoints

The main Lambda supports the single-endpoint design:

```text
POST /analytics/organizations
```

```json
{
  "dashboard_type": "overview",
  "time_filter": "30D",
  "group_by": "daily"
}
```

`overview_handler` and `performance_handler` are also exported for deployments
that use these separate routes:

```text
POST /analytics/organizations/overview
POST /analytics/organizations/performance
```

## Filters

Both dashboards accept:

- `time_filter`: `7D`, `30D`, `1Y`, `ALL`, or `CUSTOM`
- `start_date` and `end_date`: required for `CUSTOM`, in `YYYY-MM-DD` format
- `org_type`: `non_profit` or `for_profit` (display labels are normalized)
- `org_size`: `small`, `medium`, or `large`
- `state_id`, `city_name`, `org_rating`
- `is_collaborator`, `is_contributor`
- `group_by`: `daily`, `weekly`, `monthly`, or `yearly`

The API returns HTTP 400 for invalid filters. Every user-supplied value is sent
to PostgreSQL as a query parameter.

## Database configuration

The implementation does not contain or retrieve an AWS Parameter Store path.
Set either `DATABASE_URL` or these environment variables:

```text
DB_HOST=localhost
DB_PORT=5432
DB_NAME=saayam_local
DB_USER=postgres
DB_PASSWORD=<local password>
DB_SSLMODE=<optional>
```

## `is_contributor` compatibility

The current shared database may not yet contain `is_contributor`. The API checks
`information_schema.columns` at runtime:

- when present, contributor summaries, distribution, leaderboard, and filter
  work normally;
- when absent, contributor counts are `null`, contributor arrays are empty, and
  `schema_notes.is_contributor` explains the limitation;
- a requested `is_contributor` filter returns HTTP 400 when the column is absent,
  because silently ignoring a filter would return misleading analytics.

## Local PostgreSQL setup and tests

The commands below are PowerShell examples. Use a disposable local database;
nothing in this workflow deploys to AWS.

```powershell
cd data-analytics/lambda_functions
python -m pip install -r requirements.txt

$env:DB_HOST = "localhost"
$env:DB_PORT = "5432"
$env:DB_NAME = "saayam_local"
$env:DB_USER = "postgres"
$env:DB_PASSWORD = "<local password>"
$env:ORG_ANALYTICS_LOCAL_TEST = "true"

psql -d saayam_local -f organization_analytics_local_setup.sql
python organization_analytics_load_csv.py

python -m unittest -v test_organization_analytics.py
$env:ORG_ANALYTICS_RUN_INTEGRATION_TESTS = "true"
python -m unittest -v test_organization_analytics.py

python organization_analytics_generate_samples.py
```

The integration suite verifies both dashboards, every common filter, all four
trend groupings, API Gateway request parsing, response consistency, missing
`is_contributor` behavior, SQL parameterization, and per-metric failure
isolation. Generated sample bodies are stored in
`organization_analytics_samples/`.

