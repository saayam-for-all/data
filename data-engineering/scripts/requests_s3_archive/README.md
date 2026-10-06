# Archive `requests` to S3 (#416)

A scheduled job that **copies** rows from `public.requests` to S3 as monthly CSV
partitions, incrementally, keyed on `last_updated_at`. Postgres writes to S3
itself through the `aws_s3` extension and an IAM role on the instance: no
Lambda, no Glue, no stored credentials. The only statements that touch
`requests` are `SELECT`s. Deleting old rows is out of scope.

## Files

| File | Purpose |
|---|---|
| `001_setup.sql` | `request_archive` schema: `config`, `watermark`, `run_log` |
| `002_archive.sql` | `request_archive.run()` procedure |
| `003_schedule.sql` | Weekly `pg_cron` job (apply last, only after a manual run is verified) |
| `tests/` | Integration tests against local Postgres with a mock `aws_s3` |

## How a run works

1. Take a session advisory lock. An overlapping run logs `skipped` and exits.
2. Log a `running` row and commit, so a crash still leaves a trace. A stale
   `running` row from a dead session is marked `interrupted` on the next run.
3. Open one `REPEATABLE READ` snapshot. Window = `(watermark - replay_overlap,
   now - safety_lag]` on `last_updated_at`. The first run starts at `-infinity`.
4. Count rows per UTC month of `last_updated_at`, then export each month with
   `aws_s3.query_export_to_s3` as CSV with a header. Every export is compared
   with that month's source count, and the run total with the source total.
5. Only if every count agrees: advance the watermark and mark the run `success`,
   in one transaction. Otherwise mark it `failed` with the error, leave the
   watermark alone, and raise so `pg_cron` shows the failure.

Because the count and the export read the same snapshot, a request edited
during the upload cannot cause a false mismatch. The edit is picked up next run.

Objects land at `s3://<bucket>/<prefix>/year=YYYY/month=MM/run_id=<n>/requests.csv`
(AWS adds `_part2`, `_part3`... for very large exports).

## Reading the archive

Delivery is **at-least-once**:

- A request updated in a later month appears again under that month. Take the
  latest row per `req_id` by `last_updated_at`, using `run_id` to break ties.
- `replay_overlap` deliberately re-exports recent rows. This catches rows that
  commit late or share the watermark's timestamp.
- S3 writes cannot be rolled back. A failed run may leave files. **Read only
  `run_id`s whose `run_log.status = 'success'`**; `run_log.outputs` lists each
  file with its source and uploaded row counts.
- Hard deletes and changes backdated beyond `replay_overlap` are not captured.

`SELECT *` exports every column unchanged, including requester identifiers.
Use a private bucket and decide who may read it before enabling the schedule.

## Deploy (done by someone with AWS and DB admin access)

1. Confirm the engine supports `aws_s3` and `pg_cron`; an admin installs them.
2. Attach an IAM role to the instance that can write to the archive prefix
   (and the KMS key, if used). The bucket must be in the instance's region.
3. Apply `001_setup.sql` and `002_archive.sql` as the job owner, then:

   ```sql
   INSERT INTO request_archive.config (bucket, region)
   VALUES ('<archive-bucket>', '<aws-region>');
   ```

4. Grant the job role `SELECT` on `public.requests`, `EXECUTE` on
   `request_archive.run()`, and access to the `aws_s3` functions and the
   `request_archive` tables. It needs no write access to `requests`.
5. Run `CALL request_archive.run();` on its own connection in autocommit mode
   (not inside `BEGIN`/`COMMIT`). Check `request_archive.run_log`, download the
   files listed in `outputs`, and confirm they open and the row counts match.
6. Apply `003_schedule.sql`. The default is Sundays 02:00 in `pg_cron`'s time zone.

Watch `run_log` for `failed`, `interrupted`, a stuck `running`, and the age of
the last `success`.

## Tests

```sh
python -m pip install psycopg2-binary
createdb issue416_test
ARCHIVAL_TEST_DSN="host=127.0.0.1 dbname=issue416_test user=postgres" \
  python -m unittest data-engineering/scripts/requests_s3_archive/tests/test_archive.py
```

The tests refuse to run unless the host is loopback and the database name starts
with `issue416_`. Only `aws_s3` is mocked; not yet verified against real S3.
