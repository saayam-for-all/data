# Assigned Volunteers API - Test Results (Issue #295)

**50/50 checks passed** in 3.11s on the `sqlite` backend.

| | |
|---|---|
| Endpoint | `POST /volunteers/assigned` |
| Module under test | `data-analytics/lambda_functions/assigned_volunteers.py` |
| Data source | mock fixtures only - `Request_Table.csv`, `request_extra_295.csv`, `users.csv`, `users_extra_295.csv`, `user_status.csv`, `volunteers_assigned.csv` |
| Requests in fixture | 293 |
| Users in fixture | 2879 |
| Assignment rows in fixture | 16 |
| Python | 3.12.7 |
| AWS / Parameter Store access | none - no boto3 import, no SSM call path |

### Current-assignment rule under test

`volunteers_assigned` has no assignment-status column and no active flag, so "current" is defined by the Lambda: the newest `last_update_date` row per `(request_id, volunteer_id)` - ties broken by the higher `volunteers_assigned_id` - and nothing at all for a request in a terminal status (`req_status_id` 4 CANCELLED, 5 DELETED). The suite re-implements that rule in Python straight from the CSVs and compares it against what the SQL returns.

### Backend coverage

| Backend | Engine | Result |
|---|---|---|
| `sqlite` | SQLite 3.45.3 (in-memory, PostgreSQL shim) | 50/50 passed in 3.11s |
| `postgres` | PostgreSQL (local) | not run |

Reproduce with:

```bash
# zero-setup run (SQLite shim)
python data-analytics/tests/test_assigned_volunteers.py --emit-results

# against a local PostgreSQL
docker run -d --name saayam-pg -e POSTGRES_PASSWORD=postgres \
    -e POSTGRES_DB=saayam_local -p 55432:5432 postgres:16-alpine
MOCK_DB_BACKEND=postgres DB_HOST=localhost DB_PORT=55432 \
DB_NAME=saayam_local DB_USER=postgres DB_PASSWORD=postgres \
    python data-analytics/tests/test_assigned_volunteers.py
```

---

## Checks

### No shared-database access

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_boto3_is_not_imported` | Importing the module never pulls in an AWS client. |
| PASS | `test_credentials_are_not_hardcoded` | No literal host, user or password appears in the source. |
| PASS | `test_missing_db_host_raises_instead_of_falling_back` | An unconfigured environment is an error, not a credential lookup. |
| PASS | `test_source_has_no_parameter_store_references` | No boto3/SSM/Parameter Store call sites exist in the module. |

### Mock fixtures

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_every_assignment_points_at_a_known_request` | No volunteers_assigned row references a missing request. |
| PASS | `test_historical_rows_exist` | Some volunteers have more than one row on the same request. |
| PASS | `test_null_values_survive_csv_loading` | A literal NULL cell loads as None, not the string 'NULL'. |
| PASS | `test_scenario_requests_all_exist` | Each landmark req_id is present in the request fixture. |
| PASS | `test_terminal_status_requests_do_have_assignment_rows` | Cancelled/deleted requests carry rows, so suppression is real. |

### Steps 1-2 - request validation

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_blank_req_id_returns_400` | A whitespace-only req_id is rejected the same way. |
| PASS | `test_missing_req_id_returns_400` | An empty payload returns 400 {'error': 'req_id is required'}. |
| PASS | `test_no_query_runs_when_validation_fails` | A 400 is returned without ever opening a connection. |
| PASS | `test_non_string_req_id_returns_400` | A numeric or null req_id is rejected rather than coerced. |
| PASS | `test_req_id_is_trimmed` | Surrounding whitespace does not turn a valid id into a 404. |
| PASS | `test_unknown_req_id_returns_404` | A well-formed but nonexistent req_id returns 404, not 200. |
| PASS | `test_valid_req_id_returns_200` | A known req_id returns HTTP 200 with the response envelope. |

### Step 3 - current assignment retrieval

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_active_request_with_no_assignment_rows` | An in-progress request that was never matched also returns []. |
| PASS | `test_assignments_do_not_leak_across_requests` | Every returned entry belongs to the requested req_id only. |
| PASS | `test_cancelled_request_has_no_current_assignment` | A CANCELLED request returns [] despite holding assignment rows. |
| PASS | `test_deleted_request_has_no_current_assignment` | A DELETED request returns [] despite holding assignment rows. |
| PASS | `test_historical_rows_are_excluded` | Superseded rows never reach the response for any request. |
| PASS | `test_matches_the_oracle_for_every_request_in_the_fixture` | The SQL and the Python rule agree on every assigned request. |
| PASS | `test_mixed_current_and_historical_across_volunteers` | One volunteer's row is superseded while another's stays current. |
| PASS | `test_multiple_assigned_volunteers` | Two concurrent assignments are both returned, newest first. |
| PASS | `test_no_assigned_volunteer_returns_empty_list` | A valid request with no assignment is 200 with [], not an error. |
| PASS | `test_one_entry_per_volunteer` | A volunteer with several rows appears at most once. |
| PASS | `test_reassigned_request_returns_only_the_newest_row` | A replaced assignment does not appear alongside its replacement. |
| PASS | `test_single_assigned_volunteer` | A request with one current volunteer returns exactly that one. |
| PASS | `test_tied_timestamps_break_deterministically` | Two rows with the same timestamp resolve to the higher id. |

