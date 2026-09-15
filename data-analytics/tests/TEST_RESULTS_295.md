# Assigned Volunteers API - Test Results (Issue #295)

**59/59 checks passed** in 4.79s on the `sqlite` backend.

| | |
|---|---|
| Endpoint | `POST /volunteers/assigned` |
| Module under test | `data-analytics/lambda_functions/assigned_volunteers.py` |
| Data source | mock fixtures only - `requests.csv`, `users.csv`, `users_extra_295.csv`, `user_status.csv`, `volunteers_assigned.csv`, `volunteers_assigned_extra_295.csv` |
| Requests in fixture | 25 |
| Terminal statuses | (4,) (Cancelled only) |
| Users in fixture | 2879 |
| Assignment rows in fixture | 67 |
| Python | 3.12.7 |
| AWS / Parameter Store access | none - no boto3 import, no SSM call path |

### Current-assignment rule under test

`volunteers_assigned` has no assignment-status column and no active flag, so "current" is defined by the Lambda: the newest `last_update_date` row per `(req_id, volunteer_id)` - ties broken by the higher `vol_assigned_id` - and nothing at all for a Cancelled request (`req_status_id` 4). The suite re-implements that rule in Python straight from the CSVs and compares it against what the SQL returns.

### Backend coverage

| Backend | Engine | Result |
|---|---|---|
| `sqlite` | SQLite 3.45.3 (in-memory, PostgreSQL shim) | 59/59 passed in 4.79s |
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
| PASS | `test_cancelled_request_does_have_assignment_rows` | The cancelled landmark carries rows, so suppression is real. |
| PASS | `test_every_assignment_points_at_a_known_request` | No volunteers_assigned row references a missing request. |
| PASS | `test_historical_rows_exist` | Some volunteers have more than one row on the same request. |
| PASS | `test_non_terminal_landmarks_are_not_suppressed` | Completed/On Hold/Escalated landmarks hold rows and are not terminal. |
| PASS | `test_null_values_survive_csv_loading` | A literal NULL cell loads as None, not the string 'NULL'. |
| PASS | `test_scenario_requests_all_exist` | Each landmark req_id is present in the requests fixture. |
| PASS | `test_volunteers_missing_from_users_exist` | The export really does assign volunteers with no users row. |

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
| PASS | `test_assignments_do_not_leak_across_requests` | Every returned entry belongs to the requested req_id only. |
| PASS | `test_cancelled_request_has_no_current_assignment` | A Cancelled request returns [] despite holding assignment rows. |
| PASS | `test_completed_request_still_reports_its_volunteers` | Completed is deliberately not terminal - reviewers need the names. |
| PASS | `test_historical_rows_are_excluded` | Superseded rows never reach the response. |
| PASS | `test_matches_the_oracle_for_every_request_in_the_fixture` | The SQL and the Python rule agree on every request in the export. |
| PASS | `test_multiple_assigned_volunteers` | Seven concurrent assignments are all returned, newest first. |
| PASS | `test_new_request_with_no_assignment_rows` | A New request never matched in the export returns its extras only. |
| PASS | `test_no_assigned_volunteer_returns_empty_list` | A valid request with no assignment is 200 with [], not an error. |
| PASS | `test_on_hold_and_escalated_keep_their_volunteers` | Paused or raised requests are not ended, so assignments survive. |
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

### Lead volunteer (requests.lead_volunteer_id)

