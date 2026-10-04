# Steward volunteer review API — Issue #273

`steward_volunteer_review_api.py` is an AWS Lambda handler for the Steward
Dashboard's **Review Volunteers** view. It joins `users` and
`volunteer_applications` on `user_id`, returns review-ready applications newest
first, and applies pagination only after data from every configured region has
been merged.

## Lambda configuration

No credentials or Parameter Store paths are stored in source. Configure the
following Lambda environment variables instead:

| Variable | Purpose |
| --- | --- |
| `VIRGINIA_DB_PARAM` | SSM parameter name for the Virginia database credentials |
| `IRELAND_DB_PARAM` | SSM parameter name for the Ireland database credentials (optional) |
| `AWS_REGION` | AWS region for Parameter Store; defaults to `us-east-1` |
| `VOLUNTEER_REVIEW_STATUS` | Status that should appear in the review queue |

The local mock data currently uses `UNDER_REVIEW`, which is the fallback value.
Before deployment, run the issue's required query against the target database
and set `VOLUNTEER_REVIEW_STATUS` if it differs:

```sql
SELECT DISTINCT application_status FROM volunteer_applications;
```

## Local verification

The unit tests use fake connections and cursors, so neither AWS credentials nor
a database are required:

```powershell
python -m unittest data-analytics\lambda_functions\test_steward_volunteer_review_api.py -v
```

The tests cover parameterized filtering, order, cross-region merging,
pagination, an empty queue, safe database failures, and API Gateway request
body parsing.
