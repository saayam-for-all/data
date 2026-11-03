# Data_ArchiveRequestData (issue #574)

Lambda: `src/Data_ArchiveRequestData/lambda_function.py`. Exports the `requests` table as **one**
enriched CSV. The nine foreign-key columns documented in #573 are replaced by readable values:

| requests column | Lookup (LEFT JOIN) | Exported as |
|---|---|---|
| creator_id | users.user_id -> full_name | creator_name |
| beneficiary_id | users.user_id -> full_name | beneficiary_name |
| lead_volunteer_id | users.user_id -> full_name | lead_volunteer_name |
| req_cat_id | help_categories.cat_id -> cat_name | help_category |
| req_for_id | request_for.req_for_id -> req_for | request_for |
| req_islead_id | request_isleadvol.req_islead_id -> req_islead | is_lead_volunteer |
| req_type_id | request_types.req_type_id -> req_type | request_type |
| req_priority_id | request_priorities.req_priority_id -> req_priority | request_priority |
| req_status_id | request_statuses.req_status_id -> req_status | request_status |

`req_loc` / `created_loc` are exported as WKT text (`ST_AsText`).

## Why requests are neither lost nor duplicated

- Every lookup is a `LEFT JOIN`, so a null reference gives an empty cell instead of dropping the request
  (in dev, `lead_volunteer_id` is null for 218 of 221 requests; an inner join would keep 3).
- Every join is on the lookup table's primary key, so each request matches at most one row per lookup.
- The handler counts the selected requests and the exported rows inside one read-only
  `REPEATABLE READ` transaction and fails the run if they differ or a `req_id` repeats.

## Run

Event (optional): `{"last_updated_from": "...", "last_updated_to": "..."}`; default exports every request.
Env: `DB_HOST DB_PORT DB_NAME DB_USER DB_PASSWORD DB_SCHEMA S3_BUCKET S3_PREFIX LOCAL_OUTPUT_DIR`.

Local run and tests use a throwaway PostgreSQL 16 (synthetic data, schema from #573):

    python scripts/archive_request_data/run_local.py
    pytest tests/test_archive_request_data.py

## Validation summary (local synthetic run)

| Check | Result |
|---|---|
| Requests selected from source | 8 |
| Rows exported | 8 |
| Duplicate `req_id` in export | 0 |
| Requests with no lead volunteer retained | 6 of 6 |
| Requests with no beneficiary retained | 2 of 2 |
| Tests | 10 passed |

See `sample_requests_enriched.csv` and `local_run_output.txt`.

## Limits

- Synthetic data on local PostgreSQL 16. PostGIS is not installed locally, so geometry columns are text
  and `ST_AsText` is a pass-through stub in the test fixture. Not yet run against dev RDS or S3 (S3 is mocked).
- Because every reference is a declared foreign key, "unmatched" counts are 0 by construction; only null
  references occur (#573).
- The export contains `full_name` of requesters and volunteers (personal data). Confirm that is intended
  before pointing the Lambda at production.
- The existing Lambda must stay until this one is deployed and confirmed.
