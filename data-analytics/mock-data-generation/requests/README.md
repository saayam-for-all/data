# Request archival mock data

Issue [#587](https://github.com/saayam-for-all/data/issues/587). Generates synthetic data for local development of the request archival pipeline. It reads the [DDL supplied with issue #573](https://github.com/user-attachments/files/33914221/saayam_schema.sql), included as `saayam_schema.sql`. It never connects to a database or reads the historical CSV exports.

## Generate and start PostgreSQL

Requirements: Python 3.10 or later, Docker Desktop with Linux containers, and Docker Compose. No Python packages are required. From the repository root, run:

```sh
python data-analytics/mock-data-generation/requests/generate_requests_mock_data.py --seed 42
docker compose -f data-analytics/mock-data-generation/requests/compose.yaml up -d --wait
```

These two commands generate the fixtures and start PostgreSQL 16 with PostGIS, create `virginia_dev_saayam_rdbms` from the supplied DDL, and load the nine CSV tables in dependency order. All constraints remain enabled. PostGIS is required by the two `geometry(Point,4326)` columns. The default local connection is `postgresql://mock_user:mock_local_only@localhost:55487/saayam_mock`. This password is a fixed local mock credential. The port is bound to localhost; set `MOCK_POSTGRES_PORT` before starting Compose to use another port.

The initialization script runs only for a new database volume. Regenerating CSVs does not overwrite an already loaded database. To rebuild this dedicated mock database, run `docker compose -f data-analytics/mock-data-generation/requests/compose.yaml down --volumes`, then the second command above. This removes only that Compose project's local mock database volume. `down` without `--volumes` stops the container and preserves its data.

The supplied DDL names triggers but does not include their bodies. The local setup loads that DDL as provided and does not invent the live trigger behavior. Timestamp values are timezone-free, in UTC by convention. The loader synchronizes the serial lookup sequences after loading their explicit IDs.

## Files and CSV format

Default output: `data-analytics/sql/`.

| Table CSV | Rows with default settings |
|---|---:|
| requests.csv | 500 |
| help_categories.csv | 14 |
| help_categories_map.csv | 14 |
| request_for.csv | 2 |
| request_isleadvol.csv | 2 |
| request_types.csv | 2 |
| request_priorities.csv | 4 |
| request_statuses.csv | 9 |
| users.csv | 102 |

`users.csv` contains **only `user_id`**, as requested. Its other schema column receives its default during loading. Category names and the category tree are invented. The fixed lookup IDs and values follow the comments in the supplied schema:

- For: `0 SELF`, `1 OTHER`.
- Lead flag: `0 NO`, `1 YES`.
- Type: `0 IN_PERSON`, `1 REMOTE`.
- Priority: `0 LOW`, `1 MEDIUM`, `2 HIGH`, `3 CRITICAL`.
- Status: `0 CREATED`, `1 MATCHING_VOLUNTEER`, `2 IN_PROGRESS`, `3 RESOLVED`, `4 CANCELLED`, `5 DELETED`, `6 RATED_BY_REQUESTER`, `7 RATED_BY_VOLUNTEER`, `8 VOLUNTEER_NOT_FOUND`.

Files use UTF-8, LF newlines and standard CSV quoting. **`\N` means SQL NULL; an empty field means an empty string.** Every load must specify `WITH (FORMAT csv, HEADER true, NULL '\N', ENCODING 'UTF8')`, as the included loader does. The default PostgreSQL CSV null convention would conflate empty fields and nulls. See the [PostgreSQL COPY documentation](https://www.postgresql.org/docs/current/sql-copy.html).

Additional generated files are not application tables:

- `special_cases.csv` maps numbered issue cases to exact request IDs, columns and descriptions. IDs refer to CSV records, not physical lines, since a description contains a newline.
- `pii_manifest.csv` identifies every request with planted synthetic personal details, its affected fields and PII types. Names, example-domain email addresses, fictional street addresses and reserved 555-01xx phone numbers are invented test inputs. They are retained intentionally to test downstream redaction. No live personal data is used.
- `fixtures/requests_broken_reference.csv` is deliberately invalid and is excluded from the main loader.

The historical CSV exports in `data-analytics/sql` are replaced by this coherent request dataset. The separate organization/volunteer generator and its data under `data-analytics/mock-data-generation/` are unchanged.

## Numbered edge cases

For default settings, request IDs are `REQ-MOCK-0001` through `REQ-MOCK-0500`, except record 12, whose ID is `REQ-MAX-` followed by padding to 255 characters. `special_cases.csv` contains the exact long ID.

| Case | Identifiable records and behavior |
|---|---|
| 1. Skewed nullable references | Record 1 has both references null. Across 500 requests, 493 lead references are null (98.6%) and 18 beneficiary references are null (3.6%), approximating 218/221 and 8/221. |
| 2. Shared microsecond and window boundaries | Records 1, 2, 3 and 6 share `2026-10-24 12:00:00.123456`. Record 4 is one microsecond before it; record 5 is one microsecond after it. Adjacent half-open windows can test inclusion and exclusion without relying on whole seconds. |
| 3. Update before submission | Record 6 has its update at the shared timestamp and its submission exactly one day later. |
| 4. CSV punctuation and newline | Record 7's `req_desc` includes a comma, double quotes and an embedded newline. |
| 5. Non-ASCII free text | Record 8 contains Spanish accents and an ñ. Additional marked records include Chinese and Arabic names. |
| 6. Synthetic personal details | Records 17–22 contain names, phones, emails and street addresses, all labeled in `pii_manifest.csv`. Phones use parentheses, dots, international/hyphen and space formatting; records 21–22 spell the digits as words, including “four eight zero”. |
| 7. Empty strings versus nulls | Record 1 has nulls and record 9 has empty strings in **all five nullable request text columns**, including both nullable references. A deliberately empty, non-null `users.user_id` supplies a valid FK target for those empty references. It is a test-only key and differs from SQL NULL. |
| 8. Maximum declared request lengths | Record 12 fills every `varchar` in `requests`: request/user IDs 255, category ID 50, subject 125, description 255 and audio description 255. The long user and category keys exist in their target tables. Unbounded `text` columns have no maximum; lookup names retain their required fixed values. |
| 9. Every lookup value used | All category, for, lead-flag, type, priority and status values appear in requests. This includes CRITICAL, RESOLVED, CANCELLED and VOLUNTEER_NOT_FOUND. The case-9 manifest rows identify a covering set of requests. |
| 10. Contradictory lead flag | Record 11 has `req_islead_id = 1` and `lead_volunteer_id = NULL`. Other such contradictions also occur because the lead flag is more common than a recorded lead. |
| 11. Missing referenced row | Only `fixtures/requests_broken_reference.csv` contains `REQ-BROKEN-REFERENCE`, whose creator is absent (`SID-MISSING-FIXTURE`). All its other non-null references are valid. It must fail insertion with foreign-key SQLSTATE `23503`; it must never be included in the main load. |

Record 12 also deliberately exceeds the usual trigger-generated identifier format while staying within the declared SQL types. The supplied schema has no ID-format check constraint. The empty key and the maximum-length identifiers ensure the test data exercises what the schema actually permits.

## Options and reproducibility

The generator validates keys, references, types and string lengths before writing. Running it twice with the same seed and row count produces byte-identical CSVs. Changing the seed changes the non-fixed request data. All dates are anchored constants, never the current time. The command prints table sizes and nullable-reference counts for inspection.

To generate elsewhere or change the size:

```sh
python data-analytics/mock-data-generation/requests/generate_requests_mock_data.py --seed 17 --rows 1000 --output-dir /path/to/fixtures
```

At least 50 requests are required. `--output-dir` controls generation only; Compose still mounts `data-analytics/sql`, so use its default output for the two-command setup, or explicitly override the `/fixtures` bind mount. The generator overwrites only its own named output files; it never silently deletes unrelated files.
