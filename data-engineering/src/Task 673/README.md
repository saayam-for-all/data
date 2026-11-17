# Task 673: organization contributor flag

Implements [issue #673](https://github.com/saayam-for-all/data/issues/673) on
`ManishPatturu_Task673_OrgContributor`. All work and validation are local.

The production change is in [`../saayam-org-aggregator/helpers.py`](../saayam-org-aggregator/helpers.py).
Keeping it in the existing Lambda directory ensures the deployed aggregator uses
the change. This task folder contains the runnable example, fixtures, tests, and
validation results; it does not duplicate the production Lambda.

## Behavior

- Every response organization has `contributor` immediately after `collaborator`.
- Database organizations use `organizations.is_contributor`.
- If the column is absent or its value is unknown, DB organizations get `null`.
- GenAI organizations always get `false`, even if their payload claims otherwise.
- Both flags are native JSON booleans or `null`, including after pandas combines
  empty frames, nullable values, or numeric boolean representations.
- Existing SQL, search scope, result order, rating, and distance calculations are
  unchanged. There is no schema migration or additional query. The current handler
  has no pagination parameter, and this task does not introduce one.

`SELECT DISTINCT o.*` already works with both schema versions. The existing
normalization supplies a missing column, and flag conversion after concatenation
keeps `NaN`, `0`, and `0.0` out of the two flag fields. Unknown flag values become
`null`; other response fields retain their existing behavior.

## Run locally on Windows

The Python environment and portable PostgreSQL binaries are already prepared in
this workspace. From the repository root, use PowerShell:

```powershell
Set-Location 'data-engineering/src/Task 673'
& .venv/Scripts/python.exe run_local.py
& .venv/Scripts/python.exe run_local.py --missing-contributor --sort-by-distance
& .venv/Scripts/python.exe -m pytest -q
```

The runner automatically reuses PostgreSQL in `.local/pgsql/bin`. Downloading or
installing it again is unnecessary unless these binaries are removed, damaged,
or you set up another machine. Each run starts and stops the existing local
server binaries; it does not download PostgreSQL. Downloads, virtual environment,
cluster data, and logs stay in ignored `.local/` and `.venv/` folders.

Add `--output examples/response.json` to either runner command to save the
formatted response as UTF-8 JSON.

For a fresh checkout on another machine, install Python 3.12 and PostgreSQL first,
then prepare the test environment from the task directory:

```powershell
python -m venv .venv
& .venv/Scripts/python.exe -m pip install -r requirements.txt
# Example path: replace it with your installed PostgreSQL bin directory.
$env:TASK673_PG_BIN = 'C:\Program Files\PostgreSQL\16\bin'
& .venv/Scripts/python.exe -m pytest -q
```

The PostgreSQL `bin` directory must contain `initdb`, `pg_ctl`, and `postgres`.
Putting `pg_ctl` on `PATH` also works. On Linux/macOS, install PostgreSQL using
your usual package manager and use `.venv/bin/python`. Run PostgreSQL as a regular
user. The downloader is not needed by the test suite or Lambda.

The runner starts a task-owned database on an available `127.0.0.1` port, creates
a uniquely named synthetic schema, calls the actual Lambda, removes that schema,
and stops PostgreSQL. Run these commands sequentially because they share the local
cluster. Authentication is trust-based for this disposable local fixture database.
Do not point this harness at a shared/dev/production database.

AWS SSM and the GenAI invocation are mocked at the service boundary. PostgreSQL,
the production SQL, pandas transformations, Lambda handler, and distance logic
run normally. No AWS credentials, live API calls, or real user data are needed.
The runner formats the response's JSON body as an array for readability; the
production handler continues to return the original API Gateway string body.

## Tests and baseline

```powershell
# Fast checks that do not need PostgreSQL:
& .venv/Scripts/python.exe -m pytest tests/test_flags.py -q

# Real PostgreSQL and full Lambda response regression:
& .venv/Scripts/python.exe -m pytest tests/test_postgres.py -q
```

Integration tests load baseline source directly from the local Git object for
`c3b66eadc20b765c09dedb40d35d3566efdd652f`, verified as the remote `test` head on
2026-11-16. No fetch or network operation is performed by the tests. A shallow
checkout must contain this commit to run the baseline comparisons.

The matrix covers a present/absent contributor column, normal/distance order,
and available/empty/unavailable GenAI results. It compares response headers and
every existing response field with that baseline, then independently checks
contributor values, exact flag types, key order, and distance results. Additional
checks cover warm invocations, adding the column between invocations, city and
category filters, duplicate skill rows, AI-only and empty lists, invalid requests,
and unrelated database errors.

See [VALIDATION.md](VALIDATION.md) for actual run results.

## Files for the PR

| Files | Purpose / recommendation |
|---|---|
| `../saayam-org-aggregator/helpers.py` | Required production change |
| `tests/`, `harness.py`, `local_postgres.py`, `fixtures.sql`, `requirements.txt`, `pytest.ini` | Keep together to reproduce the automated checks |
| `README.md`, `.gitignore` | Keep setup instructions and local-artifact exclusions |
| `VALIDATION.md` | Recommended evidence; its results could instead go in the PR description |
| `run_local.py`, `examples/*.json` | Optional manual demo and saved outputs; automated tests do not depend on them |
| `.local/`, `.venv/`, caches | Machine-generated artifacts; ignored by Git |

The one-time downloader was moved to
`data-engineering/scripts/local-only/download_postgres.py`. That folder is ignored
by `data-engineering/.gitignore` and stays local. It still targets this task's
existing `.local/` directory if it is ever needed for setup again. The task's
runtime and automated tests do not import it.

The optional demo files remain available locally. If they are omitted from a
future PR, remove their command/output links from this README and `VALIDATION.md`
in that PR as well.

## Shared dev database check

The shared dev database has not been contacted. Local fixtures verify both schema
versions, but cannot establish whether the shared table currently has the column.
Someone with authorized dev database access can run this read-only query:

```sql
SELECT table_schema, table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'virginia_dev_saayam_rdbms'
  AND table_name = 'organizations'
  AND column_name = 'is_contributor';
```

No database alteration is needed for this task. The API supports both results of
that schema check.
