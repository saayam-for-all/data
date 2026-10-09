# Request Archival to Amazon S3

**GitHub Issue:** #416  
**Status:** Implementation complete locally; AWS integration validation pending.

## Overview

This Lambda function incrementally archives request records from PostgreSQL to Amazon S3 using the PostgreSQL `aws_s3` extension.

The implementation tracks the last successful archive using a database watermark. Source records are not deleted.

## Implementation

- `lambda_function.py` — AWS Lambda entry point.
- `helpers.py` — Database connection, incremental export, row-count reconciliation, and watermark management.
- `requirements.txt` — Python dependencies.
- `archive_watermark.sql` — Watermark table initialization, located under `data-engineering/sql/archive-requests-to-s3/`.
- `test_archive_requests_to_s3.py` — Unit tests, located under `data-engineering/tests/`.

## Archive Workflow

1. Connect to PostgreSQL using credentials from AWS Systems Manager Parameter Store.
2. Initialize the watermark table if necessary.
3. Retrieve the last successful archive watermark.
4. Determine the current archive window.
5. Count eligible request records.
6. Export the incremental records to Amazon S3.
7. Compare the source row count against the export's reported uploaded row count.
8. Advance the watermark only when the counts match.

The implementation does not delete source records.

## AWS Deployment Prerequisites

Before deployment, the following must be verified by the AWS/database administrators.

### PostgreSQL

- Confirm that the database supports the `aws_s3` and `aws_commons` extensions.
- Ensure the necessary extensions are installed.
- Grant the database user the required permissions to access the request table, manage the watermark table, and execute the export functions.
- Configure the database's AWS permissions to write to the designated S3 bucket.

### AWS Lambda

Configure these environment variables:

- `ARCHIVE_BUCKET` — Destination S3 bucket name.
- `AWS_REGION` — AWS region used for the S3 export.

Ensure the Lambda execution role can retrieve the required database credentials from Systems Manager Parameter Store and decrypt them when necessary.

The Lambda must also have network connectivity to the PostgreSQL database.

### S3

- Use a dedicated, access-controlled archive location.
- Verify the destination bucket and region.
- Configure appropriate encryption, retention, and access policies.
- Confirm that exported request data is permitted in the destination under the organization's privacy and data-handling policies.

### Deployment

The existing `deploy-lambda.yml` workflow packages Lambda-specific Python dependencies from `requirements.txt` and updates an existing Lambda function.

The workflow does not create the Lambda function, database extensions, S3 bucket, or associated AWS permissions.

The deployment package must be compatible with the configured Lambda runtime and architecture.

## Testing

Local unit tests:

```powershell
python -m pytest .\data-engineering\tests\test_archive_requests_to_s3.py -v
```

**Current result: 2 passed.**

The tests verify:

- The watermark does not advance when source and export counts differ.
- The watermark advances and the transaction commits when counts match.

These tests use mocked database connections. They do not validate live PostgreSQL or S3 integration.

## Outstanding Validation

Before production use:

- Verify database extension availability and permissions.
- Test a real export into an authorized test S3 bucket.
- Confirm exported file contents and row counts.
- Validate failure handling, retries, and overlapping executions.
- Review the archive's eligibility rules, timestamp handling, and treatment of sensitive data.
- Configure operational monitoring and an appropriate invocation schedule.

**Production deployment is not yet validated.**