| Result | Check | What it verifies |
|---|---|---|
| PASS | `test_is_lead_is_false_when_no_lead_is_set` | A NULL lead_volunteer_id never flags anybody. |
| PASS | `test_is_lead_marks_the_matching_volunteer` | is_lead is true exactly for the request's lead_volunteer_id. |
| PASS | `test_lead_does_not_filter_the_array` | Volunteers who are not the lead are still returned. |
| PASS | `test_lead_volunteer_id_is_echoed` | The request's own lead_volunteer_id is returned at the top level. |
| PASS | `test_lead_without_an_assignment_row_is_not_fabricated` | A lead with no volunteers_assigned row is never added to the array. |
| PASS | `test_null_lead_volunteer_id_is_reported_as_null` | A request with no lead reports null rather than omitting the key. |
| PASS | `test_unmatched_lead_flags_nobody` | A lead who holds no assignment row leaves every is_lead false. |

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
  "req_id": "REQ-000007"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-000007",
  "lead_volunteer_id": "SID-00-000-060-168",
  "assignedVolunteers": [
    {
      "user_id": "SID-00-000-000-307",
      "full_name": "Mohammed Ahmed",
      "primary_email_address": "shariq.mohammed01@gmail.com",
      "primary_phone_number": "+19132800576",
      "user_status": "ACTIVE",
      "volunteer_type": "Backup",
      "assigned_at": "2026-03-18 21:00:00",
      "is_lead": false
    }
  ]
}
```

### Multiple assigned volunteers

Request:

```json
{
  "req_id": "REQ-000013"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-000013",
  "lead_volunteer_id": "SID-00-000-000-308",
  "assignedVolunteers": [
    {
      "user_id": "SID-00-000-000-061",
      "full_name": "Ishita Rastogi",
      "primary_email_address": "rastogiishita30@gmail.com",
      "primary_phone_number": "2177660116",
      "user_status": "ACTIVE",
      "volunteer_type": "Secondary",
      "assigned_at": "2026-08-17 06:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-340",
      "full_name": "Mohammed Ahmed",
      "primary_email_address": "shariq.mohammed01@gmail.com",
      "primary_phone_number": "+19132800576",
      "user_status": "ACTIVE",
      "volunteer_type": "Primary",
      "assigned_at": "2026-06-20 13:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-100",
      "full_name": "Rajas Ronghe",
      "primary_email_address": "rajasr9@outlook.com",
      "primary_phone_number": "2673663719",
      "user_status": "ACTIVE",
      "volunteer_type": "Primary",
      "assigned_at": "2026-06-14 18:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-078",
      "full_name": "Vighnesh Sridhar",
      "primary_email_address": "vighnesh.s.saayam@gmail.com",
      "primary_phone_number": "4087265003",
      "user_status": "ACTIVE",
      "volunteer_type": "Backup",
      "assigned_at": "2026-06-08 19:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-311",
      "full_name": "Mohammed Ahmed",
      "primary_email_address": "shariq.mohammed01@gmail.com",
      "primary_phone_number": "+19132800576",
      "user_status": "ACTIVE",
      "volunteer_type": "Backup",
      "assigned_at": "2026-03-17 10:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-096",
      "full_name": "BhanuTeja Thattepally",
      "primary_email_address": "bhanutejat221003@gmail.com",
      "primary_phone_number": "4145957832",
      "user_status": "ACTIVE",
      "volunteer_type": "Primary",
      "assigned_at": "2026-03-05 16:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-308",
      "full_name": "Mohammed Ahmed",
      "primary_email_address": "shariq.mohammed01@gmail.com",
      "primary_phone_number": "+19132800576",
      "user_status": "ACTIVE",
      "volunteer_type": "Secondary",
      "assigned_at": "2025-12-02 03:00:00",
      "is_lead": true
    }
  ]
}
```

### Reassigned request - only the current volunteer

Request:

```json
{
  "req_id": "REQ-000016"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-000016",
  "lead_volunteer_id": null,
  "assignedVolunteers": [
    {
      "user_id": "SID-00-000-295-001",
      "full_name": "Priya Nair",
      "primary_email_address": null,
      "primary_phone_number": null,
      "user_status": "ACTIVE",
      "volunteer_type": "Primary",
      "assigned_at": "2026-04-01 09:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-087",
      "full_name": "Prashant Kumar",
      "primary_email_address": "prashantkumaromar@gmail.com",
      "primary_phone_number": "7164864876",
      "user_status": "ACTIVE",
      "volunteer_type": "Primary",
      "assigned_at": "2026-01-13 17:00:00",
      "is_lead": false
    }
  ]
}
```

### NULL contacts, inactive volunteer, NULL status

Request:

```json
{
  "req_id": "REQ-000022"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-000022",
  "lead_volunteer_id": null,
  "assignedVolunteers": [
    {
      "user_id": "SID-00-000-295-003",
      "full_name": "Ana Ruiz",
      "primary_email_address": "ana.ruiz@example.org",
      "primary_phone_number": "5715550163",
      "user_status": null,
      "volunteer_type": "Backup",
      "assigned_at": "2026-03-01 11:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-295-002",
      "full_name": "Marcus Bell",
      "primary_email_address": "marcus.bell@example.org",
      "primary_phone_number": "5715550142",
      "user_status": "INACTIVE",
      "volunteer_type": "Secondary",
      "assigned_at": "2026-03-01 10:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-295-001",
      "full_name": "Priya Nair",
      "primary_email_address": null,
      "primary_phone_number": null,
      "user_status": "ACTIVE",
      "volunteer_type": "Primary",
      "assigned_at": "2026-03-01 09:00:00",
      "is_lead": false
    }
  ]
}
```

### Volunteers with no users row

Request:

```json
{
  "req_id": "REQ-000020"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-000020",
  "lead_volunteer_id": "SID-00-000-408-687",
  "assignedVolunteers": [
    {
      "user_id": "SID-00-000-682-105",
      "full_name": null,
      "primary_email_address": null,
      "primary_phone_number": null,
      "user_status": null,
      "volunteer_type": "Secondary",
      "assigned_at": "2026-07-23 17:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-255-895",
      "full_name": null,
      "primary_email_address": null,
      "primary_phone_number": null,
      "user_status": null,
      "volunteer_type": "Backup",
      "assigned_at": "2026-03-13 17:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-826-416",
      "full_name": null,
      "primary_email_address": null,
      "primary_phone_number": null,
      "user_status": null,
      "volunteer_type": "Secondary",
      "assigned_at": "2025-12-29 08:00:00",
      "is_lead": false
    }
  ]
}
```

### Lead volunteer flagged

Request:

```json
{
  "req_id": "REQ-000013"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-000013",
  "lead_volunteer_id": "SID-00-000-000-308",
  "assignedVolunteers": [
    {
      "user_id": "SID-00-000-000-061",
      "full_name": "Ishita Rastogi",
      "primary_email_address": "rastogiishita30@gmail.com",
      "primary_phone_number": "2177660116",
      "user_status": "ACTIVE",
      "volunteer_type": "Secondary",
      "assigned_at": "2026-08-17 06:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-340",
      "full_name": "Mohammed Ahmed",
      "primary_email_address": "shariq.mohammed01@gmail.com",
      "primary_phone_number": "+19132800576",
      "user_status": "ACTIVE",
      "volunteer_type": "Primary",
      "assigned_at": "2026-06-20 13:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-100",
      "full_name": "Rajas Ronghe",
      "primary_email_address": "rajasr9@outlook.com",
      "primary_phone_number": "2673663719",
      "user_status": "ACTIVE",
      "volunteer_type": "Primary",
      "assigned_at": "2026-06-14 18:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-078",
      "full_name": "Vighnesh Sridhar",
      "primary_email_address": "vighnesh.s.saayam@gmail.com",
      "primary_phone_number": "4087265003",
      "user_status": "ACTIVE",
      "volunteer_type": "Backup",
      "assigned_at": "2026-06-08 19:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-311",
      "full_name": "Mohammed Ahmed",
      "primary_email_address": "shariq.mohammed01@gmail.com",
      "primary_phone_number": "+19132800576",
      "user_status": "ACTIVE",
      "volunteer_type": "Backup",
      "assigned_at": "2026-03-17 10:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-096",
      "full_name": "BhanuTeja Thattepally",
      "primary_email_address": "bhanutejat221003@gmail.com",
      "primary_phone_number": "4145957832",
      "user_status": "ACTIVE",
      "volunteer_type": "Primary",
      "assigned_at": "2026-03-05 16:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-308",
      "full_name": "Mohammed Ahmed",
      "primary_email_address": "shariq.mohammed01@gmail.com",
      "primary_phone_number": "+19132800576",
      "user_status": "ACTIVE",
      "volunteer_type": "Secondary",
      "assigned_at": "2025-12-02 03:00:00",
      "is_lead": true
    }
  ]
}
```

### Completed request - volunteers still reported

Request:

```json
{
  "req_id": "REQ-000002"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-000002",
  "lead_volunteer_id": "SID-00-000-797-944",
  "assignedVolunteers": [
    {
      "user_id": "SID-00-000-000-060",
      "full_name": "Rbac Test",
      "primary_email_address": "rbac@example1.com",
      "primary_phone_number": "4081234456",
      "user_status": "ACTIVE",
      "volunteer_type": "Primary",
      "assigned_at": "2026-04-12 15:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-760-566",
      "full_name": null,
      "primary_email_address": null,
      "primary_phone_number": null,
      "user_status": null,
      "volunteer_type": "Backup",
      "assigned_at": "2026-03-30 20:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-090",
      "full_name": "Sowmya Manchikanti",
      "primary_email_address": "manchikanti.sowmya@gmail.com",
      "primary_phone_number": "9174198796",
      "user_status": "ACTIVE",
      "volunteer_type": "Primary",
      "assigned_at": "2026-02-08 15:00:00",
      "is_lead": false
    },
    {
      "user_id": "SID-00-000-000-312",
      "full_name": "Mohammed Ahmed",
      "primary_email_address": "shariq.mohammed01@gmail.com",
      "primary_phone_number": "+19132800576",
      "user_status": "ACTIVE",
      "volunteer_type": "Primary",
      "assigned_at": "2025-11-20 12:00:00",
      "is_lead": false
    }
  ]
}
```

### No current assignment

Request:

```json
{
  "req_id": "REQ-000015"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-000015",
  "lead_volunteer_id": null,
  "assignedVolunteers": []
}
```

### Cancelled request

Request:

```json
{
  "req_id": "REQ-000005"
}
```

Response (HTTP 200):

```json
{
  "req_id": "REQ-000005",
  "lead_volunteer_id": "SID-00-000-576-102",
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
  "req_id": "REQ-999999"
}
```

Response (HTTP 404):

```json
{
  "error": "no request found for req_id 'REQ-999999'"
}
```

### Database failure - connection refused

Request:

```json
{
  "req_id": "REQ-000007"
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
- Only four scenarios the real export cannot express live in the `*_extra_295` fixtures; they are unioned in rather than appended to the exports, so regenerating `requests.csv`, `users.csv` or `volunteers_assigned.csv` cannot silently delete them.
- `Completed` requests deliberately still report their volunteers - only `Cancelled` (4) suppresses the array. `requests.lead_volunteer_id` is echoed and flagged via `is_lead` but never reconciled: in this fixture it matches an assignment row in only 1 of 20 cases.
- Suggested indexes for the production tables: `volunteers_assigned(req_id)` and `volunteers_assigned(req_id, volunteer_id, last_update_date)` to serve the lookup and the anti-join, plus the existing `request(req_id)` and `users(user_id)` primary keys.
