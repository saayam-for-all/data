# Request archival to S3 (#416)

This package implements issue #416's schema contract, independently of older
schema metadata in this repository. PostgreSQL exports rows directly to S3.
There is no Lambda, Glue job, AWS access key, or source-row deletion.

## Files

- `001_setup.sql`: configuration, watermark, and durable run-log tables.
- `002_archive.sql`: the PL/pgSQL export procedure.
- `003_schedule.sql`: an explicitly installed weekly pg_cron schedule.
- `tests/`: disposable PostgreSQL integration tests with a mock S3 exporter.

## Source assumptions

The source is `public.requests`. `last_updated_at` is a non-null timestamp
maintained on every insert and update by the application/database. Prefer
`timestamptz`; timestamp-without-time-zone values are interpreted as UTC.
The pipeline does not install triggers, alter the source, or infer old column
names. All source columns are exported without transformations. Consumers need
the source primary key (assumed `req_id`) to identify request versions.

Source access is SELECT only. Metadata tables and the session's temporary
snapshot are separate from the source. A test verifies operation under a role
with SELECT-only source privileges.

## Batch behavior

1. Acquire a session advisory lock so two workers cannot archive concurrently.
   An overlapping invocation records `skipped` and exits.
2. Record and commit `running` before export. A subsequent worker marks a
   previously abandoned `running` entry as `interrupted` after obtaining the lock.
3. Read the successful watermark. The first run starts at negative infinity,
   exporting all available history through the cutoff; no age/status filter.
4. Choose a cutoff of now minus `safety_lag` (default five minutes). Select rows
   from watermark minus `replay_overlap` (default one day) through the cutoff,
   including both boundary timestamps.
5. Materialize that SELECT once into a temporary table. Count and export this
   same snapshot so changes to the live table during upload cannot affect counts.
6. Partition by the UTC **last-updated year and month**, exporting CSV with a
   header and UTF-8 encoding through `aws_s3.query_export_to_s3`.
7. Compare each partition's count with `rows_uploaded`, then reconcile run totals.
   Only a fully matching run commits a new watermark and `success` together.
   Empty batches succeed with zero files and advance the cutoff.

Object layout:

```text
s3://<bucket>/<prefix>/year=2026/month=10/run_id=123/requests.csv
```

AWS may split a large export into additional `requests.csv_part2`, `_part3`, etc.
The run manifest records the base key and number of files, plus row/byte counts.

## Failures, retries, and archive readers

Export exceptions and count mismatches persist `failed`, error text, expected
rows, and statistics from completed export calls. The previous watermark stays
unchanged. If an upload fails before returning statistics, actual partial S3
contents are unknown; logged counts describe acknowledged exports only.

S3 writes are not part of PostgreSQL's transaction. A retry gets a new run ID;
files from failed/interrupted runs may remain. Readers must select run IDs whose
metadata status is `success`, rather than blindly reading every object under the
prefix. Within successful runs, select the latest version per `req_id` ordered by
`last_updated_at`, using run ID to break replay ties. Preserve the successful run
manifest with the archive's operational metadata. Failed-object cleanup and a
downstream query layer are outside this change.

This is **at-least-once extraction**, not exactly-once delivery or full CDC.
Overlap and inclusive boundaries deliberately re-export some unchanged rows.
They catch equal timestamps and late commits within the configured replay window.
They cannot guarantee capture of arbitrarily late/backdated commits, hard deletes,
or every intermediate update between weekly runs. Set overlap/lag according to
the source's transaction behavior; out-of-window backdated changes require a
controlled backfill. Never claim timestamp watermarks solve unbounded lateness.

Use a dedicated database connection for each invocation, with autocommit enabled.
Do not wrap CALL in an explicit transaction: the procedure commits its run log.
Ordinary export failures return a WARNING to preserve the durable failure record.
**The runs table is authoritative; a successful CALL/cron exit alone does not
mean the export succeeded.** Monitor `failed`, `interrupted`, stale `running`,
and the age of the last successful run. A terminated worker may remain `running`
until the next invocation; pg_cron/database logs provide additional crash evidence.

