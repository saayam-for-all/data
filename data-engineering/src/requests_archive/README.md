# requests_archive

Copies rows from the `requests` table to S3 on a schedule, incrementally, with
PII rules applied on the way out. Issue #416.

**The only statement this pipeline issues against an application table is
`SELECT`.** It does not insert, update, delete, truncate or alter anything in
the application schema, and it holds no locks on application tables. The two
tables it writes to are its own, created by the DBA:
`infrastructure/db/requests_archive/001_archive_state_tables.sql`.

There is a second implementation of #416 in the repo,
`infrastructure/db/requests_s3_archive/`, which does the same export from
inside Postgres using `pg_cron` and `aws_s3`. The two have not been reconciled.
See `APPROACH.md`.

## Files

```
lambda_function.py   extract, mask, write to S3, advance the watermark
state.py             watermark and run-log storage, three backends
config.json          which tables, which columns, which PII rule
APPROACH.md          what this does and why, and what the 15 Oct review changed
```

Deploy script: `scripts/deploy/deploy_requests_archive.sh`
State table DDL: `infrastructure/db/requests_archive/001_archive_state_tables.sql`

## One run

```
read watermark -> select new rows -> upload to S3 -> advance watermark, log run
```

The watermark moves last. A run that dies partway through leaves it where it
was, so the next run recomputes the identical window. The S3 key is derived
from that window, so a repeat overwrites the same object instead of creating a
duplicate.

The window is half-open, `(lo, hi]`, so a row whose timestamp sits exactly on a
bound belongs to exactly one run. The upper bound is five minutes in the past,
not `now()`, because `last_updated_at` is set when the statement runs but the
row only becomes visible when the transaction commits. Reading up to `now()`
would permanently skip a row stamped just under the bound and committed just
over it, with nothing reporting an error.

## State store

| `STATE_STORE` | Watermark lives in | Needs | Schedulable |
|---|---|---|---|
| `none` | nowhere | nothing | no |
| `postgres` | `archive_watermark` / `archive_run_log` | the DDL above run once, then `SELECT`/`INSERT`/`UPDATE` on those two tables only | yes |
| `s3` | `_state/watermark.json` in the bucket | `s3:GetObject` on the bucket | yes |

Switching is one environment variable and a redeploy. No code change.

`none` keeps no watermark, so an incremental table **refuses to run** under it
unless given an explicit range. It does not quietly fall back to re-exporting
everything.

## Running it

From `data-engineering/`:

```
STATE_STORE=postgres ./scripts/deploy/deploy_requests_archive.sh
./scripts/deploy/deploy_requests_archive.sh invoke
./scripts/deploy/deploy_requests_archive.sh range "2000-01-01 00:00:00" "2026-10-13 00:00:00"
./scripts/deploy/deploy_requests_archive.sh logs
./scripts/deploy/deploy_requests_archive.sh teardown
```

Both range bounds are UTC. `range` ignores the watermark and persists nothing,
which is how backfills are done. `teardown` removes the function and schedule
and leaves the bucket and log group alone.

Creates no IAM, no bucket, no database objects.

## Config

`config.json` ships inside the deployment package, so the PII rules live in git
with review history rather than in a database row somebody can edit unlogged.

Per column: `keep`, `drop`, `hash`, `mask`, `redact`, `scrub`. `drop` means the
column is absent from the output file, not blanked. `hash` is
`sha256(value || salt)` in hex and preserves NULL as NULL, so a missing value
does not become the hash of the string "None". `scrub` is the free-text pattern
pass and runs in Python rather than in SQL, because no SQL expression finds a
phone number inside a sentence.

Anything not listed in `columns` is exported unchanged.

## Two things that will bite

**Timestamps.** Every timestamp column in this schema is `timestamp without
time zone`. Comparing one to `now()` or `clock_timestamp()` casts it through
the session `TimeZone`, which shifts the range by the UTC offset (seven hours,
from Phoenix) without erroring. The handler issues `SET TIME ZONE 'UTC'` on
connect and writes every bound as `now() AT TIME ZONE 'UTC'`. Do not remove
either.

**`aws:SourceArn` in a trust policy.** If anyone re-creates the `s3Export`
role, do not add an `aws:SourceArn` condition. The role reports ACTIVE and
every export fails with "credentials stored with the database cluster can't be
accessed". Not relevant to this version, which does not use `aws_s3`, but it
cost a day the first time.

## Known gaps

- The hash salt is passed as an environment variable because `ssm:PutParameter`
  is not granted. It belongs in Parameter Store as a SecureString. The ID
  hashes are pseudonyms, not anonymised values, and with tens of users in a
  predictable ID format a hash with a known salt is recoverable by enumeration
  in under a second.
- `INLINE_DB_CREDS=1` puts the database password in a Lambda environment
  variable, where it is plaintext to anyone with
  `lambda:GetFunctionConfiguration`. Evaluation only, pending an SSM interface
  endpoint or a NAT.
- The scheduler role does not yet trust `scheduler.amazonaws.com`, so scheduled
  runs are not enabled. Manual invocation works.
- Free-text masking is patterns only. It finds emails, phone numbers, card
  numbers, SSNs and URLs. It does not find names in any language. See
  `APPROACH.md`.
