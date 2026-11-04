# Issue #574 validation summary

Scope: synthetic fixture on real PostgreSQL; S3 mocked. Task #573 is pending.

- Tests: 34/34 tests passed; 0 failed; 0 skipped.
- Selected source requests: 6.
- Exported requests: 6.
- Duplicate requests: 0.
- One enriched requests CSV was captured from the actual Lambda handler upload.
- All nine references use LEFT JOIN; every null and unmatched reference is retained.
- Each mapping has 4 matched + 1 null + 1 unmatched = 6 selected requests.
- Missing user labels are marked and retained (subset of matched keys).
- Duplicate lookup keys and duplicate/null source keys cause failure before upload.
- Empty/filtered selections, concurrent changes, read-only transactions, small cursor batches,
  CSV escaping, schema drift, encryption, and S3 failure propagation are covered.
- CSV SHA-256: `30ada6bf4002d6322754d4e801e2d0753737f02a1295296a1ecacb8e42324fe3`.

Artifacts: [sample CSV](sample_requests.csv), [validation JSON](validation.json),
[JUnit](test-results.xml), [execution log](local-execution.txt),
[execution screenshot](local-execution.png), [output screenshot](exported-output.png).

Screenshots capture the generated evidence report, not a terminal or AWS console.

Pending: Task #573 approved production mappings/counts, deployed validation,
and team-lead confirmation before retiring the previous Lambda. The old Lambda was untouched.
