# Data_ArchiveRequestData (#574)

Replaces the six-table export in `saayam-archive-fn` (#416) with one export of `requests`, with the
six lookup tables joined in so the file can be read without separate lookup files.

## Scope

Agreed on #574 (Oct 29):

- **Copy, not move.** The only statement run against application tables is `SELECT`. Nothing is
  deleted from the database. Status based clean up of old data is a separate, future task.
- **All rows.** No status filter. A row is exported again whenever `last_updated_at` changes, which
  is intended and gives us the history. Filtering to closed requests would mean an open request
  never reaches the archive.
- **Keep ids and readable values.** `req_status` sits next to `req_status_id` rather than replacing
  it. The id is the join key for reconciling the archive against the source later.
- **Raw values, no masking.** This is the backup copy only. User ids, free text and location are
  exported as they are. A second, PII masked copy for stakeholders comes after #585 and #586, in a
  separate bucket.
- **Only the six lookup tables are joined.** `users` is not joined.

## Joins

| Column in requests | Joins to | Readable value |
|---|---|---|
| req_cat_id | help_categories.cat_id | cat_name |
| req_for_id | request_for.req_for_id | req_for |
| req_islead_id | request_isleadvol.req_islead_id | req_islead |
| req_type_id | request_types.req_type_id | req_type |
| req_priority_id | request_priorities.req_priority_id | req_priority |
| req_status_id | request_statuses.req_status_id | req_status |

All six are `LEFT JOIN`. A request with a null or unmatched reference stays in the file, with its id
kept and the readable column empty. The list is `LOOKUPS` at the top of `helpers.py`.

## One run

```
read watermark -> select (watermark, now - 5 min] -> validate -> upload CSV -> advance watermark
```

- The window is half open, `(lo, hi]`, on `last_updated_at`, so a row stamped exactly on a bound
  belongs to one run only.
- The upper bound is 5 minutes in the past. `last_updated_at` is set when the statement runs but the
  row is only visible once the transaction commits, so reading up to `now()` could skip a row for good.
- The count and the export run in the same read only, repeatable read transaction.
- Before anything is written: the exported count must equal the count in the window, `req_id` must be
  unique, and no lookup table may have a repeated key (that would turn one request into two rows).
  If any check fails it returns a 500, writes nothing and leaves the watermark alone.
- The watermark moves only after S3 has the file. A run that dies partway leaves it unmoved, and
  the S3 key comes from the window, so the retry overwrites the same file instead of duplicating it.
- Requests with a null `last_updated_at` can never fall in a window. They are counted and reported
  in every run rather than skipped quietly.

## S3 layout

```
{prefix}/requests/ingest_date=YYYY-MM-DD/requests_{from}_{to}.csv
{prefix}/_state/watermark.json
```

`prefix` defaults to `request_archive`. The watermark lives in the bucket, so the Lambda never writes
to the database. This is the same idea as `STATE_STORE=s3` in `saayam-archive-fn`.

## Invocation

```json
{"bucket": "archive-bucket", "prefix": "request_archive"}
```

`bucket` can also come from the `BUCKET` environment variable, so the schedule can send an empty
payload. For a backfill, pass `"from"` and `"to"` (UTC). That runs exactly that range and does not
read or move the watermark.

Bad input returns 400. A failed check, database error or S3 error returns 500 with the reason.

## Storage guidelines for the backup bucket

- Block all public access, default encryption with SSE-KMS, versioning on.
- Access limited to the data engineering leads. The file holds raw user ids and free text.
- Lifecycle: S3 Standard for 30 days, then Glacier Instant Retrieval, then Glacier Deep Archive after
  180 days. Retention period to be decided by leadership.
- Reserved concurrency of 1 on the Lambda, so two runs can't read the same watermark at once.

## Not in this task

- PII masking and the stakeholder copy (#585, #586).
- Decoding `req_loc` from EWKB hex to readable coordinates (subtask 3 in the #416 approach doc).
  It is exported as text for now.
- Removing `saayam-archive-fn` and its lookup table files in S3. Only after this Lambda is
  deployed and confirmed working.
- Deleting old rows from Aurora.

## Testing

- `pytest tests/test_data_archive_request_data.py`: joins, null and unmatched references, duplicate
  lookup keys, the watermark (first run, no changes, an updated row, a row inside the 5 minute lag,
  a failed upload, a backfill range, a row on a window boundary) and handler input checks.
- `python tests/run_local_archive.py`: three runs of the handler on the mock CSVs in the repo, with
  SQLite in place of Postgres and a local folder in place of S3. Writes a validation summary outside
  the repo.

Not tested yet: the real database and real S3. Reconciliation against the source is planned once
it is deployed.