### Step 4 - volunteer details

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_assignment_metadata_is_returned` | volunteer_type and assigned_at come from volunteers_assigned. |
| PASS | `test_complete_profile_is_returned` | A fully populated volunteer returns every response field. |
| PASS | `test_every_entry_has_the_full_key_set` | The response shape is stable regardless of NULL columns. |
| PASS | `test_inactive_volunteer_is_still_returned` | A changed user status does not remove a current assignee. |
| PASS | `test_missing_user_row_does_not_drop_the_volunteer` | An assignment with no users row still reports the volunteer id. |
| PASS | `test_null_contact_details_do_not_drop_the_volunteer` | NULL email/phone surface as null instead of failing or filtering. |
| PASS | `test_null_user_status_id_yields_null_status` | A NULL user_status_id reports null rather than failing the join. |
| PASS | `test_user_status_is_resolved_from_the_lookup` | user_status comes from the user_status join, not the raw id. |

### General / failure scenarios

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_database_connection_failure_returns_500` | A refused connection returns 500 without leaking details. |
| PASS | `test_empty_result_set_is_not_an_error` | An empty assignment set is a 200, distinguishable from a failure. |
| PASS | `test_no_n_plus_one_queries` | Many assigned volunteers still cost the same two statements. |
| PASS | `test_query_execution_failure_returns_500` | A failing statement returns 500 rather than a partial payload. |
| PASS | `test_req_id_is_bound_never_interpolated` | The request id is passed as a parameter, not spliced into SQL. |
| PASS | `test_sql_injection_attempt_returns_404` | An injected predicate matches no request rather than every one. |