## Team deployment (not performed by these scripts automatically)

1. Confirm the AWS PostgreSQL engine supports `aws_s3` and `pg_cron`. The database
   administrator installs extensions and configures pg_cron's parameter group.
2. Attach the appropriate S3-export IAM role to the RDS instance or Aurora
   cluster. Grant access only to the target archive prefix and any configured
   KMS key. No AWS credentials are passed to SQL or stored in configuration.
   The bucket must be in the exporting database's region.
3. Review the full-row archive's destination/access policy. Use a private archive
   bucket, not the public homepage-metrics bucket referenced elsewhere in the repo.
4. Apply `001_setup.sql` and `002_archive.sql` in the target database under the
   job owner. Configure the destination with environment-specific values:

   ```sql
   INSERT INTO requests_archival.config(job_name, bucket, region, prefix)
   VALUES ('requests', '<archive-bucket>', '<aws-region>', 'requests');
   ```

5. Grant the execution role SELECT on `public.requests`, TEMP on the database,
   access to the AWS export function, and the necessary schema/metadata/sequence
   privileges. Run as the package owner or grant EXECUTE on the procedure.
   No source mutation privileges are needed. PUBLIC cannot execute the procedure.
6. Execute a top-level `CALL requests_archival.archive_requests();`. Inspect the
   run record, download the files from the successful manifest, and verify CSV
   readability and row counts before enabling the schedule. Large first loads
   need sufficient database temporary-disk capacity; test this with realistic data.
7. Apply `003_schedule.sql` in the database containing pg_cron, with
   `target_database` set to the database containing this package. The default is
   Sunday at 02:00 in pg_cron's configured timezone; configure that timezone as
   UTC or explicitly account for it. The job uses the invoking user's privileges.

   ```sh
   psql -v target_database=saayam -v cron_expression='0 2 * * 0' -f 003_schedule.sql
   ```

The stable job name updates an existing schedule rather than adding another.
To pause scheduling, the administrator can call
`cron.unschedule('requests-archive-weekly')`. This does not delete archives or
source rows. Do not reset a production watermark except as a reviewed backfill.

Monitor with:

```sql
SELECT run_id, status, source_rows, uploaded_rows, error_message
FROM requests_archival.runs ORDER BY run_id DESC LIMIT 20;
SELECT * FROM requests_archival.watermark;
```

## Local tests

Use a dedicated disposable PostgreSQL instance and a database named `issue416_*`.
The tests reject non-loopback hosts and other database names. They recreate the
fixture schemas/table in that database; never use a shared database. psycopg2 is
already a repository dependency. No AWS access is needed.

From the repository root in PowerShell, with the dedicated local server running:

```powershell
$env:ARCHIVAL_TEST_DSN = 'host=127.0.0.1 port=55416 dbname=issue416_tests user=postgres'
.\venv\Scripts\python.exe -B data-engineering/scripts/requests_archival/tests/test_archival.py
```

These tests execute real PL/pgSQL transactions, partition queries, role checks,
and locks. Only the AWS exporter is replaced. They cover backfill, incremental
inserts/updates, zero rows, timestamp ties, lag/overlap, mismatches, full/partial
upload failures, retries, overlapping jobs, interrupted workers, source changes
during export, and SELECT-only source privileges. They do not establish real
S3 connectivity, actual AWS CSV serialization, IAM correctness, or pg_cron
installation. Those require the team's AWS integration verification.

References: [issue #416](https://github.com/saayam-for-all/data/issues/416),
[AWS export function](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/postgresql-s3-export-functions.html),
[pg_cron on RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL_pg_cron.html),
[PostgreSQL procedure transactions](https://www.postgresql.org/docs/current/plpgsql-transactions.html).
