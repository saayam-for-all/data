# Archive verification results (#586)

| | |
| --- | --- |
| Run date | 2026-11-22 |
| Command | `python -m src.archive_verification.verify` |
| Source | local SQLite copy of the schema, 20 requests |
| Extract under test | **reference extract (fixture)** - see below |
| Archive | local directory |
| Result | **7 passed, 0 failed, 1 skipped** of 8 |
| Total | 0.110 s (0.084 / 0.088 / 0.099 s on repeat runs) |

## Read this before reading the results

**The extract these results describe is a fixture, not the production
pipeline.** Task 2 ([#574](https://github.com/saayam-for-all/data/issues/574))
owns the real `Data_ArchiveRequestData` extract. That issue is closed, but its
code is not merged into `dev`, `main` or `test` - verified with
`git merge-base --is-ancestor` against all three, and the name appears nowhere
in the tree. There was therefore nothing in this repository for #586's checks to
run against, so `fixture_extract.sql` was written to give them something real.

What these results establish: **the seven checks work, and they fail when they
should.** What they do not establish: that the deployed pipeline is correct.
That needs one command once Task 2's extract merges:

```bash
python -m src.archive_verification.verify --extractor src.their_module:extract
```

**No dev-database or S3 numbers appear in this document.** `CONTRIBUTING.md`
says contributors do not get that access, and none was used. Every number below
was measured against the local copy.

## Results

### 1. Row counts - PASS

Rows in the file match the source for the same window.

```sql
SELECT count(*) FROM requests
 WHERE last_updated_at >= '2026-10-01 00:00:00.000000'
   AND last_updated_at <  '2026-10-08 00:00:00.000000'
```

| | |
| --- | --- |
| Expected | 12 rows, from the source query above |
| Actual | 12 rows, parsed from `requests/20261001T000000000000-20261008T000000000000.csv` |

The count comes from the source, not from anything the file says about itself,
which is what #586 requires.

**Recorded aside, because it nearly went wrong:** counting lines in that file
gives **14**, not 12. `req_subj` and `req_desc` are free text and one fixture row
contains newlines, so `wc -l` and `readlines()` both overstate the row count.
The harness parses with `csv.reader` and prints the discrepancy on every run.

### 2. No duplicates - PASS

| | |
| --- | --- |
| Expected | 0 duplicate `(req_id, last_updated_at)`; no `req_id` twice within one file |
| Actual | 0 duplicate pairs across 21 rows in 2 files; no repeats within a file |

**The unique key is `(req_id, last_updated_at)`, not `req_id`.** Epic #416: *"
`last_updated_at` moves on update as well as insert, so a status change on an
already-archived request gets re-archived with its new value."* A `req_id`
appearing in two files is therefore correct, and a check keyed on `req_id` alone
would report correct behaviour as a failure.

This check creates that situation deliberately: `REQ-A-001` is archived in the
first window, updated, then archived again in the second. Both copies are
present, each with a different `last_updated_at`, and the run reports it as an
expected re-archive rather than a duplicate.

### 3. No gaps - PASS

Two adjacent runs, `[t0,t1)` then `[t1,t2)`, with nothing changed in between.

| | |
| --- | --- |
| Expected | 0 rows missing, 0 rows in both, the boundary tie group in run 2 only, watermark == `2026-10-08 00:00:00` |
| Actual | missing=none, in_both=none, boundary_in_run1=none, boundary_in_run2=`REQ-B-001, REQ-B-002, REQ-B-003`, watermark=`2026-10-08 00:00:00` |

Three rows share `last_updated_at = 2026-10-08 00:00:00.000000` **to the
microsecond**, sitting exactly on the boundary. A half-open window puts them in
the second run and only there. A closed window puts them in both; an exclusive
low bound puts them in neither.

The watermark advances to the window's upper bound, not to
`max(last_updated_at)` of the rows returned. Taking the max strands every row
that shares the boundary microsecond - mutation-tested below.

### 4. Joins resolve - PASS

| | |
| --- | --- |
| Expected | each readable column holds words drawn from its lookup table, no identifiers |
| Actual | `cat_name`=2 distinct, `req_for`=2, `req_islead`=2, `req_type`=2, `req_priority`=4, `req_status`=5 - all drawn from their lookups |

Each exported word is checked for membership in `SELECT <column> FROM <lookup>`
and rejected if it is all digits. The lookups are the committed
`database/lookup_tables/*.csv`, whose values match #573's DDL comments exactly.

Identifiers are kept **alongside** the words rather than replaced by them. That
is what makes check 5 provable: a row with an id present and its word empty is
visible evidence of a broken reference that survived.

### 5. Broken references survive - PASS

The failure #586 most wants ruled out. Both sub-cases were tested against actual
inserted rows, not inferred from reading the SQL.

| | |
| --- | --- |
| Expected | 12 rows exported, every broken reference retained |
| Actual | 12 rows exported; an inner join would have returned 10 |

**5a, null references - the case that actually occurs.** The fixture has 2 rows
with a null `lead_volunteer_id` and 2 with a null `beneficiary_id`; all four are
present in the export. Measured for comparison on the same window:

| Query | Rows |
| --- | --- |
| `LEFT JOIN users ON lead_volunteer_id` (correct) | **12** |
| `JOIN users ON lead_volunteer_id` (inner) | **10** |
| `LEFT JOIN help_categories` (correct) | **12** |
| `JOIN help_categories` (inner) | **11** |

Nothing about 10 or 11 looks wrong on its own. That is the point, and #573's DDL
says so about the real data: *"An inner join on `lead_volunteer_id` would
therefore return 3 rows of 221, and the row count would look small rather than
wrong."* In dev, `lead_volunteer_id` is null in **218 of 221** requests.

**5b, a non-null reference pointing at nothing.** `REQ-A-005` has
`req_cat_id = 'CAT-DOES-NOT-EXIST'`, which matches none of the 80 rows in
`help_categories`. It is exported with its `req_cat_id` intact and an empty
`cat_name`.

Creating it required disabling foreign key enforcement, and that is itself a
finding worth recording: **`req_cat_id` is `NOT NULL` and foreign-key
constrained, so a faithful copy of the schema physically rejects the row #586
asks for.** All nine references from `requests` are enforced constraints, so
production cannot reach this state by any ordinary write. What check 5b
therefore guards is narrower than it looks, and worth stating plainly:

* it does **not** show that such rows exist in the source - they cannot, while
  the constraints stand;
* it **does** show the export would retain one if a constraint were ever dropped,
  or if rows were loaded with constraints disabled.

A test (`test_schema_enforces_the_foreign_key_the_dangling_row_violates`) pins
the constraint itself, so this reasoning cannot quietly stop being true.

### 6. Re-runs are safe - PASS

The same window run twice.

| | |
| --- | --- |
| Expected | identical content, identical bytes, one stable archive key, no extra file |
| Actual | content_equal=True, bytes_equal=True, key_stable=True, extra_files_from_rerun=0 |

Three separate properties, reported separately so a failure can be diagnosed:

* **content** - the same rows;
* **bytes** - which needs `ORDER BY req_id`, since row order is otherwise
  unspecified. "Same content, different bytes" is reported distinctly from
  "different rows", because a missing `ORDER BY` and actual data loss would
  otherwise look identical in a report;
* **the archive key** - derived only from the window bounds, never from the
  clock. A key containing the run time would make a re-run write a second file
  rather than replace the first, which check 2 would then report as a
  duplicated request.

### 7a. Timestamps are UTC, clock independence - PASS

| | |
| --- | --- |
| Expected | every exported timestamp canonical and naive; watermark == the window's upper bound |
| Actual | 12 rows checked, all canonical and naive; watermark correct |

Run on a machine whose local offset is **UTC-05:00**, so this is not a test that
a UTC-configured machine could pass by accident. `format_timestamp` raises on a
tz-aware value rather than converting it, which is what catches
`datetime.now()` used where `datetime.now(timezone.utc)` was required.

### 7b. Timestamps are UTC, session time zone - SKIP

**Not run. Reported as skipped rather than passed.**

| | |
| --- | --- |
| Expected | byte-identical export and watermark under `SET TIME ZONE 'UTC'` and `'Asia/Kolkata'` |
| Actual | not run - a session time zone is a Postgres concept and the local copy is SQLite |

To run it, against a database with the real schema:

```bash
python -m src.archive_verification.verify \
    --source postgres --schema virginia_dev_saayam_rdbms
```

`Asia/Kolkata` is chosen deliberately: its **+05:30** offset catches an
implementation that assumes whole-hour offsets, which `America/New_York` would
not.

**This is the one acceptance criterion a local copy cannot settle, and there is a
specific reason to care.** `requests.last_updated_at` defaults to
`now() AT TIME ZONE 'UTC'`, which is session-time-zone independent and therefore
safe. But #573's schema dump also records a trigger `set_updated_at()` on that
column and **does not include its body**. If it writes `localtimestamp`,
`now()::timestamp` or `CURRENT_TIMESTAMP::timestamp`, the stored value follows
the session time zone and the extraction window shifts silently - exactly what
#586 warns about. Nothing short of running against the real database rules
that out.

## Do the checks actually catch anything

A suite that always passes is worth nothing, so each property was broken in turn.
All eight mutations were caught; the baseline was green beforehand. These are
kept as tests in `tests/test_archive_verification.py`.

| Mutation | Expected red | Actually red |
| --- | --- | --- |
| `LEFT JOIN help_categories` → `INNER JOIN` | 1, 5 | 1, 3, 5 |
| `LEFT JOIN users` (lead volunteer) → `INNER JOIN` | 1, 5 | 1, 3, 5 |
| closed window, `<=` on the high bound | 2 | 1, 2, 3 |
| exclusive low bound, `>` | 3 | 3 |
| watermark from `max(last_updated_at)` | 3 | 3, 7a |
| row order varies between runs | 6 | 6 |
| readable status replaced by its identifier | 4 | 4 |
| watermark from the local clock | 3, 7a | 3, 7a |

Three mutations tripped more checks than predicted, each for a sound reason: a
dropped row is both a count mismatch and a gap, and a closed window both
double-counts and duplicates.

## Timing baseline

| | |
| --- | --- |
| Total, end to end | **0.110 s** (0.084 / 0.088 / 0.099 s on repeats) |
| Slowest check | 6, re-runs are safe, 18.3 ms (it runs the extract twice) |
| Fastest check | 4, joins resolve, 11.1 ms |
| Test suite | 40 passed, 1 skipped in 1.92 s |

**This is a baseline for the harness, not for the pipeline, and should not be
quoted as one.** It covers 20 fixture requests against in-memory SQLite; dev has
221 and production will have far more. Most of each check's time is rebuilding
the fixture, including loading all 80 `help_categories` rows, rather than doing
the comparison.

The number that will matter for *"a baseline for comparison later"* is a run
against the real source, which needs the access this run did not have. The same
command produces it, and the per-check timings are already printed.

## Acceptance criteria

| #586 criterion | State |
| --- | --- |
| All checks have a recorded result | **Met** - 7 results above, plus 7b recorded as skipped with its reason |
| Row counts compared against the source for the same window, not reported from the file | **Met** - check 1 |
| The broken reference case tested against an actual row, not assumed from reading the SQL | **Met** - check 5, with the FK caveat stated |
| A re-run of the same window confirmed to produce an identical file | **Met** - check 6 |
| Timestamps confirmed UTC from a session that is not set to UTC | **Partly** - 7a passed on a UTC-05:00 machine; 7b, the Postgres session case, needs database access |
| Any failure written up with expected versus actual | **Met** - no failures; every check reports both either way |
| The script is committed and the document attached to this issue | **Script and document committed.** Attaching to the issue is not done here - the issue is deliberately left unedited. |

## Still outstanding

1. **Re-run against Task 2's extract** once #574's code is merged. Until then no
   result here describes the production pipeline.
2. **Run check 7b** against the real schema, and settle what
   `set_updated_at()` writes.
3. **Re-measure the timing** against a real-sized source.
4. **Swap the fixture's seeded rows for Task 7's generated data** once
   [#587](https://github.com/saayam-for-all/data/issues/587) lands, so the
   checks run over ~500 requests instead of 20. `data-analytics/sql/*.csv`
   cannot stand in meanwhile: those exports were taken months apart and are
   mutually inconsistent, which is the reason #587 exists.
