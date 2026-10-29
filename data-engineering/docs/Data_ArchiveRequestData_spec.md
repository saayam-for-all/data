# Data_ArchiveRequestData: functional spec (#574)

## Why we are moving this data

From Rao (Oct 28):

1. Share request data with stakeholders as a data product, without leaking any PII or sensitive data.
2. Cut Aurora storage cost by moving cold request data to low cost S3.

These two goals need different things, so the Lambda writes **two copies** of the same export on every run.

| Copy | Who it is for | What is in it | Where |
|---|---|---|---|
| Backup | Us only (restore, audit, freeing up Aurora) | Every column of `requests`, plus the readable value for each reference | `{prefix}/backup/run_date=YYYY-MM-DD/requests_full.csv` in `bucket` |
| Shared | Stakeholders | De-identified columns only (see below) | `{prefix}/shared/run_date=YYYY-MM-DD/requests_shared.csv` in `shared_bucket` |

`prefix` defaults to `request_archive`. If `shared_bucket` is not given, both copies go to `bucket` under different prefixes. A separate bucket for the shared copy is recommended so access can be granted to it without exposing the backup.

## What the Lambda does

1. Reads `requests` once inside a read-only, repeatable-read transaction, so the count and the export see the same data.
2. LEFT JOINs every referenced table, so a request with a null or broken reference is never dropped.
3. Checks every lookup table for repeated keys. A repeated key would turn one request into two rows.
4. Validates before writing anything: exported count must equal the source count, and `req_id` must be unique. If either fails, nothing is written and it returns a 500 with the reason.
5. Writes the backup copy, then the shared copy, and returns the S3 keys, both counts and the null / unmatched counts per reference column.

It never writes to, updates or deletes from the database.

### References (from the schema attached to #573)

| Column in requests | Joins to | Readable value |
|---|---|---|
| req_cat_id | help_categories.cat_id | cat_name |
| req_for_id | request_for.req_for_id | req_for |
| req_islead_id | request_isleadvol.req_islead_id | req_islead |
| req_type_id | request_types.req_type_id | req_type |
| req_priority_id | request_priorities.req_priority_id | req_priority |
| req_status_id | request_statuses.req_status_id | req_status |
| creator_id | users.user_id | none (users has no readable column, the join only counts missing users) |
| beneficiary_id | users.user_id | none |
| lead_volunteer_id | users.user_id | none |

The list lives in `LOOKUPS` and `USER_REFS` at the top of `helpers.py`, so a change from #573 is a one line edit.

In the backup the original id is kept next to the readable value. When there is no match, the readable column is empty and the id is still there. In the shared copy the readable value is used, and the raw id is used as a fallback so the row is not blank.

## Column decisions

| Column | Backup | Shared | Reason |
|---|---|---|---|
| req_id | keep | drop | Internal key. Anyone with database access could link it back to a person. |
| creator_id, beneficiary_id, lead_volunteer_id | keep | drop, replaced by `has_beneficiary` and `has_lead_volunteer` | Direct links to people. Hashing still counts as personal data, so they are removed. |
| req_subj, req_desc | keep | drop | Free text. People write names, phone numbers and addresses here. |
| req_doc_link, audio_req_desc | keep | drop | Point at documents and recordings. |
| deletion_reason | keep | drop | Free text. |
| req_loc, created_loc | keep (as text) | drop | Exact points can identify a home. |
| submission_date | keep | `request_month` (YYYY-MM) | Exact timestamps plus other fields can single out a request. |
| serviced_date | keep | `days_to_service` (whole days) | Keeps the useful part, the turnaround time. |
| last_updated_at | keep | drop | Not useful to stakeholders. |
| category, request_for, islead, type, priority, status | keep id and readable | readable only | No personal data. |
| iscalamity | keep | `is_calamity` | No personal data. |
| to_public | keep | drop | Internal flag. |

## Which requests get archived

Not decided yet. The Lambda exports **all requests** by default. It also takes an optional `statuses` list (for example `[3, 4, 5, 6, 7]` for resolved, cancelled, deleted and rated) so we can switch to closed requests only without a code change.

## Storage guidelines

Backup bucket:
- Block all public access, default encryption with SSE-KMS, versioning on.
- Access limited to the data engineering leads.
- Lifecycle: S3 Standard for 30 days, then Glacier Instant Retrieval, then Glacier Deep Archive after 180 days. Retention period to be decided by leadership.

Shared bucket:
- Same encryption and public access block.
- Access granted per stakeholder, read only.
- Keep in Standard or Standard-IA, since it will be read.

Deleting rows from Aurora is **not** part of this Lambda. That should only happen after a backup file has been checked (row count matches and the file opens) and a restore has been tried once.

## Before selling any data

The shared copy is row level. Even without names, a rare combination (for example one request in a small category in a given month) can point at a person. Before it goes to a paying stakeholder I'd suggest one of these:
- share aggregated counts instead of rows, or
- drop rows from groups smaller than 10 before sharing.

## Event

```json
{"bucket": "backup-bucket", "shared_bucket": "shared-bucket", "prefix": "request_archive", "statuses": [3, 4, 5, 6, 7]}
```

Only `bucket` is required. Bad input returns 400, a failed check or database error returns 500 with the reason.

## Open questions

1. Which requests should be archived: all, or closed only?
2. Is the shared copy row level or aggregates only?
3. How long do we keep the backup?
4. Name of the old Lambda that exports six tables, so it can be retired once this one is deployed and confirmed working. It is not in this repo.
5. Do stakeholders need any location at all, for example state or country? That would need a separate decision since it is not in `requests` directly.

## Testing

- `pytest tests/test_data_archive_request_data.py`: join behaviour (null and unmatched references stay in, duplicate lookup keys are caught), status filter, the shared copy has no personal fields, handler input checks.
- `python tests/run_local_archive.py`: runs the handler on the mock CSVs in the repo with SQLite in place of Postgres and a local folder in place of S3, and writes a validation summary. Output goes outside the repo.

Not tested yet: the real Aurora database and real S3. That needs someone with access.
