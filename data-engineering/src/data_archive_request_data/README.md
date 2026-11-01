# Data_ArchiveRequestData

Archives the `requests` table to S3 as **one enriched table** instead of six
separate ones (issue #574, Task 2 of the request archival pipeline).

Reference ids are resolved to readable values with a `LEFT JOIN` on each
referenced table's primary key, so the archived file can be read without the
lookup files, requests whose references are null or unmatched keep their row,
and no join can duplicate a request.

Deployed Lambda name: `Data_ArchiveRequestData`
Source folder for `deploy-lambda.yml`: `data_archive_request_data`

## Reference column mapping

The mapping is the Task 1 (issue #573) output expressed as code in
[`reference_mappings.py`](reference_mappings.py); the tables are the six lookups
that used to be exported alongside `requests`.

| Column in `requests` | Referenced table | Referenced column | Readable column | Export column |
| --- | --- | --- | --- | --- |
| `req_for_id` | `request_for` | `req_for_id` | `req_for` | `req_for` |
| `req_islead_id` | `request_isleadvol` | `req_islead_id` | `req_islead` | `req_islead` |
| `req_cat_id` | `help_categories` | `cat_id` | `cat_name` | `req_category` |
| `req_type_id` | `request_type` | `req_type_id` | `req_type` | `req_type` |
| `req_priority_id` | `request_priority` | `req_priority_id` | `req_priority` | `req_priority` |
| `req_status_id` | `request_status` | `req_status_id` | `req_status` | `req_status` |

`creator_id`, `beneficiary_id` and `lead_volunteer_id` also reference another
table (`users.user_id`). They are **not** enriched: the ids are already the
readable identifiers used across Saayam, and copying names, emails or phone
numbers into an S3 archive would move personal data out of the database. The
mapping for them is in `USER_REFERENCE_COLUMNS`, ready to enable if the team
decides the archive should carry those values.

## Export layout

Request columns keep their source order and each reference id is replaced in
place by its readable value. By default the raw id is kept immediately after the
readable value (`req_status`, `req_status_id`, …) so an unmatched reference stays
auditable in the file itself; set `ARCHIVE_INCLUDE_REFERENCE_IDS=false`, or pass
`"include_reference_ids": false` in the event, to export readable values only.

One CSV per run, written to:

```text
s3://<bucket>/<prefix>/archive_year=YYYY/archive_month=MM/archive_day=DD/run_ts=<ts>/requests_enriched.csv
```

## Memory and schema safety

Rows are streamed from a server-side cursor and written to the CSV as they
arrive, spilling from an 8 MiB memory buffer to the Lambda's `/tmp` when the
export outgrows it, so a run never holds the whole result set in memory. A
window holding more than `ARCHIVE_MAX_ROWS` rows (250,000 by default) is refused
with a message telling the caller to narrow the watermark window — that ceiling
matters because `ARCHIVE_WATERMARK_START` defaults to the epoch, so a run
invoked with no window would otherwise try to archive the whole table at once.

Before querying, the run reads the live columns of `requests` with a zero-row
`SELECT` and compares them against `REQUEST_COLUMNS`. A column added to the
table after this Lambda was written would otherwise be dropped from the archive
silently; instead the run stops and names it. Set
`ARCHIVE_FAIL_ON_SCHEMA_DRIFT=false` to archive anyway — the drift is still
reported in the validation summary.

## Validation

Every run is validated **before** anything is uploaded, and a failed validation
returns 500 and writes nothing to S3:

- the exported row count matches the source records selected for archival,
- the exported distinct request count matches the source request count,
- no `req_id` appears twice (joins did not duplicate requests) — checked as the
  rows stream past, which works because the export is ordered by
  `(last_updated_at, req_id)`, so the rows a join fans out for one request are
  adjacent,
- null and unmatched reference values are counted per reference column and
  reported, which confirms those requests are still in the export.

The summary is printed to CloudWatch as Markdown and returned in the response
body. `validation.format_validation_summary` renders the version to attach to
the issue.

## Configuration

Read from the event first, then the environment (`.env` locally):

| Setting | Event key | Environment variable | Default |
| --- | --- | --- | --- |
| Destination bucket | `bucket` | `ARCHIVE_S3_BUCKET` | required |
| Key prefix | `prefix` | `ARCHIVE_S3_PREFIX` | `requests_enriched` |
| KMS key | `kms_key_id` | `ARCHIVE_S3_KMS_KEY_ID` | none |
| Bucket region | `region` | `AWS_REGION` | none |
| Schema holding `requests` | `schema` | `REQUEST_ARCHIVE_SCHEMA` | `public` |
| Window lower bound (exclusive) | `watermark_start` | `ARCHIVE_WATERMARK_START` | `1970-01-01 00:00:00` |
| Window upper bound (inclusive) | `watermark_end` | — | now, UTC |
| Keep raw reference ids | `include_reference_ids` | `ARCHIVE_INCLUDE_REFERENCE_IDS` | `true` |
| Row ceiling for one run | `max_rows` | `ARCHIVE_MAX_ROWS` | `250000` |
| Stop on unexported columns | `fail_on_schema_drift` | `ARCHIVE_FAIL_ON_SCHEMA_DRIFT` | `true` |
| Validate without uploading | `dry_run` | — | `false` |
| Database connection | — | `DATABASE_URL` | required |

The window is `last_updated_at > watermark_start AND last_updated_at <= watermark_end`,
the same incremental boundary the archival pipeline already uses, so the caller
(EventBridge rule, or the existing scheduler) owns the watermark.

## Running locally

Contributors have no Lambda, S3 or RDS access, so the local run builds an
in-memory SQLite copy of `requests` and the six lookup tables from CSVs already
in the repository (`data-analytics/sql/requests.csv` and
`database/lookup_tables/*.csv`), calls the real `lambda_handler` with that
connection, and writes the "uploaded" object to disk through a mock S3 client.

From `data-engineering/`:

```bash
python -m src.data_archive_request_data.local_run
```

It writes to `datasets/cleaned/request_archive/` (gitignored, so no archived
data is committed):

- `requests_enriched.csv` — the sample export,
- `validation_summary.md` — the summary to attach to the issue,
- `validation_summary.json` — the same summary as data.

Useful flags: `--watermark-start`, `--watermark-end`, `--output-dir`,
`--no-reference-ids`.

The mock `requests.csv` carries ids the seeded lookup tables do not define
(`req_cat_id` values such as `CAT-TRANSPORT`, `req_for_id` values above 1), so a
local run reports a high unmatched count. That is mock-data drift, not a mapping
error: it is exactly the case the `LEFT JOIN` has to survive, and the local run
shows those requests exported with an empty readable value instead of being
dropped. Counts against the real database will be far lower.

## Tests

```bash
python -m pytest tests/test_data_archive_request_data.py -v
```

The tests run the real queries against SQLite fixtures that include a request
with resolvable references, one whose references match nothing, one with all
references null, a lookup table seeded with a duplicated key, and a requests
table carrying a column the export does not know about, and they pass a mock S3
client into the handler.

## Replacing the previous export

The existing Lambda that exports the six separate tables stays in place until
`Data_ArchiveRequestData` is deployed and a run is confirmed in S3 and in the
validation summary. Only then should it be removed, as the issue requires.

## Modules

| File | Purpose |
| --- | --- |
| `lambda_function.py` | Handler: configuration, run, validate, upload |
| `archive_runner.py` | Runs the queries and builds the validation summary |
| `query_builder.py` | Export, count and reference-audit SQL |
| `reference_mappings.py` | Reference columns and the tables they join to |
| `exporter.py` | CSV spool that spills to disk, S3 key layout, S3 upload |
| `validation.py` | Validation checks and the Markdown summary |
| `db.py` | Connection, streaming cursor, live-column probe |
| `local_run.py` | Local run against the repository's mock CSVs |
