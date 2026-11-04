# Data_ArchiveRequestData — issue #574

This local Lambda exports **one enriched requests CSV** from PostgreSQL. Every direct reference is resolved with a LEFT JOIN. No records or Lambda functions are deleted.

**Status:** local implementation and synthetic PostgreSQL validation complete. Task [#573](https://github.com/saayam-for-all/data/issues/573) is pending. The user authorized local implementation from the published schema while flagging this dependency. Production mapping approval, live counts, AWS deployment, and retirement of the previous Lambda remain team-lead actions.

## Files

- Runtime: `data-engineering/src/Data_ArchiveRequestData/lambda_function.py`
- Explicit mappings: `data-engineering/src/Data_ArchiveRequestData/reference_mapping.json`
- Example event: `data-engineering/src/Data_ArchiveRequestData/event.example.json`
- PostgreSQL acceptance tests: `data-engineering/tests/test_archive_requests.py`
- Synthetic database fixture: `data-engineering/tests/archive_fixture.py`
- Local reproduction and evidence scripts: `data-engineering/scripts/archive_requests/`
- Sample, machine-readable validation, logs, screenshots, SQL: this directory's `evidence/`

## Mapping provenance and pending Task 1

The published `data-analytics/sql/requests.csv` at commit [`443fc079091fce43058030ef1ac8bc1ef6cf9951`](https://github.com/saayam-for-all/data/tree/443fc079091fce43058030ef1ac8bc1ef6cf9951/data-analytics/sql) supplies the source column names. `request_statuses.csv` and `help_category.csv` in that directory supply those lookup column names. The [published schema metadata](https://github.com/saayam-for-all/data/blob/443fc079091fce43058030ef1ac8bc1ef6cf9951/database/mock-data-generation/db_info.json) supplies the remaining lookup keys and readable columns.

These sources differ: the older metadata calls the source `request`, uses `req_user_id`, and calls category/status tables `help_categories` and `request_status`. The newer CSV uses `requests`, `creator_id`, `beneficiary_id`, `lead_volunteer_id`, `help_category`, and `request_statuses`. The shipped JSON explicitly targets the newer shape. It does **not** guess which version production uses. Update the mapping to the completed Task 1 artifact before production deployment. Schema drift and incompatible declared foreign keys cause a validation error.

| Column in requests | Referenced table.column | Readable column | CSV output |
|---|---|---|---|
| creator_id | users.user_id | full_name | creator_name |
| beneficiary_id | users.user_id | full_name | beneficiary_name |
| lead_volunteer_id | users.user_id | full_name | lead_volunteer_name |
| req_for_id | request_for.req_for_id | req_for | request_for |
| req_islead_id | request_isleadvol.req_islead_id | req_islead | request_is_lead_volunteer |
| req_cat_id | help_category.cat_id | cat_name | help_category |
| req_type_id | request_type.req_type_id | req_type | request_type |
| req_priority_id | request_priority.req_priority_id | req_priority | request_priority |
| req_status_id | request_statuses.req_status_id | req_status | request_status |

Task 1 must confirm every production reference and separately record null/unmatched counts. The counts in this directory are explicitly synthetic, and do not replace that artifact. Whole-table Task 1 counts must be compared using the same population; the runtime summary covers only the selected archival population.

## Export behavior

The event must include a timezone-aware, exclusive `archive_before` cutoff and an explicit `status_ids` policy. `serviced_date` is interpreted as UTC because the published schema declares a timestamp without time zone. Confirm this convention with the database owner. Null serviced dates and dates at/after the cutoff are excluded.

```json
{"archive_before":"2026-01-01T00:00:00Z","status_ids":[3,4]}
```

Use status IDs approved by the data owner; no terminal-status list is assumed in code. The example file uses `status_ids: null` to explicitly include **all statuses**, including null/unmatched statuses, for the local fixture. It is a demonstration event, not a production retention policy.

Reference IDs are replaced with readable columns. SQL NULL is encoded as `\N`; empty strings remain empty. Literal backslashes are doubled, so an original literal `\N` becomes `\\N`. To decode, check for the exact `\N` null token first, then collapse doubled backslashes. CSV quoting preserves commas, quotes, Unicode, and embedded newlines. Unmatched non-null references become `[UNMATCHED: original_id]`; matched keys with empty/null labels become `[MISSING LABEL: original_id]`. All other request columns, including `req_id`, remain in the output.

Counts, lookup uniqueness checks, and the streamed query run in a single REPEATABLE READ, READ ONLY transaction. All nine references use LEFT JOIN. Each lookup key must be unique; duplicate keys cause failure before upload rather than choosing an arbitrary label. Selected request IDs must be non-null and unique. The sorted streamed output checks request identities again and verifies that exported count equals selected source count. A server cursor bounds memory use; the local CSV limit is 400 MB. Use smaller archival windows if it is exceeded. The SQL statement timeout is ten minutes.

Only after validation succeeds does the handler upload one CSV with boto3's managed transfer. An upload failure is raised to the caller. S3 metadata contains the source/export counts, validated flag, and CSV SHA-256; detailed reference counts are returned and logged. AES256 is the default encryption, with optional KMS. Each invocation uses a unique key; retries can create a second complete export of the same selection. This task does not add deletion, a watermark, or exactly-once orchestration.

## Reproduce locally

Requires Python 3.12 and an accessible PostgreSQL database in which the test user may create/drop test schemas. No AWS account or production credentials are required. Run from the repository/workspace root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r data-engineering/src/Data_ArchiveRequestData/requirements.txt -r data-engineering/docs/archive_requests/requirements-dev.txt
$env:TEST_DATABASE_URL = 'postgresql://archive_test@127.0.0.1:55740/postgres?connect_timeout=5'
.\.venv\Scripts\python.exe -m pytest data-engineering/tests/test_archive_requests.py -q --junitxml=data-engineering/docs/archive_requests/evidence/test-results.xml *> data-engineering/docs/archive_requests/evidence/test-output.txt
.\.venv\Scripts\python.exe data-engineering/scripts/archive_requests/run_local.py *> data-engineering/docs/archive_requests/evidence/local-execution.txt
.\.venv\Scripts\python.exe data-engineering/scripts/archive_requests/build_evidence.py
```

Create a dedicated local cluster if needed (adjust the PostgreSQL binary path):

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\initdb.exe' -D .local-postgres -U archive_test -A trust --encoding=UTF8 --locale=C
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D .local-postgres -l data-engineering/docs/archive_requests/evidence/postgres-local.log -o '-h 127.0.0.1 -p 55740' -w start
# Run tests and demo above, then stop only this dedicated cluster:
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D .local-postgres -m fast -w stop
```

The trust-authenticated cluster is loopback-only and for synthetic development data. The test suite creates unique schemas and drops only those schemas. If `TEST_DATABASE_URL` is absent, PostgreSQL tests skip; that is not full acceptance validation. The committed JUnit evidence records zero skips.

Screenshots are actual browser captures of `evidence/report.html`, a report generated from saved logs, JUnit, and the exact handler-uploaded CSV. They are labeled as rendered evidence, not terminal or AWS console screenshots. To recreate, install Playwright and Chromium, then run:

```powershell
node data-engineering/scripts/archive_requests/capture_evidence.cjs
```

`PLAYWRIGHT_MODULE` and `PLAYWRIGHT_EXECUTABLE` optionally select preinstalled tooling. The test environment's exact Python dependency versions are in `tested-requirements.txt`; they include Windows-only test dependencies and are not a Linux Lambda deployment lockfile.

## Deployment handoff (team leads)

The repository's [contributor guide](https://github.com/saayam-for-all/data/blob/main/data-engineering/CONTRIBUTING.md) assigns AWS deployment to team leads. No AWS resources were changed during this task.

1. Complete Task #573 and approve the production mapping, null/unmatched baseline, archival status policy, and timestamp convention. Verify all nine mappings and any additional production references. Reconcile schema naming differences in the mapping JSON.
2. Package for **Python 3.12, Linux x86_64**, with `lambda_function.py`, `reference_mapping.json`, and installed runtime dependencies at the ZIP root. `build_lambda.py` below creates this layout. Windows psycopg binary wheels must not be deployed to Lambda.
3. Create a separate function named **Data_ArchiveRequestData** with handler **lambda_function.lambda_handler**. Do not update/delete the existing function. Configure VPC access to RDS, verified database TLS with the AWS RDS CA bundle, adequate memory, a 900-second timeout, and at least 512 MB ephemeral storage.
4. Set environment variables below. Grant only database SELECT, S3 PutObject (and AbortMultipartUpload for managed-transfer failure cleanup), CloudWatch Logs, and required secret/KMS access. No DeleteFunction or database DELETE permissions are required.
5. Invoke with an approved small archival selection. Compare selected source counts and IDs, CSV counts and IDs, reference counts, S3 metadata hash, and readable labels. Repeat with null/unmatched cases. Save deployed invocation evidence and actual Task 1 comparison in the issue.
6. After deployment and confirmation, move the schedule to the new function, monitor a successful scheduled run, and obtain team-lead sign-off. Only then may the team remove the old Lambda. Its identity and deployment access were not supplied, so no deletion command is included.

| Environment variable | Purpose |
|---|---|
| DB_SCHEMA | Production schema; overrides JSON default |
| DB_SECRET_ID | Secrets Manager secret with host, port, dbname, username, password |
| DATABASE_URL | Alternative connection URL, injected securely; verified TLS enforced in Lambda |
| DB_SSLROOTCERT | Mounted/bundled CA bundle path for Secrets Manager connections; for DATABASE_URL supply sslrootcert in its connection options |
| ARCHIVE_BUCKET | Destination bucket, required |
| ARCHIVE_PREFIX | Key prefix, default requests |
| ARCHIVE_KMS_KEY_ID | Optional KMS encryption key |
| REFERENCE_MAPPING_PATH | Optional reviewed mapping JSON path |

`DB_SECRET_ID` takes priority over `DATABASE_URL`. AWS clients are created only when needed and credentials come from the execution role. No credentials are embedded in code or evidence.

```powershell
.\.venv\Scripts\python.exe data-engineering/scripts/archive_requests/build_lambda.py
```

The resulting `.build/Data_ArchiveRequestData.zip` is a local deployment artifact. This script packages only; it does not deploy or remove any function.

## Acceptance tracking

| Acceptance criterion | Evidence/status |
|---|---|
| New local Data_ArchiveRequestData Lambda | Runtime folder and real handler invocation |
| One enriched requests export | One captured upload; sample_requests.csv |
| Readable values replace matched IDs | All nine mappings exercised in PostgreSQL |
| Every lookup uses LEFT JOIN | export_query.sql and null/unmatched fixture assertions |
| Null/unmatched references retained | Each reference has 1 null and 1 unmatched selected synthetic request |
| No duplicate requests | 6 distinct selected/exported IDs; duplicate source/lookup keys rejected |
| Selected source and export counts match | 6 = 6, reported in validation.json; empty and filtered selections also tested |
| PR, sample, screenshots, validation linked/attached | [Draft PR #584](https://github.com/saayam-for-all/data/pull/584) and [issue attachments](https://github.com/saayam-for-all/data/issues/574#issuecomment-6388182308) published |
| Existing Lambda removed only after replacement works | Existing Lambda untouched; guarded team-lead retirement sequence above |

Local evidence establishes local behavior. It does not establish Task 1 completion, production schema compatibility, live source counts, deployed success, or permission to retire the previous Lambda.

