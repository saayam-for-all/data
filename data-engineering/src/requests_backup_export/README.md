# requests_backup_export

Stage one of two. Copies the `requests` table to S3 incrementally, with the six
lookup tables joined in so the file reads without a lookup sheet.

This is the full fidelity copy. Nothing is hashed, masked or dropped, because
once rows are deleted from the source this file is the only one left. Stage two
reads this output and writes a de-identified copy to a different bucket.

```
Postgres  ->  backup bucket        (this)
backup    ->  stakeholder bucket   (stage two, separate Lambda)
```

**The only statement this issues against an application table is `SELECT`.**
The two tables it writes to, `archive_watermark` and `archive_run_log`, are its
own.

## What the output looks like

Every source column is exported, in source order, with each lookup's readable
value inserted directly after its ID column. 22 source columns become 28.

```
req_id, creator_id, beneficiary_id, lead_volunteer_id,
req_cat_id, req_cat_name, req_for_id, req_for, req_islead_id, req_islead,
req_type_id, req_type, req_priority_id, req_priority, req_status_id, req_status,
req_subj, req_desc, req_doc_link, audio_req_desc, deletion_reason,
req_loc, created_loc, iscalamity, to_public,
submission_date, serviced_date, last_updated_at
```

The ID is kept, not replaced. It is the join key back to the source, labels can
be renamed later while IDs don't change, and once the archive is the only copy
you can't recover a column you dropped.

`req_loc` and `created_loc` go through `ST_AsText`, so the file holds
`POINT(-122.036349 37.3688301)` rather than PostGIS hex.

`users` is not joined. There is no readable label for a person that isn't their
identity, and joining it would copy a name into every request that person ever
filed. The three user ID columns are exported as-is.

## Mechanics

```
read watermark -> select the window -> upload to S3 -> advance watermark, log
```

The watermark moves last, so a run that dies partway through leaves it where it
was and the next run recomputes the identical window. The S3 key is derived
from the window, so a repeat overwrites the same object instead of duplicating.

The window is half-open, `(lo, hi]`, so a row whose timestamp sits exactly on a
bound belongs to exactly one run.

The upper bound is `lag_minutes` in the past, not `now()`. `last_updated_at` is
set when the statement runs but the row is only visible once the transaction
commits, so reading up to `now()` would permanently skip a row stamped just
under the bound and committed just over it. The lag must exceed the longest
write transaction.

Every join is a `LEFT JOIN`. An inner join silently drops any request whose
reference is null or broken, and the row count looks small rather than wrong.
In dev, 218 of 221 requests have a null `lead_volunteer_id`.

## Running it locally

Needs a PostgreSQL with the schema from #573. No AWS, S3 is mocked.

```
python3 tests/requests_backup_local_test.py
```

It runs a full export, an immediate rerun that should find nothing, an
incremental run after a new row, and the same window twice to confirm the
bytes are identical.

## Deploy

```
STATE_STORE=postgres INLINE_DB_CREDS=1 ./scripts/deploy/deploy_requests_backup.sh
./scripts/deploy/deploy_requests_backup.sh invoke
./scripts/deploy/deploy_requests_backup.sh logs
```

Creates no IAM, no bucket, no database objects.

## Config

`config.json` ships inside the deployment package, so the join mapping lives in
git with review history rather than in a database row somebody can edit
unlogged.

`joins` adds a readable column next to each ID. `geometry_columns` are passed
through `ST_AsText`. `expected_unjoined` is the list of `*_id` columns we have
deliberately decided not to join; anything ending in `_id` that isn't in the
config and isn't on that list gets logged as `unmapped_reference_columns`, so a
new foreign key added upstream gets noticed instead of silently exporting as a
bare number.

## Known gaps

- Runs under `STREAM=backup`, which keeps its own watermark separate from the
  old `main` stream. The old stream's rows are left alone.
- The database password is currently passed as an environment variable because
  the VPC has no route to Parameter Store. Evaluation only.
- Scheduling is not enabled. The scheduler role does not yet trust
  `scheduler.amazonaws.com`.
- Writes to `saayam-virginia-archive` under the `backup/` prefix. The old
  pre-join exports live under `raw/` in the same bucket and are a different
  schema, so they are kept apart by prefix rather than mixed.
- The stakeholder bucket for stage two does not exist yet. It needs creating
  separately, with no path back to this one.
