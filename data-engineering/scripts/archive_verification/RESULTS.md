# Results: verify the requests archive matches the source (#586)

**Status: verified on a local copy. Two checks fail on the Lambda as built, and both have the same cause. Production verification is pending database and S3 access.**

- Lambda under test: `Data_ArchiveRequestData` (#574), branch `Mango-gh_574_archive_request_data_lambda`
- Run on: 2026-11-24
- Tools: `verify_request_archive.py` (the checks), `run_local_harness.py` (local setup), `tests/test_archive_verification.py` (negative tests). See [README.md](README.md).

## 1. What was run, and why locally

Contributors have no database or S3 access yet, and the source database is read only, so a request with a broken reference cannot be created there. The checks were therefore run on a local copy:

- **Database:** PostgreSQL 16 with the schema rebuilt from the spreadsheet ([local_schema.sql](local_schema.sql); assumptions in section 6).
- **Lookup tables:** seeded from `database/lookup_tables/`.
- **Requests:** 13 seeded rows, each chosen for one check.
- **S3:** mocked in-process with moto. The Lambda's own upload code ran.
- **Lambda:** the real `lambda_handler`, with its database session set to `America/Phoenix`, not UTC.

| Run | Window | Purpose |
|---|---|---|
| 1 | (09:00, 10:00] | holds `REQ-V-007`, stamped exactly 10:00 (the boundary) |
| 2 | (10:00, 11:00] | resolvable rows, the broken-reference rows, `REQ-V-006` at exactly 11:00 |
| 3 | (10:00, 11:00] | re-run of run 2 (check 6) |
| — | — | then `REQ-V-010` is created at 11:30, `REQ-V-011` at 12:00, and `REQ-V-001` is edited (11:45) |
| 4 | (11:00, 12:00] | the request created between runs (check 3) |

All times are 2026-11-09, UTC. `REQ-V-012` (12:30) lies after every window and must appear in no file.

Two scenarios were run, each on a freshly built database:

- **as built:** the Lambda exactly as on the branch.
- **window-key fix:** the S3 key is built from the window instead of the run time, to show what checks 2 and 6 report once that is fixed.

## 2. Results

| # | Check | As built | With window-key fix |
|---|---|---|---|
| 1 | Row counts | **PASS** | **PASS** |
| 2 | No duplicates | **FAIL** | **PASS** |
| 3 | No gaps | **PASS** | **PASS** |
| 4 | Joins resolve | **PASS** | **PASS** |
| 5 | Broken references survive | **PASS** | **PASS** |
| 6 | Re-runs are safe | **FAIL** | **PASS** |
| 7 | Timestamps are UTC | **PASS** | **PASS** |

Two further checks can only be made on a local run:

| Check | Result |
|---|---|
| Default `watermark_end` is UTC when the process clock is not | **PASS** |
| Two different windows archived in the same second keep separate files | **FAIL** |

The results were identical in three consecutive harness runs.

### Check 1: Row counts (PASS)

- **Query (per run):**
  ```sql
  SELECT req_id, last_updated_at FROM virginia_dev_saayam_rdbms.requests
  WHERE last_updated_at > :start AND last_updated_at <= :end
  ```
  The result is compared with the file's rows by `req_id`.
- **Expected and actual:** 21 rows across 4 files; the files held 21.
- **The one difference was explained.** `REQ-V-001` is in the (10:00, 11:00] file but is no longer in that window in the source, because it was edited at 11:45, after the export. The verifier treats a row like this as explained, not missing. Production data changes after every export, so this case will be common there.

### Check 2: No duplicates (FAIL as built)

- **Method:** read every file in the manifest and group rows by `(req_id, last_updated_at)`.
- **Expected:** each version of a request in exactly one file.
- **Actual:** 8 request versions appear in two files. Those 8 rows are the whole (10:00, 11:00] window: run 3 wrote them a second time under a new key (see check 6).
- **With the window-key fix:** 0 duplicates.
- **Open decision:** `REQ-V-001` is in the (10:00, 11:00] file at 10:05 and in the (11:00, 12:00] file at 11:45, after its edit. That is two versions of one request, not a duplicate. The Lambda's window follows `last_updated_at`, so every edited request is archived again. The issue says "no request appears in two different files", which this design cannot meet. The verifier allows it by default and fails it with `--strict-unique-requests`. **The team needs to decide which is intended.**

### Check 3: No gaps (PASS)

- **Method:** sort the windows and check that each start equals the previous end. Then check that every source row in each window is in that window's file, at the same `last_updated_at`.
- **Actual:** 3 contiguous windows; 12 source rows checked; none missing.
- **Boundary rows:**
  - `REQ-V-007` (exactly 10:00) is in the (09:00, 10:00] file only.
  - `REQ-V-006` (exactly 11:00) is in (10:00, 11:00] only.
  - `REQ-V-010`, created between runs at 11:30, is in run 4's file only.
  - `REQ-V-012` (after every window) is in no file.

### Check 4: Joins resolve (PASS)

- **Query:** `SELECT <key>, <value> FROM virginia_dev_saayam_rdbms.<lookup>` for `request_for`, `request_isleadvol`, `help_categories`, `request_types`, `request_priorities` and `request_statuses`. Each file row's id is compared with its readable column.
- **Actual:** 98 references checked, 0 wrong. For example, status `1` came out as `MATCHING_VOLUNTEER`, category `5.1.2` as `ENT(EAR_NOSE_AND_THROAT)`, and priority `3` as `CRITICAL`.

### Check 5: Broken references survive (PASS)

- **Method:** find the source rows in each window whose reference id is NULL or absent from its lookup table. This is computed in Python from the window query and the lookup queries, so it cannot share a join mistake with the Lambda. Each such row must be in the file, with its id unchanged and an empty readable value.
- **Actual:** 4 of 4 archived correctly:

| Request | What is broken |
|---|---|
| `REQ-V-002` | `req_cat_id = 'CAT-MISSING'`, no such category (the case the issue names) |
| `REQ-V-003` | `req_cat_id` is NULL |
| `REQ-V-004` | every reference is NULL |
| `REQ-V-005` | every reference points at nothing (`req_status_id = 99` etc.) |

- **Negative test:** a test removes these rows the way an inner join would. Checks 1 and 5 both fail (`test_inner_join_export_fails_row_count_and_broken_reference_checks`), so a lower row count cannot slip through unnoticed.
- **Production:** whether real rows are already broken is Task 1's output. If a real window has none, this check reports SKIP rather than PASS.

### Check 6: Re-runs are safe (FAIL as built)

- **Method:** group the runs by window, then count the distinct S3 keys and compare the SHA-256 of their contents.
- **Expected:** one object per window, identical bytes on every run.
- **Actual:** the (10:00, 11:00] window run twice produced **2 objects**:
  - `run_ts=20261124T135904Z/requests_enriched.csv`
  - `run_ts=20261124T135905Z/requests_enriched.csv`

  The content was byte-identical (sha256 `c381405f0a04…`). Output is deterministic, so only the key is at fault.
- **Cause:** `lambda_function.py` builds the key with `build_s3_key(datetime.now(timezone.utc), prefix)`. The key depends on when the Lambda runs, not on the window. `upload_csv_to_s3` calls `put_object` without checking for an existing object.
- **With the window-key fix:** the re-run overwrites the same object, giving 1 object with identical bytes (PASS).

### Check 7: Timestamps are UTC (PASS)

- **Column types:** `information_schema.columns` shows `submission_date`, `serviced_date` and `last_updated_at` as `timestamp without time zone`.
- **Session time zone:** the window count was repeated after `set_config('TimeZone', tz, true)` for UTC, America/Phoenix and Asia/Kolkata. The counts were identical for every window: 2, 7 and 3 rows.
- **Exported values:** 57 timestamp values compared as text with the source read in a UTC session, including one with microseconds (`10:35:12.345678`). All equal.
- **Watermark:** every row lies inside its declared window, and no `watermark_end` is later than the UTC run time in its key.
- **Default watermark (local-only check):** run with the process clock set to America/Phoenix and no `watermark_end` given, the Lambda used 13:57:09 while the local clock read 06:57. That is UTC, 1 s from UTC now. PASS.
- **Why it held:** the Lambda passes the window as explicit UTC values and never asks the database for "now". The session time zone therefore cannot move the window while the columns stay `timestamp without time zone`. If the live column turns out to be `timestamp with time zone`, this check fails, and a negative test shows it does.

### Local-only check: same-second runs (FAIL)

- **Method:** the clock was frozen so two runs fell in the same second. The windows (09:00, 10:00] and (10:00, 11:00] were archived back to back.
- **Expected:** 2 objects.
- **Actual:** 1 object. Both runs wrote `collision/.../run_ts=20261124T130000Z/requests_enriched.csv`, so the second window's file replaced the first one's. The first window's rows are lost from S3, even though both runs returned 200.
- **When this bites:** a backfill loop over several windows. The window-key fix also fixes this.

## 3. Findings for the Task 2 owner (#574)

1. **The S3 key depends on the run time, not the window.** This is why checks 2 and 6 fail, and why runs in the same second overwrite each other. Suggested fix: build the key from the window, for example `requests_enriched/window_start=20261109T100000Z/window_end=20261109T110000Z/requests_enriched.csv`. The `window_key_fix` scenario shows checks 2 and 6 passing with it.
2. **The archive does not record its own window.** The window is only in the Lambda's response and its log, so an independent check needs a manifest. The fix above solves this too, or the window can go into the object metadata.
3. **The watermark is not stored anywhere.** `watermark_start` defaults to 1970-01-01, and the caller is expected to track it. Whoever schedules the Lambda decides whether windows chain without gaps. Check 3 can only verify the runs it is given.

## 4. Pending: needs database and S3 access

The checks still to run against production:

- **Check 1:** row counts against real data.
- **Check 5:** whether real windows contain broken references (Task 1 says whether any exist).
- **Check 7:** the live column types and the database's default time zone.
- **Timing:** the production baseline.
- **Checks 3 and 6:** need at least two consecutive real runs, and one re-run, which needs permission to invoke the Lambda.

The command, from `data-engineering/`, is in [README.md](README.md#running-it-against-the-real-archive):

```bash
python scripts/archive_verification/verify_request_archive.py --dsn "$DATABASE_URL" \
    --manifest runs.json --bucket <archive-bucket> --region us-east-1 \
    --list-prefix requests_enriched/ --report-dir scripts/archive_verification/reports/<date>
```

Record its output here when it has been run.

## 5. Time baseline

All figures are on the local copy (13 requests, 2–8 rows per window), so they only show the fixed overhead. Production will be dominated by query and S3 time; record it from the first real run.

| What | Time |
|---|---|
| Verifier, end to end, in process (evidence gathering + 7 checks) | 0.03 s (0.029–0.035 s over 6 runs) |
| Verifier from the command line, including Python start-up | 0.11 s wall |
| One Lambda invocation | 9–17 ms |
| Full harness: 2 scenarios + local-only checks | 9.8 s (about 9 s of it deliberate one-second pauses) |

## 6. Assumptions in the local schema

The spreadsheet is older than the database the Lambda was written against. Its README says the table names come from the previous pipeline that ran against the database. So the local schema takes **column types and keys from the spreadsheet** and **names from the Lambda**:

| Spreadsheet | Local copy and Lambda |
|---|---|
| `request` | `requests` |
| `request.req_user_id` | `requests.creator_id` |
| `request.last_update_date` | `requests.last_updated_at` |
| `request_type`, `request_priority`, `request_status` | `request_types`, `request_priorities`, `request_statuses` |

`beneficiary_id`, `lead_volunteer_id` and `deletion_reason` are not in the spreadsheet, so they are typed by assumption: `varchar(255)`, `varchar(255)` and `text`.

No foreign keys run from `requests` to the lookups, which is what allows broken references. Confirm all of this with the query at the top of [local_schema.sql](local_schema.sql) once there is access. The Lambda's own schema-drift check will also stop on the first run if the live column names differ.
