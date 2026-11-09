# Task 574 — Data_ArchiveRequestData

This local implementation exports one enriched `requests` CSV. Six lookup tables
are joined with `LEFT JOIN`, all source columns are preserved, and readable labels
sit beside their IDs. Null and unmatched references retain their request rows.
Counts and uniqueness must reconcile before an upload can start.

All task files are contained here, on `ManishPatturu_Task574_ArchiveData`.
No deployment, push, PR, issue attachment, or deletion of an existing Lambda is
part of this local work.

## Run locally

Python **3.11 or later** is required. The demo and tests use only Python's standard
library; they require no packages, AWS credentials, PostgreSQL server, or network.
From the repository root in PowerShell:

```powershell
Set-Location 'data-engineering/src/Task 574'
python tools/run_checks.py
python local_run.py
```

`local_run.py` creates a temporary synthetic SQLite database, invokes the real
`lambda_handler` with injected local adapters, and writes the upload to
`evidence/requests_enriched.csv`. Socket connections are blocked during that
invocation. The source file hash and the source/export ID sets are compared after
execution. It never uses the older repository CSVs or reads production credentials.

Expected result: **12 selected, 12 exported, 12 distinct IDs, 0 duplicates**.
Each of the six lookup references has one null and one unmatched test value,
both retained. All nine request statuses are represented. One existing request
type has a null label, counted separately from an unmatched reference.

The fixture intentionally relaxes FK, NOT NULL and primary-key constraints to
test dirty input and duplicate-key rejection. Its timestamps are fixed UTC values
for reproducible runs; it is not a copy of the live database.

## Review the results

- [Sample enriched CSV](evidence/requests_enriched.csv)
- [Validation summary](evidence/validation_summary.md)
- [Machine-readable validation](evidence/validation_summary.json)
- [Actual execution transcript](evidence/execution.txt)
- [Test output](evidence/tests.txt)
- [Browser-readable report](evidence/report.html)
- [Execution screenshot](evidence/execution.png)
- [Export screenshot](evidence/export.png)

The screenshots capture the generated report of actual execution and actual CSV
values. They are browser report screenshots, not terminal or AWS console captures.
To regenerate them after the two commands above, install Playwright if needed and
use an installed Chrome or Edge browser:

```powershell
python tools/capture_evidence.py --channel chrome
# Or: python tools/capture_evidence.py --channel msedge
```

No screenshot/image generation service is used. The report has no external assets.

## Mapping and Task 573 provenance

