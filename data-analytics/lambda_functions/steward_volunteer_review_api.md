# Steward volunteer review API — issue #273

Handler: `steward_volunteer_review_api.lambda_handler`. Dependencies: `boto3`
and `psycopg2` (as in the existing analytics Lambdas). No deployment is included.
Use the existing steward-authorized route; this handler does not authenticate callers.

Join `users.user_id` to `volunteer_applications.user_id`. Do not join
`volunteer_details`: acceptance creates that row and removes the application.
The response maps `volunteer_applications.last_updated_at` to `updated_time`;
`user_id` identifies the application for the frontend's Review action.

## Required configuration

- `DB_CONFIG_PARAMETER`: SSM SecureString parameter name, provided by the environment.
  Its JSON uses the existing KPI Lambda keys: `HOST`, `PORT`, `DATABASE NAME`,
  `USERNAME`, `PASSWORD`. AWS region and credentials use the normal boto3 chain.
- `DB_SCHEMA`: schema containing both tables; quoted as an SQL identifier.
- `STEWARD_REVIEW_STATUSES`: JSON array of exact, case-sensitive review statuses.
  There is deliberately no default. Missing/invalid configuration returns a safe 500.

Before setting the review statuses, run against the **target** database with the
appropriate schema/search path:

```sql
SELECT DISTINCT application_status FROM volunteer_applications;
```

Confirm which returned statuses represent applications requiring steward review
with the workflow owner. Repository CSV fixtures contain `APPROVED`, `DRAFT`,
`REJECTED`, `SUBMITTED`, and `UNDER_REVIEW`. These are not evidence of live values:
the reported current acceptance workflow uses `ACCEPTED`. The local tests use
`SUBMITTED` and `UNDER_REVIEW` as test configuration only. Target database status
and column verification remains required; no target credentials were supplied.

## Contract

Direct invocation accepts `{"page": 1, "page_size": 5}`. A `body` object or JSON
string is also accepted. Defaults are page 1 and 5 rows; page must be positive,
and page size must be 1–100. Invalid payloads return 400 before connecting.

The return value contains `statusCode`, JSON content-type headers, and an object
`body`, matching the ticket and existing KPI Lambda. A proxy integration must
serialize `body` using its response mapping (this is not a proxy-string response).

Rows contain only `user_id`, `updated_time`, and `volunteer_review: "Review"`.
Timestamps are ISO 8601 UTC; timezone-naive database timestamps are interpreted
as UTC, consistent with the local fixture convention. Confirm this convention
for the target database. Null timestamps return JSON null and sort last.
Results sort by latest application update, then user ID to stabilize ties.
The application table is expected to have one current application per user.
A single read-only SQL statement supplies the total and page from one snapshot.
Empty or out-of-range pages return 200 with `data: []`; total pages are zero
when there are no matches. Database/configuration errors return a generic 500
without SQL, credentials, or applicant details in the response or log message.

## Local validation

From the repository root, using an environment with the dependencies installed:

```sh
python -m unittest discover -s data-analytics/tests -v
```

Tests invoke the handler with mocked SSM/PostgreSQL connections and cursors,
and execute the query against an in-memory SQLite fixture with only PostgreSQL
array binding and placeholders adapted. They cover joins, excluded statuses,
sorting, ties, null timestamps, page sizes, totals, empty/out-of-range pages,
parameter binding, identifier quoting, validation, UTC conversion, cleanup,
and safe failures. They make no AWS calls. SQLite execution is not a substitute
for PostgreSQL/target-environment integration validation.
