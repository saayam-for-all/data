# Requests S3 Archive Pipeline

Implements issue #416: copy rows from `public.requests` to S3 as partitioned CSV on a schedule, using PostgreSQL/RDS native `aws_s3` and `pg_cron`.

## What this adds

- `archive.requests_s3_watermark` stores the last successful `last_updated_at` watermark.
- `archive.requests_s3_runs` logs every run with source and uploaded row counts.
- `archive.requests_s3_run_files` logs each partition file exported to S3.
- `archive.export_requests_to_s3(...)` performs an incremental export.
- `archive.export_requests_to_s3_from_config()` is the scheduled wrapper.
- `002_schedule_pg_cron.sql` schedules the job weekly at 06:00 UTC on Sunday.

The export job only reads `public.requests`. It does not delete, update, or insert rows in the source table.

## S3 layout

Each run writes CSV files under partitions derived from `last_updated_at`:

```text
s3://<bucket>/requests/
  last_updated_year=YYYY/
    last_updated_month=MM/
      last_updated_day=DD/
        run_id=<archive.requests_s3_runs.run_id>/
          requests.csv
```

If a request is updated after it was already archived, the next successful run exports the current row again because the watermark is based on `last_updated_at`.

## Deployment order

1. Attach an IAM role to the RDS/Aurora PostgreSQL instance with the permissions in `iam_policy_requests_s3_archive.json`.
2. Ensure the S3 bucket is in the same AWS Region as the DB instance. AWS documents this as a requirement for `aws_s3.query_export_to_s3`.
3. Run `001_requests_s3_archive.sql` in the Saayam application database as a role allowed to create extensions and schema objects.
4. Edit `002_schedule_pg_cron.sql` and replace:
   - `<replace-with-request-archive-bucket>`
   - `<replace-with-aws-region>`
   - optional `kms_key_id`
5. Run `002_schedule_pg_cron.sql` as a role allowed to create and use `pg_cron`.

## Manual run

After configuring `archive.requests_s3_config`, run:

```sql
SELECT *
FROM archive.export_requests_to_s3_from_config();
```

Or pass settings directly:

```sql
SELECT *
FROM archive.export_requests_to_s3(
    'saayam-request-archive-dev',
    'us-east-1',
    'requests',
    NULL
);
```

## Verification queries

Check the latest runs:

```sql
SELECT run_id,
       status,
       watermark_start,
       watermark_end,
       source_row_count,
       uploaded_row_count,
       uploaded_file_count,
       uploaded_bytes,
       error_message,
       started_at,
       finished_at
FROM archive.requests_s3_runs
ORDER BY run_id DESC
LIMIT 20;
```

Inspect files for a successful run:

```sql
SELECT partition_date,
       s3_key,
       source_row_count,
       uploaded_row_count,
       uploaded_file_count,
       uploaded_bytes
FROM archive.requests_s3_run_files
WHERE run_id = <run_id>
ORDER BY partition_date;
```

The run is marked `success` only when `source_row_count = uploaded_row_count`. Failed runs leave the watermark unchanged, so the next run retries from the last successful watermark.

## Operational notes

- `aws_s3.query_export_to_s3` returns uploaded row, file, and byte counts; the function stores those values in the run log.
- `pg_cron` must be enabled in the DB parameter group before `CREATE EXTENSION pg_cron`.
- S3 exports are append-only. Re-archived updates are expected; downstream analytics should use the latest row per request by `req_id` and `last_updated_at` when a current-state view is needed.
- Source deletion is intentionally out of scope for this issue.
