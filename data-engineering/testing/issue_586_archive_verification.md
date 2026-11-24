# Issue #586 — verify the requests S3 archive matches the source database

## Scope and a caveat up front

Issue #586 asks to verify the real dev-database archive against the real
S3 bucket, with DB and S3 read access "to be provided." That access was not
available in this environment, and the issue was already independently
worked by another contributor (`hpant5`, self-assigned 2026-11-10, script
committed in the PR for #652, results posted on the issue 2026-11-17: 240
rows, all checks passing against the real `s3://saayam-virginia-archive/backup/requests/ingest_date=2026-11-17/`
export).

Given that, this is a second, independent pass: the deliverable script
(`data-engineering/scripts/verify_archive.py`) implements the issue's six
checks and is written to run against the **real** DB and S3 once credentials
exist (point `--s3-root` at `s3://<bucket>/<prefix>`, set `PGHOST`/`PGUSER`/
etc.). Since I don't have those credentials, I validated it the same way
issue #587's mock-data generator was validated: build a local Postgres
reproduction of the actual schema and archive logic, load realistic data
including the edge case the issue specifically calls for (a broken
category reference), run the real checks against it, and then prove the
checks aren't rubber stamps by deliberately injecting five kinds of faults
and confirming each one is caught. All of that lives in
`data-engineering/scripts/local_586_harness/`.

**What this does NOT prove**: that the real dev DB and the real S3 archive
agree. Only a run against the real systems proves that (as `hpant5`'s run
already did for the 2026-11-17 export). What it does prove: the
verification logic itself is correct and will catch a real divergence if
one is run against the actual archive.

## Results — clean local reproduction (301 rows, 5 day-partitions, run_id=1)

Command:
```
PGHOST=localhost PGPORT=55432 PGUSER=postgres PGPASSWORD=postgres PGDATABASE=saayam \
  python data-engineering/scripts/verify_archive.py --run-id 1 \
  --s3-root ./local_s3 --known-broken-ids REQ-BROKENREF
```

| # | Check | Result | Detail |
|---|-------|--------|--------|
| 1 | Row counts (source vs. files vs. run log) | PASS | source=301, archived=301, run log source=301, run log uploaded=301 |
| 2 | No duplicate `req_id` across files | PASS | duplicates: none |
| 3 | No gaps / no invented rows | PASS | missing from archive: none; in archive but not source: none |
| 4 | Every field of every row matches the source | PASS | 6,622 field values compared across 301 rows; mismatches: none |
| 5 | FK ids resolve to lookup-table labels | PASS | unresolved (excluding the known-broken row): none |
| 6 | Broken-reference row still present in the archive | PASS | `REQ-BROKENREF` (its `req_cat_id` points at a category row that was never created) expected and found |
| 7 | Re-running the same window twice is idempotent | PASS | sha256 of both runs: `a5a0396364727ac1...` (identical) |
| 7b | Watermark math is session-timezone independent | PASS (informational) | script always computes windows from UTC-aware `datetime.now(timezone.utc)`, never local time; confirmed the local host's own clock is 6 hours off UTC (Central time) while results were unaffected |

End-to-end runtime for one verification run against the local container: **0.226s** (301 rows, 7 checks). Not representative of real DB/S3 network latency, but shows the check logic itself is cheap.

## Fault-injection proof (`local_586_harness/fault_injection_test.py`)

Each row is: inject one fault into a copy of the clean archive file, re-run
`verify_archive.py`, confirm the expected check fails (and nothing passes
that shouldn't).

| Injected fault | Expected failing check | Result |
|---|---|---|
| Deleted a row | 1. row counts | CAUGHT (also tripped check 3, as expected — a missing row is both a count mismatch and a gap) |
| Duplicated a row | 2. no duplicate req_id | CAUGHT (also tripped check 1, since the file now has one more row than the source) |
| Changed a field (`req_subj`) | 4. every field matches the source | CAUGHT |
| Changed a FK to a nonexistent id (`req_status_id` → `999999`) | 4. every field matches the source | CAUGHT (also tripped check 5, since `999999` isn't in `request_statuses`) |
| Shifted a row (swapped `req_id` between two rows, so each row's other columns now belong to the wrong request) | 4. every field matches the source | CAUGHT |

One real bug was found and fixed while building this: the fault-injection
script's own "delete a row" mutation initially stripped the CSV header
instead of a data row (an indexing mistake in the test harness, not in
`verify_archive.py`) — it was corrected after the first run showed no check
failing at all, which was the signal something was wrong with the test
itself rather than the thing under test.

## What I'd still want flagged to the team

- The real export (`archive.export_requests_to_s3` in
  `001_requests_s3_archive.sql`) does `SELECT *` from `public.requests` —
  raw foreign-key ids, not joined labels. Issue #586's check 4 as written
  ("status, type, priority and category come out as readable words, not
  identifiers") implies the archived *file* should contain readable text.
  I read that as "the ids must be resolvable to readable labels" rather
  than "the file itself must already contain the labels," since the
  currently-deployed export never joins — but that's an assumption worth
  confirming with whoever wrote the issue, since the alternative reading
  would mean the export function itself needs to change, not just the
  verification.
- This local harness can't exercise the real `aws_s3.query_export_to_s3`
  path (it only exists on RDS/Aurora), so it says nothing about whether
  that specific AWS extension call behaves correctly — only that the
  watermark/partitioning/row-accounting logic it wraps does.
