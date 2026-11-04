# Add Data_ArchiveRequestData enriched requests export (#574)

Published as [draft PR #584](https://github.com/saayam-for-all/data/pull/584), targeting `test`. Evidence is [linked on issue #574](https://github.com/saayam-for-all/data/issues/574#issuecomment-6388182308). Task #573 and deployed validation remain pending; this change does not close #574.

## Problem and behavior

Issue #574 requires replacing a multi-table archive with one readable requests CSV while retaining requests with broken or null references. Add the locally developed `Data_ArchiveRequestData` Lambda with nine explicit LEFT JOIN mappings, including creator, beneficiary, and lead-volunteer names. Preserve all non-reference request fields and mark unmatched IDs or missing labels visibly.

Validate lookup uniqueness and source request identities, stream from one REPEATABLE READ / READ ONLY snapshot, and refuse upload when validation fails. Upload one encrypted CSV only after selected source and exported counts match. Include sample output, screenshots of a report built from actual local execution, machine-readable validation, PostgreSQL tests, and a team-lead deployment/retirement runbook.

## Validation

- Real PostgreSQL 18.4, synthetic requests, mocked S3 boundary.
- Selected source requests = 6; exported requests = 6; duplicates = 0.
- Every reference has 1 null and 1 unmatched selected request, both retained.
- PostgreSQL tests cover all mappings, duplicate keys, filters/cutoffs, empty exports, concurrency, read-only transactions, cursor batches, schema drift, CSV escaping, encryption, and upload failures. All 34 tests passed with zero skips; see JUnit and test-output.txt.
- Linux x86_64 Python 3.12 deployment ZIP built; ZIP layout and platform libraries checked.
- Ruff import/syntax checks passed.

Evidence in the proposed branch:

- [Sample enriched requests CSV](evidence/sample_requests.csv)
- [Validation summary](evidence/validation_summary.md)
- [Machine-readable validation](evidence/validation.json)
- [Local execution screenshot](evidence/local-execution.png)
- [Exported output screenshot](evidence/exported-output.png)
- [Execution report](evidence/report.html)
- [Setup, mapping provenance, acceptance tracking, deployment handoff](README.md)

## Pending dependency and deployment

Task #573 remains open without an approved mapping/count artifact. With the user's authorization, local implementation follows the published newer requests CSV plus lookup schema metadata; known schema naming differences are documented. These are synthetic local results, not production counts.

Team leads must reconcile the completed Task 1 mappings, select the archival policy, deploy the new function separately, validate it against the live database/S3, switch the schedule, and confirm success before removing the previous Lambda. No AWS resources or existing Lambda functions were changed.

Related: https://github.com/saayam-for-all/data/issues/574
Dependency: https://github.com/saayam-for-all/data/issues/573