### Lambda handler contract

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_accepts_a_dict_body` | A dict body is accepted as-is. |
| PASS | `test_accepts_a_json_string_body` | An API Gateway proxy event with a JSON string body is parsed. |
| PASS | `test_accepts_a_top_level_payload` | A direct invocation payload works without a body wrapper. |
| PASS | `test_body_is_a_json_string` | The proxy body is serialized text, not a dict. |
| PASS | `test_cors_headers_are_present` | Every response carries the shared CORS headers. |
| PASS | `test_malformed_json_body_is_a_400` | An unparseable body degrades to the missing-req_id error. |
| PASS | `test_none_event_is_a_400` | A null event is rejected rather than raising. |

---

## Sample API responses

Generated by invoking `lambda_handler` against the mock fixtures.

### One assigned volunteer

Request:

```json
{
  "req_id": "REQ-00-000-000-0018"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-00-000-000-0018",
  "assignedVolunteers": [
    {
      "user_id": "SID-00-000-000-078",
      "full_name": "Vighnesh Sridhar",
      "primary_email_address": "vighnesh.s.saayam@gmail.com",
      "primary_phone_number": "4087265003",
      "user_status": "ACTIVE",
      "volunteer_type": "LEAD",
      "assigned_at": "2026-01-10 09:00:00"
    }
  ]
}
```

### Multiple assigned volunteers

Request:

```json
{
  "req_id": "REQ-00-000-000-0019"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-00-000-000-0019",
  "assignedVolunteers": [
    {
      "user_id": "SID-00-000-000-080",
      "full_name": "Likhith H G",
      "primary_email_address": "likhithhalkurke98@gmail.com",
      "primary_phone_number": "7202515128",
      "user_status": "ACTIVE",
      "volunteer_type": "SUPPORT",
      "assigned_at": "2026-01-11 10:30:00"
    },
    {
      "user_id": "SID-00-000-000-079",
      "full_name": "Shashikiran Devadiga",
      "primary_email_address": "shashikirandevadiga1995@gmail.com",
      "primary_phone_number": "4252696548",
      "user_status": "ACTIVE",
      "volunteer_type": "LEAD",
      "assigned_at": "2026-01-11 09:00:00"
    }
  ]
}
```

### Reassigned request - only the current volunteer

Request:

```json
{
  "req_id": "REQ-00-000-000-0020"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-00-000-000-0020",
  "assignedVolunteers": [
    {
      "user_id": "SID-00-000-000-081",
      "full_name": "shobha kamath",
      "primary_email_address": "shobha.s.kamath@gmail.com",
      "primary_phone_number": "7150400000",
      "user_status": "ACTIVE",
      "volunteer_type": "LEAD",
      "assigned_at": "2026-01-12 14:00:00"
    }
  ]
}
```

### Volunteer with NULL contact details

Request:

```json
{
  "req_id": "REQ-00-000-000-0021"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-00-000-000-0021",
  "assignedVolunteers": [
    {
      "user_id": "SID-00-000-295-001",
      "full_name": "Priya Nair",
      "primary_email_address": null,
      "primary_phone_number": null,
      "user_status": "ACTIVE",
      "volunteer_type": "LEAD",
      "assigned_at": "2026-01-13 11:00:00"
    }
  ]
}
```

### Inactive volunteer, still assigned

Request:

```json
{
  "req_id": "REQ-00-000-000-0022"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-00-000-000-0022",
  "assignedVolunteers": [
    {
      "user_id": "SID-00-000-295-002",
      "full_name": "Marcus Bell",
      "primary_email_address": "marcus.bell@example.org",
      "primary_phone_number": "5715550142",
      "user_status": "INACTIVE",
      "volunteer_type": "LEAD",
      "assigned_at": "2026-01-14 11:00:00"
    }
  ]
}
```

### No current assignment

Request:

```json
{
  "req_id": "REQ-00-000-000-0030"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-00-000-000-0030",
  "assignedVolunteers": []
}
```

### Cancelled request

Request:

```json
{
  "req_id": "REQ-00-000-295-004"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-00-000-295-004",
  "assignedVolunteers": []
}
```

### Validation error - missing req_id

Request:

```json
{}
```

Response (HTTP 400):

```json
{
  "error": "req_id is required"
}
```

### Unknown req_id

Request:

```json
{
  "req_id": "REQ-00-000-999-999"
}
```

Response (HTTP 404):

```json
{
  "error": "no request found for req_id 'REQ-00-000-999-999'"
}
```

### Database failure - connection refused

Request:

```json
{
  "req_id": "REQ-00-000-000-0018"
}
```

Response (HTTP 500):

```json
{
  "error": "internal server error"
}
```

---

## Notes

- A valid request with no current assignment is **not** an error: it returns HTTP 200 with an empty `assignedVolunteers` array. Only a missing `req_id` (400), an unknown `req_id` (404) and a database failure (500) are errors.
- Volunteer profile and status are joined with `LEFT JOIN`, so a volunteer with NULL contact details, a NULL `user_status_id`, or no `users` row at all is still reported rather than silently dropped.
- A volunteer is never removed from the response because their user status changed. `SID-00-000-295-002` is INACTIVE and still returned, with the status reported as informational data.
- `user_status.csv` holds the single real lookup row (`1 ACTIVE`) plus two mock-only rows (`2 INACTIVE`, `3 SUSPENDED`) that exist solely so non-ACTIVE status handling can be exercised.
- The edge-case rows for this issue live in `request_extra_295.csv` and `users_extra_295.csv` rather than being appended to the bulk exports, so a regeneration of `Request_Table.csv` or `users.csv` cannot silently delete the scenarios this suite depends on.
- Suggested indexes for the production tables: `volunteers_assigned(request_id)` and `volunteers_assigned(request_id, volunteer_id, last_update_date)` to serve the lookup and the anti-join, plus the existing `request(req_id)` and `users(user_id)` primary keys.
