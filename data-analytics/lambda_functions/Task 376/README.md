# Task 376: Size & Contribution Analytics API

Standalone implementation of [issue #376](https://github.com/saayam-for-all/data/issues/376),
kept beside the existing analytics Lambdas. Entry point:
`size_contribution_analytics.lambda_handler`. No existing function is modified.

## Run locally (PowerShell)

From the repository root:

```powershell
Set-Location 'data-analytics/lambda_functions/Task 376'
```

The task already has an isolated `.venv` and local `mock_data` from verification.
Run the six example requests again:

```powershell
$env:USE_MOCK_DATA = 'true'
$env:MOCK_DATA_DIR = Join-Path (Get-Location) 'mock_data'
& .\.venv\Scripts\python.exe .\size_contribution_analytics.py
& .\.venv\Scripts\python.exe -m unittest discover -s . -p 'test_*.py' -v
```

For a fresh checkout, prepare the environment and sample data first:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe .\create_mock_data.py
```

`create_mock_data.py` generates eight synthetic organizations relative to the
current UTC time and two small geography lookup tables. It refuses to overwrite
existing CSVs. All CSVs, `.venv`, and Python caches in this folder are gitignored.
To reuse existing Growth & Location CSVs, set `MOCK_DATA_DIR` to their directory
instead; there is no need to run the generator. The handler also accepts the
older repository filenames `state.csv` and `country.csv` when the plural names
are absent.

`local_test_output.txt` contains the actual test run and printed responses from
all six examples. Tests create and clean up their own temporary CSVs and freeze
the clock, so results do not depend on when the test suite runs.

## Request and response

Use a direct Lambda event containing filters, an object in `event.body`, or a
JSON string in `event.body`. An absent, null, or empty body selects defaults.
The API Gateway response contains `statusCode`, JSON/CORS headers, and a **JSON
string** in `body`; parse that string to obtain the charts.

```json
{
  "body": {
    "country": "USA",
    "organization_type": "non_profit",
    "size_start_date": "2026-09-01",
    "size_end_date": "2026-09-30",
    "contribution_start_date": "2025-01-01",
    "contribution_end_date": "2025-12-31"
  }
}
```

| Parameters | Keys in decoded response | Populated charts |
| --- | --- | --- |
| Neither date pair | `7D`, `30D`, `1Y`, `All`, `Custom` | Both in each fixed bucket; `Custom` empty |
| Size pair only | `Custom` | Organizations by size |
| Contribution pair only | `Custom` | Collaborators vs contributors |
| Both pairs | `Custom` | Each chart uses its own range |

Every bucket has exactly `organizations_by_size` and
`collaborator_vs_contributor`. Empty datasets/windows return empty arrays.
Observed size categories are returned unchanged, sorted by raw category, with
no hardcoded categories or zero filling. Nonempty contribution windows contain
exactly `Collaborator` and `Contributor` rows, in that order. Each percentage is
its own count divided by the window's organization count, rounded to one decimal.
Both flags can be true, or both false; percentages need not sum to 100.

`country` matches either code or name, ignoring case and surrounding whitespace.
`organization_type` accepts `non_profit`, `for_profit`, or `ALL`, ignoring case.
Both default to `ALL` and apply to every requested chart. Legacy CSV type values
`Non-Profit`/`For-Profit` are recognized. Raw size values are never rewritten.
Unknown countries give empty results. Unknown request fields, including
`time_filter`, are rejected to avoid silently ignoring misspelled filters.

Date semantics are explicit: `7D`, `30D`, and `1Y` are rolling 7-, 30-, and 365-day
windows ending at the invocation's UTC time, inclusive at both boundaries.
`All` has no lower bound and ends at the same instant. Future-created rows do
not enter fixed snapshots. Custom ranges use strictly formatted `YYYY-MM-DD`
dates and include the entire UTC start and end days. Offset timestamps are
converted to UTC; naive timestamps are treated as UTC. Custom dates are
independent of the current time. Both pairs are validated before any data is
loaded, so an invalid second pair cannot produce a partial successful response.

Invalid requests return HTTP 400 with `{"error": "..."}`. Missing/incompatible
data or database failures return HTTP 500. Unexpected server exceptions are
logged and return a generic error rather than database connection details.

## Data configuration

| CSV | Columns |
| --- | --- |
| `organizations.csv` | `org_id`, `org_size`, `is_collaborator`, `org_type`, `state_id`, `created_at`; optional `is_contributor` |
| `states.csv` | `state_id`, `country_id` |
| `countries.csv` | `country_id`, and at least one of `country_code` / `country_name` |

The join follows `organizations.state_id -> states.country_id -> countries`.
Identifiers remain strings so leading zeroes survive CSV loading. Primary keys
must be unique and nonempty to avoid counting an organization multiple times.
Organizations without a matching location remain in unfiltered counts and do
not match country filters. Missing `is_contributor` means zero contributors;
null flags mean false. Boolean values `true`/`false`, `t`/`f`, and `1`/`0`
(including `1.0`/`0.0`) are accepted without treating `"False"` as true.
Missing/invalid timestamps, empty size values, and invalid flag values are
reported as data errors. Header-only and zero-byte organizations files work.

## Optional PostgreSQL mode

CSV mode defaults to `USE_MOCK_DATA=true` and does not require psycopg2. To use
the database adapter, install the existing repository's optional driver:

```powershell
& .\.venv\Scripts\python.exe -m pip install psycopg2-binary==2.9.9
```

Set `USE_MOCK_DATA=false` and provide `DB_HOST`, `DB_NAME`, `DB_USER`, and
`DB_PASSWORD` in the process environment. Optional settings:

| Variable | Default |
| --- | --- |
| `DB_PORT` | `5432` |
| `DB_SSLMODE` | `require` |
| `DB_SCHEMA` | `virginia_dev_saayam_rdbms` |
| `DB_ORGANIZATIONS_TABLE` | `organizations` |
| `DB_STATES_TABLE` | `state` |
| `DB_COUNTRIES_TABLE` | `country` |

Singular lookup table defaults follow the repository schema. Set the table
variables if an environment uses plural names. The same column requirements
apply to CSV and database sources. Metadata discovery tolerates a missing
`is_contributor` column and either country label column. Queries select only the
columns used by this function, bind metadata values, and quote table/schema
identifiers with `psycopg2.sql.Identifier`.

The adapter reads all selected rows in one read-only, repeatable-read transaction
and then uses the same pandas transformations as CSV mode. Size Lambda memory
for those tables when integrating it. Connections close on success and failure.
The older organization DDL checked into this branch predates issue #376; the
target database must expose the issue's required columns.

Local verification covers actual CSV reads, optional-driver import behavior,
database query construction, adapter parity, and cleanup with mocked database
connections. A live PostgreSQL server and AWS deployment were not exercised.
No remote service, PR, commit, or push is needed to run this task locally.
