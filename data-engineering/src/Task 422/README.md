# Task 422: Profanity severity and Help Request routing

Local implementation of [issue #422](https://github.com/saayam-for-all/data/issues/422).
All task code, tests, examples, and configuration live in this folder. Nothing
needs to be pushed or deployed to run it.

The workflow validates a Help Request, calls the existing Profanity API, returns
a severity score, and commits the request to its destination before acknowledging
success. It includes a Flask HTTP service and an optional Lambda entry point.
The classifier itself is not reimplemented.

## Run the complete local demo

From the repository root, using PowerShell and Python 3.10+:

```powershell
Set-Location 'data-engineering/src/Task 422'
# Only needed if these dependencies are not already installed:
python -m pip install -r requirements-dev.txt

python -m pytest -q
python -m profanity_routing demo
```

The demo starts two temporary HTTP servers on `127.0.0.1`, uses the real HTTP
client between them, writes to `task422_demo.sqlite3` in this folder, prints the
results, and shuts down both servers. It needs no API keys, AWS access, or remote
database. The mock returns fixed fixtures; it does **not** classify arbitrary text.

Verified locally: **105 tests passed**. The demo verifies all four scores, a
request with multiple categories, an API outage, an HTTP-200 response containing
a model failure, and an idempotent retry. Expected database contents:

| Table | Rows | Meaning |
| --- | ---: | --- |
| `request` | 1 | Score 0, ready for matching |
| `fraud_requests` | 4 | Scores 1, 2, 3, and the mixed-category fixture |
| `profanity_screenings` | 5 | Durable scores, original submissions, and routing receipts |

Rerunning the demo replays its five saved submissions without adding duplicates.
SQLite files and Python/test caches are ignored by Git.

## Routing policy

| Score | Meaning | Destination | State |
| --- | --- | --- | --- |
| 0 | Normal | `request` | `ready_for_matching` |
| 1 | Profanity | `fraud_requests` | `held_for_review` |
| 2 | Depressive or suicidal content | `fraud_requests` | `held_for_review` |
| 3 | Threatening content | `fraud_requests` | `held_for_review` |

Multiple flagged categories use the highest score and preserve every category
in the response. The `fraud_requests` name comes from the existing repository;
using it as a review holding area does not label the requester as fraudulent.

The issue does not specify the destination mapping. The policy above follows
the repository's existing fraud table and the mapping described in
[PR #487](https://github.com/saayam-for-all/data/pull/487). Other PR descriptions
were consulted for context; their implementation code was not copied. This
mapping and highest-score precedence are explicit local assumptions to confirm
with the maintainers before deployment.

Score 0 is actually persisted in the local `request` table. This service does
not run the external volunteer-matching service; receipts explicitly report
`matching_invoked: false`. A production caller must use this as the submission
gate and let its existing matching worker consume approved requests. It must
not separately insert the same request or treat a failed check as approval.

## Run interactive local services

In one PowerShell terminal, from this folder:

```powershell
python -m profanity_routing mock-api --port 5011
```

In a second terminal, from this folder:

```powershell
$env:PROFANITY_API_URL = 'http://127.0.0.1:5011/check-profanity'
$env:PROFANITY_ALLOW_LOCAL_HTTP = 'true'
python -m profanity_routing init-db
python -m profanity_routing serve --port 5010
```

In a third terminal, from this folder:

```powershell
Invoke-RestMethod -Method Post `
  -Uri 'http://127.0.0.1:5010/api/help_requests' `
  -ContentType 'application/json' `
  -Body (Get-Content -Raw 'examples/help_request.json')
```

Use a new `request_id` when changing a submission. The mock recognizes these
exact subjects: `Normal fixture`, `Profanity fixture`, `Support fixture`,
`Threat fixture`, `Mixed fixture`, `API outage fixture`, `Model failure fixture`.
Unknown subjects return an error rather than a fabricated score. Stop each
interactive server with Ctrl+C.

## Endpoint contract

`POST /api/help_requests` and its alias `POST /api/check_profanity` both screen
**and persist** a full submission. `GET /health` is a process liveness check.

```json
{
  "request_id": "request-001",
  "user_id": "user-001",
  "subject": "Need groceries",
  "description": "Please help me find a nearby food pantry.",
  "category_id": "food",
  "location": "Chicago"
}
```

`request_id`, `user_id`, `subject`, and `description` are required nonempty
strings. `category_id` and `location` are optional. Limits follow the repository's
schema: IDs 255 characters, subject/location 125, description 255, category 50.
Unknown fields, including caller-provided scores, are rejected. The HTTP body
limit is 16 KiB. Only subject and description are sent to the Profanity API.

Example success:

```json
{
  "request_id": "request-001",
  "severity_score": 0,
  "severity_label": "normal",
  "flagged_categories": [],
  "classification_status": "complete",
  "destination": "active_matching",
  "destination_table": "request",
  "workflow_status": "ready_for_matching",
  "recorded": true,
  "matching_invoked": false,
  "replayed": false
}
```

| HTTP status | Meaning |
| --- | --- |
| 200 | Complete classification and committed routing, including held requests |
| 400 | Invalid submission or malformed JSON |
| 409 | A request ID was reused with different content or identity |
| 413 | HTTP body exceeds the size limit |
| 503 | Classification unavailable or database write failed; retry later |

Identical retries return the stored receipt with `replayed: true` without calling
the API again. Concurrent duplicates commit only one destination row. A database
failure rolls back the destination and ledger together. API failures write
nothing and never become score 0; they can be retried with the same request ID.
Error responses do not include upstream text, credentials, or database details.

## Existing Profanity API compatibility

The request contract was checked against the original
[inappropriate-content filter source](https://github.com/saayam-for-all/data/blob/vighneshsridhar-inappropriate_content_filter/inappropriate_content_filter.py),
which accepts `subject` and `description` and returns four booleans. The adapter
accepts these documented forms:

- `{"severity_score": 0}` with a genuine integer from 0 to 3.
- All four strict boolean fields: `contains_profanity`,
  `contains_depressive_content`, `contains_suicidal_content`, and
  `contains_threatening_content`.
- A `severity_scores` list containing all four `score`/`flagged` entries.
- These payloads directly or inside a successful Lambda `statusCode`/`body`
  envelope, with `body` as JSON text or an object.

If representations coexist, they must agree. Missing flags, non-boolean flags,
fractional/string scores, contradictory normal/flagged categories, non-2xx
statuses, explicit error markers, degraded classification, partial results,
timeouts, redirects, and invalid JSON are rejected.

The original Lambda can report an internal `status_code: 500` and `Error`
inside an outer HTTP-200 success response. The adapter checks both layers, so
that model failure cannot silently enter active matching.

## Configuration and integration

The CLI reads environment variables. `.env.example` documents them; `.env`
files are **not** loaded automatically.

| Variable | Default / use |
| --- | --- |
| `PROFANITY_API_URL` | Required by `serve` and Lambda; full HTTPS endpoint |
| `PROFANITY_API_KEY` | Optional API Gateway `x-api-key`; never a caller-supplied header |
| `PROFANITY_API_TIMEOUT` | 10 seconds, finite and greater than 0, at most 60 |
| `PROFANITY_ALLOW_LOCAL_HTTP` | `false`; opt-in HTTP for loopback fixtures only |
| `TASK422_DATABASE_URL` | SQLite `task422.sqlite3` in this folder |
| `TASK422_DB_SCHEMA` | Required for PostgreSQL; leave unset for SQLite |
| `TASK422_ACTIVE_STATUS_ID` | Local value 1; actual approved status ID required for PostgreSQL |

The `demo` command deliberately uses its own local configuration, ignoring any
remote API/database environment settings. Other commands require explicit
configuration. There are no network calls or database changes on module import.

The database adapter uses SQLAlchemy and names from
`database/mock-data-generation/db_info.json` and `src/models/fraud_requests.py`.
`profanity_screenings` is an additional ledger because the existing fraud table
does not retain a request ID, submitted text, severity, or idempotency receipt.
For PostgreSQL, the code requires existing destination tables and a manually
reviewed ledger migration; `sql/postgresql_screenings.sql` is a template.
`init-db` creates only local SQLite tables and refuses PostgreSQL. A PostgreSQL
driver such as `psycopg2-binary` is needed only for that integration.

The repository describes different database schemas in different places, so
none is hard-coded for PostgreSQL. Confirm the deployed schema, required request
columns/foreign keys, active status ID, API authentication, and routing policy
before connecting this service to the real request workflow. Live API, AWS,
PostgreSQL, and external matching were not contacted during this local work.
Authentication for a deployed endpoint must come from the existing trusted
request service/API gateway; the standalone CLI binds only to loopback.

To incorporate the routes into a host Flask application, make this folder
importable and register `profanity_routing.web.create_blueprint(service)` with
a configured `RoutingService`. The existing repository application is unchanged;
it has an unrelated database connection at import time, so the standalone
factory is used for local execution.

For Lambda packaging, this folder is the package root and the handler is
`lambda_function.lambda_handler`. It supports direct invocation and API Gateway
v1/v2 JSON bodies, including base64 bodies. No deployment script is run or
required for local verification.

## Files

| Path | Purpose |
| --- | --- |
| `profanity_routing/domain.py` | Submission validation and severity result |
| `profanity_routing/client.py` | Existing API transport and score normalization |
| `profanity_routing/storage.py` | Atomic destination/ledger writes and idempotency |
| `profanity_routing/service.py` | Shared submission workflow |
| `profanity_routing/web.py` | HTTP application factory and reusable routes |
| `profanity_routing/config.py` | Environment configuration |
| `profanity_routing/local_tools.py` | Explicit mock fixtures and temporary servers |
| `profanity_routing/__main__.py` | Local CLI and end-to-end demo |
| `lambda_function.py` | Optional Lambda entry point |
| `tests/` | Contract, HTTP, database, concurrency, and Lambda tests |
| `examples/help_request.json` | Runnable local submission |
| `sql/postgresql_screenings.sql` | Review-only ledger migration template |
