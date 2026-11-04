Local implementation is available in **draft PR #584**: https://github.com/saayam-for-all/data/pull/584 (target: `test`).

`Data_ArchiveRequestData` exports one enriched requests CSV using nine LEFT JOINs. The local PostgreSQL validation selected **6 requests and exported 6 distinct request rows, with 0 duplicates**. Every reference retained its null and unmatched test values (1 of each per mapping). **34 tests passed with zero skips**, including duplicate-key rejection, concurrent changes, read-only execution, batched streaming, schema drift, CSV escaping, encryption, and upload failures.

- [Sample enriched requests CSV](https://github.com/saayam-for-all/data/blob/BVSSUMANTH_574_enriched_request_archive/data-engineering/docs/archive_requests/evidence/sample_requests.csv)
- [Validation summary](https://github.com/saayam-for-all/data/blob/BVSSUMANTH_574_enriched_request_archive/data-engineering/docs/archive_requests/evidence/validation_summary.md), [validation JSON](https://github.com/saayam-for-all/data/blob/BVSSUMANTH_574_enriched_request_archive/data-engineering/docs/archive_requests/evidence/validation.json), and [test results](https://github.com/saayam-for-all/data/blob/BVSSUMANTH_574_enriched_request_archive/data-engineering/docs/archive_requests/evidence/test-output.txt)
- [Mapping provenance, acceptance tracking, and deployment handoff](https://github.com/saayam-for-all/data/blob/BVSSUMANTH_574_enriched_request_archive/data-engineering/docs/archive_requests/README.md)

**Scope:** synthetic fixture on real PostgreSQL 18.4; S3 was mocked. **Task #573 remains pending** and production reference mappings/counts must be approved before deployment validation. No AWS resources or existing Lambda functions were changed. The previous Lambda must remain until the replacement is deployed and confirmed working by the team leads.

Screenshots below capture the generated report of actual local execution and exported data; they are not AWS console or terminal screenshots.

![Successful local execution: 34 passing tests, source 6, export 6, duplicates 0](https://raw.githubusercontent.com/saayam-for-all/data/5024adc0e04973c58ded1f9645b2cfc5eed75ee2/data-engineering/docs/archive_requests/evidence/local-execution.png)

![One enriched requests export retaining null and unmatched references](https://raw.githubusercontent.com/saayam-for-all/data/5024adc0e04973c58ded1f9645b2cfc5eed75ee2/data-engineering/docs/archive_requests/evidence/exported-output.png)

