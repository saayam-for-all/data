# Task 673 local validation

Validated on **2026-11-16** on branch
`ManishPatturu_Task673_OrgContributor`. No commits, pushes, PRs, deployments, or
shared database changes were made.

## Environment

| Component | Version / configuration |
|---|---|
| OS | Windows, x64 |
| Python | 3.12.3, isolated task virtual environment |
| PostgreSQL | 16.16, task-owned loopback-only cluster |
| pandas / NumPy | 2.2.2 / 2.0.1 (repository requirement versions) |
| psycopg2-binary | 2.9.9 |
| pytest | 8.3.3 |
| boto3 / aws-lambda-powertools | 1.44.4 / 3.40.0 |
| Baseline | `test` at `c3b66eadc20b765c09dedb40d35d3566efdd652f` |
| AWS / GenAI | Service-boundary fixtures; no external invocations |

## Automated checks

Command from the repository root:

```powershell
& 'data-engineering/src/Task 673/.venv/Scripts/python.exe' -m pytest 'data-engineering/src/Task 673' -q
```

Result: **56 passed in 54.94 seconds** (39 unit/contract checks and 17 real
PostgreSQL integration checks). No failures or skipped tests.

| Check | Result |
|---|---|
| DB contributor values `true`, `false`, SQL `NULL` | Correct native JSON values |
| Table without `is_contributor` | HTTP 200; all DB contributor values `null` |
| GenAI records with claimed contributor status | Always `false` |
| Flag ordering and types | `contributor` follows `collaborator`; only bool/null |
| Numeric flags, NumPy scalars, pandas missing values | Normalize safely to bool/null |
| AI-only, DB-only, empty and unavailable AI results | Correct response shape and flags |
| City/category filters and duplicate skill rows | Existing filtering and deduplication preserved |
| Repeated warm invocations | Connection and response remain usable |
| Column added between warm invocations | New DB values immediately reflected |
| Invalid requests / unrelated DB failures | Existing 400 / 500 behavior preserved |
| Existing response fields and headers | Match pinned `test` baseline in all 12 matrix cases |
| Distance calculation and sorting | Match baseline; no external geocoder calls |

The baseline matrix covers both schema versions, both default/distance ordering,
and available/empty/unavailable GenAI responses. Each comparison removes only
the new contributor field before comparing the remaining output.

Pandas emitted 30 concatenation deprecation warnings across current and baseline
code for empty/all-null frames. These are warnings, not failing checks; the
existing concatenation strategy and non-flag fields were preserved.

## Standalone handler runs

Both commands completed successfully against actual local PostgreSQL:

```powershell
& 'data-engineering/src/Task 673/.venv/Scripts/python.exe' 'data-engineering/src/Task 673/run_local.py' --output 'data-engineering/src/Task 673/examples/with_contributor_column.json'
& 'data-engineering/src/Task 673/.venv/Scripts/python.exe' 'data-engineering/src/Task 673/run_local.py' --missing-contributor --sort-by-distance --output 'data-engineering/src/Task 673/examples/without_contributor_column.json'
```

| Synthetic organization | With column | Without column |
|---|---|---|
| Community Pantry (DB) | `true` | `null` |
| Neighborhood Kitchen (DB) | `false` | `null` |
| Volunteer Groceries (DB) | `null` | `null` |
| Generated Food Network (GenAI) | `false` | `false` |
| HTTP status | 200 | 200 |

Saved outputs:

- [Response with contributor column](examples/with_contributor_column.json)
- [Response without contributor column](examples/without_contributor_column.json)

All fixtures use synthetic names, addresses, and `example.invalid` contacts.
PostgreSQL was stopped after validation. `git diff --check` passed and all eight
task/changed Python source files parsed successfully.

## Remaining environment confirmation

The shared dev database's `organizations.is_contributor` column is **unverified**.
The workspace's database URL is a local example configuration, and no dev DB
connection was used. Both possible schemas have been verified against real local
PostgreSQL. The README includes a read-only query for an authorized dev DB owner
to confirm its current schema.
