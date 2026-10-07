# public.requests S3 archival

Issue #416 adds a database-side archival routine for `public.requests`.
The implementation lives in `data-engineering/infrastructure/db/archive/001_public_requests_s3_archive.sql`.

## Design

The routine creates a separate `request_archive` schema with:

- `request_archive.archive_watermarks`: one row for `public.requests`, holding the last successful `last_updated_at` watermark.
- `request_archive.archive_runs`: one row per archival attempt, including window bounds, source count, exported count, S3 object key, status, timestamps, and failure text.
- `request_archive.archive_public_requests_to_s3(...)`: a callable PL/pgSQL function that exports changed request rows to S3 through `aws_s3.query_export_to_s3`.

`public.requests` is read-only for this workflow. The routine only uses `SELECT` against `public.requests`; it never deletes, updates, inserts into, truncates, or cleans up that table.

## Incremental window

Each run reads the current successful watermark from `request_archive.archive_watermarks` and uses `p_window_end` as the upper bound.

Rows are eligible when:

```sql
last_updated_at IS NOT NULL
AND last_updated_at <= p_window_end
AND (current_watermark is initial OR last_updated_at > current_watermark)
```

The initial run archives all rows with a non-null `last_updated_at` through `p_window_end`. Later runs exclude rows exactly at the previous successful watermark and archive only rows whose `last_updated_at` has advanced beyond it. Updated requests become eligible again whenever their `last_updated_at` advances into a later archival window.

After a verified successful non-empty export, the watermark advances to the maximum `last_updated_at` actually selected for that run. Failed runs and count mismatches do not advance it. Zero-row runs are logged as successful with zero source/exported rows, but do not move the watermark.

## S3 object naming

Objects are written as partitioned CSV under a deterministic, auditable key:

```text
<prefix>/source_schema=public/source_table=requests/year=<YYYY>/week=<IW>/window_start=<UTC>/window_end=<UTC>/run_id=<run_id>/requests.csv
```

The default prefix is `archives/public.requests`. `run_id` is included so retries are auditable and do not overwrite earlier failed or partial attempts.

## Verification

The function first counts rows from `public.requests` for the archival window. After `aws_s3.query_export_to_s3` returns, the function compares `rows_uploaded` with that source count.

A run is marked `success` only when:

```text
source_row_count = exported_row_count
```

If the counts differ, the run is marked `failed`, the mismatch is recorded in `failure_message`, and the watermark remains unchanged.

## Prerequisites

Before using this in RDS/Aurora PostgreSQL:

- Enable the `aws_s3` extension in the target database. RDS also provides `aws_commons` for `create_s3_uri`.
- Attach an IAM role to the RDS instance/cluster that permits writing to the archival S3 bucket/prefix.
- Ensure the database role running the function can execute `aws_s3.query_export_to_s3` and can create/read/write the `request_archive` schema objects.
- Confirm `public.requests.last_updated_at` exists in the deployed database. The repository workbook lists a related `request` table with `last_update_date`; issue #416 specifically requires `public.requests.last_updated_at`, so the SQL follows the issue.
- Choose the S3 bucket, region, and optional prefix.

Example manual invocation:

```sql
SELECT request_archive.archive_public_requests_to_s3(
    p_s3_bucket := 'saayam-request-archive',
    p_s3_region := 'us-east-1',
    p_s3_prefix := 'archives/public.requests'
);
```

## Scheduling

This repository does not currently show an established `pg_cron` or database scheduler convention. The archival function is therefore independently callable and ready to be scheduled weekly by the database operations process used for the target RDS environment.

If the target RDS database already has `pg_cron` enabled, a weekly invocation can be scheduled there, for example:

```sql
SELECT cron.schedule(
    'archive-public-requests-to-s3-weekly',
    '0 6 * * 0',
    $$
    SELECT request_archive.archive_public_requests_to_s3(
        p_s3_bucket := 'saayam-request-archive',
        p_s3_region := 'us-east-1',
        p_s3_prefix := 'archives/public.requests'
    );
    $$
);
```

Do not add Lambda/EventBridge solely for this archival schedule unless the project adopts that as an explicit scheduling standard later.

## Before any future deletion work

Deletion or retention cleanup of `public.requests` is out of scope for issue #416.
Before any future deletion work is considered, verify:

- Recent `request_archive.archive_runs` rows are `success`.
- `source_row_count` equals `exported_row_count`.
- S3 objects exist under the recorded `s3_object_key`.
- CSV headers and row counts match the audit records.
- Downstream readers can load the archived CSV partitions.
