# Archive verification (#586)

Checks that the archived `requests` export matches the source database. Task 6
of epic [#416](https://github.com/saayam-for-all/data/issues/416).

Recorded results live in [REPORT.md](REPORT.md).

## Running it

```bash
cd data-engineering
python -m src.archive_verification.verify
```

No container, no credentials and no network. It prints a pass or fail for each
of the seven checks, times each one and the run as a whole, and exits non-zero
if anything failed, so it can gate CI once the real extract exists.

```
  [PASS] 1   Row counts match the source                 16.9 ms
  ...
  7 passed, 0 failed, 1 skipped of 8 checks
  total 0.110 s
```

Useful arguments:

| Argument | Effect |
| --- | --- |
| `--extractor MODULE:CALLABLE` | the extract to verify. Omit for the reference fixture. |
| `--source postgres` | read the real schema instead of the local copy. The only way to run check 7b. |
| `--schema NAME` | schema qualifying the tables when `--source postgres` |
| `--archive-dir PATH` | where exports are written (default: a temporary directory) |
| `--archive-s3 BUCKET/PREFIX` | write to S3 instead. Needs `boto3` and credentials. |

`--source postgres` reads `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` and
`DB_PASSWORD`, the names already in `.env.example`. The connection is opened
read only, because #586 says the source database is read only.

## Two things to read before trusting a green run

**The extract is a fixture, not the pipeline.** Task 2
([#574](https://github.com/saayam-for-all/data/issues/574)) owns the real
`Data_ArchiveRequestData` extract. That issue is closed but its code is not
merged into `dev`, `main` or `test`, so there was nothing in this repository for
these checks to run against. [`fixture_extract.sql`](fixture_extract.sql) exists
so the checks could be executed and proven, and the report labels every result
with it. **A green run here says the checks work; it does not say the production
pipeline is correct.** When Task 2's extract lands:

```bash
python -m src.archive_verification.verify --extractor src.their_module:extract
```

Nothing else changes. Do not promote the fixture extract to production use: it
has no PII masking (issue #585 owns the free-text fields), no S3 write path and
no watermark table. It is a query, not a pipeline.

**Check 7b is skipped, not passed.** A session time zone is a Postgres concept
and the local copy is SQLite, so the harness reports `SKIP` with a reason rather
than a pass it could not have earned. That acceptance criterion is still
outstanding; see the caveat below.

## How it is put together

| File | Job |
| --- | --- |
| `verify.py` | CLI: runs the checks, times them, prints the report, sets the exit code |
| `checks.py` | the seven checks, numbered as #586 numbers them |
| `adapters.py` | the source / archive / extract seams |
| `fixture.py` | builds the local copy of the schema and seeds the awkward rows |
| `fixture_schema.sql` | the local schema copy, derived from #573's `saayam_schema.sql` |
| `fixture_extract.sql` | the reference extract. **Fixture only.** |

Three things vary between a local run and a real one, so each is a seam rather
than a hard-coded choice: where rows are read from, where files are written, and
which extract is under test. That is what lets one script serve both a laptop
with no credentials and a lead with full access.

`boto3` is imported lazily and tolerated absent, so the default path adds
nothing to `requirements.txt` and both `pip-audit` steps in CI are unaffected.

### The local copy

#586 asks for one explicitly:

> Check 5 needs a row with a broken reference, and the dev data may not have
> one. You cannot insert into the source database, it is read only. So build a
> local copy of the schema, put a request in it whose category points at
> nothing, and run the extract against that.

It is SQLite, which means no container and no setup, while still giving real
`LEFT JOIN` versus `INNER JOIN` semantics and real foreign key enforcement -
the two things check 5 actually turns on.

Lookup values are loaded from `database/lookup_tables/*.csv`, already committed,
whose values match #573's DDL comments exactly (`request_status` 0=CREATED
through 7, `request_priority` 0=LOW through 3=CRITICAL, and so on). Nothing here
invents lookup data. Generating mock data for this pipeline is Task 7
([#587](https://github.com/saayam-for-all/data/issues/587)), a separate open
issue; this fixture is deliberately the ~25 rows the checks need, not a dataset.

The fixture deliberately contains: null `lead_volunteer_id` and
`beneficiary_id`; a `req_cat_id` pointing at nothing; three rows sharing one
`last_updated_at` to the microsecond, exactly on a window boundary; a row whose
`last_updated_at` precedes its `submission_date`; a `req_desc` containing a
newline, a comma and a double quote; and a row updated between two runs.

Every check builds its own fixture. Check 3 needs two windows with nothing
changing in between, check 2 needs a row updated between them, so a shared
fixture would make the checks order-dependent.

### Deviations from the real schema

| Upstream | Here | Why |
| --- | --- | --- |
| `req_loc`, `created_loc` are `geometry(Point,4326)` | `TEXT` | no PostGIS in SQLite, and no check inspects geometry. `data-analytics/sql/requests.csv` already stores `req_loc` as plain text (`"Suffolk, VA"`), which contradicts the DDL anyway. |
| `timestamp(6)` | `TEXT`, `YYYY-MM-DD HH:MM:SS.ffffff` | lexical order equals chronological order in that form, so the window predicate behaves as it does on Postgres, microsecond ties included |
| triggers `generate_req_id`, `generate_sid`, `set_updated_at` | not reproduced | the fixture supplies ids and timestamps explicitly, which is what makes windows deterministic. See the caveat below. |
| `request_status` has ids 0-8 | 8 added | `request_status.csv` stops at 7 while #573's DDL comment lists `8 VOLUNTEER_NOT_FOUND` |
| lookup CSVs say `last_updated_date` | `last_updated_at` | the files and the schema disagree; the schema wins |

`data-analytics/sql/*.csv` is deliberately not read at all. Those exports were
taken months apart and are mutually inconsistent: `req_cat_id` values such as
`CAT-FOOD` appear in no row of `help_categories.csv`, `req_priority_id` reaches
4 against a 0-3 lookup, and `request_statuses.csv` calls status 1 `New` where
the real lookup calls it `MATCHING_VOLUNTEER`. Both #573 and #587 say so, and
#587 owns replacing them.

## The caveat that matters most

`requests.last_updated_at` defaults to `now() AT TIME ZONE 'UTC'`, which is
session-time-zone independent. But a trigger `set_updated_at()` also writes that
column, and **its body is not in #573's schema dump**. That trigger is exactly
where a non-UTC `now()` would leak in, and no local copy can rule it out. Check
7b against the real database is the only thing that settles it.

## Mutation results

Checks that always pass are worth nothing, so each property was broken in turn
to confirm the matching check goes red. `tests/test_archive_verification.py`
keeps these as tests.

| Mutation | Checks that went red |
| --- | --- |
| `LEFT JOIN help_categories` → `INNER JOIN` | 1, 3, 5 |
| `LEFT JOIN users` (lead volunteer) → `INNER JOIN` | 1, 3, 5 |
| closed window, `<=` on the high bound | 1, 2, 3 |
| exclusive low bound, `>` | 3 |
| watermark from `max(last_updated_at)` | 3, 7a |
| row order varies between runs (no `ORDER BY`) | 6 |
| readable status replaced by its identifier | 4 |
| watermark from the local clock | 3, 7a |

Check 1's trap is reported rather than mutated: against the fixture, counting
lines instead of parsing CSV gives 14 rows where there are 12, because free text
contains newlines. The run prints that discrepancy every time.

## Tests

```bash
cd data-engineering
python -m pytest -v tests/test_archive_verification.py
```

They need no Postgres, no Docker and no AWS, so they are safe for the CI job
that runs `pytest -v tests/` on push to `dev`. The one Postgres test skips
unless `ARCHIVE_VERIFY_POSTGRES` is set.