The schema and completed reference spreadsheet were downloaded read-only from
[Task #573](https://github.com/saayam-for-all/data/issues/573):

- [Authoritative schema](references/saayam_schema.sql), originally
  [attached by the issue author](https://github.com/user-attachments/files/33914221/saayam_schema.sql).
- [Reference spreadsheet](references/requests_reference_columns.xlsx), originally
  [attached by KrupaP99](https://github.com/user-attachments/files/34229000/requests_reference_columns.xlsx).

The published counts describe **221 dev requests on October 24, 2026**. They are
historical evidence from the schema, not measurements made by this implementation.

| Request column | Reference table/key | Readable output | Historical unmatched | Historical null |
|---|---|---|---:|---:|
| req_cat_id | help_categories.cat_id | req_category ← cat_name | 0 | 0 |
| req_for_id | request_for.req_for_id | req_for | 0 | 0 |
| req_islead_id | request_isleadvol.req_islead_id | req_islead | 0 | 0 |
| req_type_id | request_types.req_type_id | req_type | 0 | 0 |
| req_priority_id | request_priorities.req_priority_id | req_priority | 0 | 0 |
| req_status_id | request_statuses.req_status_id | req_status | 0 | 0 |
| creator_id | users.user_id | Retain raw ID | 0 | 0 |
| beneficiary_id | users.user_id | Retain raw ID | 0 | 8 |
| lead_volunteer_id | users.user_id | Retain raw ID | 0 | 218 |

Use the plural table names from the authoritative schema. `help_categories_map`
is the category hierarchy and is not a request lookup. No user names are available
in the supplied schema; its users table was deliberately reduced to keys.

The original [Task #574](https://github.com/saayam-for-all/data/issues/574) wording
says to replace IDs with labels. The current task documentation in
[Mango-gh's branch](https://github.com/saayam-for-all/data/blob/Mango-gh_574_archive_request_data_lambda/data-engineering/src/data_archive_request_data/README.md)
and [rahulb0206's branch](https://github.com/saayam-for-all/data/blob/rahulb0206_574_archive_request_lambda/data-engineering/docs/Data_ArchiveRequestData_spec.md)
both report the later team clarification: preserve IDs alongside labels, join only
the six lookup tables, and retain raw user IDs, text and location. This implementation
follows that documented clarification. Those documents were consulted for scope;
the Python implementation, fixtures and tests here were written independently.

Task 573 remains open on GitHub, but its schema and completed mapping attachment
are available and agree. Its historical counts are included for provenance; the
runtime measures fresh counts for every selected export and never hard-codes 221.

## Export behavior

The default `{}` event exports a full snapshot, including requests with null
`last_updated_at`. Every status is eligible; no source rows are modified or deleted.
To select an incremental window, supply both bounds:

```json
{
  "watermark_start": "2026-10-24T00:00:00Z",
  "watermark_end": "2026-11-03T00:00:00Z"
}
```

The predicate is `last_updated_at > start AND last_updated_at <= end`. Bounds
must include a timezone and are normalized to naive UTC, matching the schema's
UTC convention for `timestamp without time zone`. Null timestamps are outside
incremental windows and their count is explicitly reported; use a snapshot to
include them. Set `"dry_run": true` to validate without creating an S3 client.
See [sample events](events).

The existing scheduler/caller owns watermark persistence. It must advance only
after a successful response with `uploaded: true`, preserve the same bounds on
retry, and supply an end bound behind current time by the team's agreed lag
(currently documented as five minutes). The lag must exceed application write
transaction duration; this timestamp export does not provide change-data-capture
guarantees for arbitrarily late commits. Lookup-only changes do not update a request
timestamp; run a snapshot when a full refresh of labels is required.

An unbounded event intentionally means a snapshot, not an automatically advancing
scheduled run. The Lambda creates no schedule and no watermark state files.

## Validation and resource handling

- All queries share one **read-only, REPEATABLE READ** PostgreSQL transaction.
  Counts, schema inspection, lookup validation and export therefore see one snapshot.
- Null or duplicate selected `req_id` values fail validation. Duplicate non-null
  lookup keys fail before the join, including duplicates in currently unused keys.
  No arbitrary `DISTINCT` or first-row selection hides conflicting values.
- Source columns are discovered in source order. Newly added fields are included;
  missing required fields and collisions with readable output names fail clearly.
- A PostgreSQL server-side cursor reads bounded batches. The CSV spool spills to
  temporary storage after 8 MiB. Row and byte ceilings prevent unbounded exports.
- Rows are ordered by `req_id`; adjacent duplicate IDs and total counts are checked.
  Each lookup separately reports matched, null, unmatched, and missing-label counts.
- UTF-8 CSV quoting preserves commas, quotes, Unicode and embedded newlines.
  SQL NULL is represented as an empty CSV field (as is empty text). Geometry is
  preserved in the driver's raw representation; binary values are hex-encoded.
- Validation finishes before S3 is constructed. Upload failures propagate as Lambda
  failures for scheduler retry. Connections and temporary files are always closed.
- Only one CSV is uploaded. Its SHA-256 is included in S3 object metadata and in
  the object name. Identical output retries reuse a key; changed output gets a new
  object so an earlier snapshot is retained. Consumers comparing multiple exports
  must reconcile by `req_id` and archival window, not blindly concatenate snapshots.

Object keys:

```text
<prefix>/requests/snapshot/<sha256>.csv
<prefix>/requests/window=<start>_<end>/<sha256>.csv
```

No lookup-table export files are written. The local evidence reports emulate the
upload interface; `uploaded: true` there means the **local sink** accepted the CSV.

## Production handoff (not executed)

AWS function name: **Data_ArchiveRequestData**.
Handler: **Data_ArchiveRequestData.lambda_function.lambda_handler**.

Package the `Data_ArchiveRequestData/` directory as a package at the ZIP root,
alongside dependencies from its `requirements.txt`. Build `psycopg2-binary` for the
selected Lambda Linux runtime/CPU architecture, not from Windows-installed wheels.
Use Python 3.11+ and enough `/tmp` storage for the configured byte ceiling.
The existing generic deployment workflow has not been modified; this task folder
requires explicit packaging by the deployment owner.

| Environment setting | Purpose / default |
|---|---|
| DATABASE_URL | Required PostgreSQL DSN; supplied securely by deployment owner |
| ARCHIVE_DB_SCHEMA | `virginia_dev_saayam_rdbms` |
| ARCHIVE_S3_BUCKET | Required unless `dry_run` is true |
| ARCHIVE_S3_PREFIX | `request_archive` |
| ARCHIVE_BATCH_SIZE | `1000` rows |
| ARCHIVE_MAX_ROWS | `250000` selected rows |
| ARCHIVE_MAX_BYTES | `268435456` bytes (256 MiB) |
| ARCHIVE_KMS_KEY_ID | Optional KMS key; otherwise explicit SSE-S3 AES256 |

`.env.example` is a template, not automatically loaded. The AWS runtime uses its
execution role; credentials are not accepted in invocation payloads. The database
connection has a 10-second connect timeout and 120-second statement timeout.
Use a database role restricted to SELECT on requests and the six lookups. The S3
role needs upload access to the configured prefix, multipart abort permission,
and the appropriate KMS permissions if KMS is selected. Apply the team's restricted
raw-backup bucket access policy; masking belongs to separate tasks #585/#586.

Before retiring the old Lambda, the deployment owner must verify the mapping
against the actual database, execute a controlled PostgreSQL/S3 run, compare source
and exported counts and IDs, inspect readable labels and unresolved references,
verify retries and scheduler watermark behavior, and confirm the new output with
the team. Only then switch the schedule and retire the previous function. Location
conversion and old S3 lookup-file cleanup remain separate tasks.

## Validation limits and acceptance status

All locally deliverable acceptance items are provided: implementation, sample
export, screenshots, validation report and repeatable tests. The suite includes
concurrent writer behavior, all six lookup failures, CSV round trips, dynamic
columns, window boundaries, resource limits, read-only operation, retries and
failed uploads. PostgreSQL adapter setup is checked with a test double.

No live PostgreSQL/PostGIS or S3 integration was run: neither PostgreSQL nor Docker
is installed in this workspace, and AWS access is not part of contributor testing.
SQLite verifies SQL join behavior but cannot prove driver/PostGIS or IAM behavior.
The publishing acceptance items (issue attachments and PR link), deployment, and
removal of the old Lambda are intentionally left to the owner after review, in
accordance with the request to keep all work local.

Driver/API references used for implementation:
[Psycopg connection and transactions](https://www.psycopg.org/docs/connection.html),
[server-side cursors](https://www.psycopg.org/docs/usage.html#server-side-cursors),
[Boto3 upload_fileobj](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/upload_fileobj.html).
