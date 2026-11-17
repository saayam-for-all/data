# Synthetic request archive fixtures

This directory contains generated, fabricated CSV data for developing and testing the request archive pipeline. No rows are read from PostgreSQL, the dev database, or an export. Table and column definitions follow the schema-only [`saayam_schema.sql`](../saayam_schema.sql), attached to issue #573. The generator checks its CSV column lists against that DDL before writing. It also copies the DDL into this directory so the generated fixture bundle is self-contained. The `users.csv` file contains only `user_id`.

## Generate the fixtures

From the repository root:

```bash
python data-analytics/sql/generate_request_archive_mock.py
```

The defaults create 500 requests using seed `587`. Re-running with the same seed and count writes byte-identical files. To choose another repeatable seed or output location:

```bash
python data-analytics/sql/generate_request_archive_mock.py --count 500 --seed 587 --output-dir data-analytics/sql/request_archive_mock
```

To verify byte-for-byte repeatability before writing the requested output:

```bash
python data-analytics/sql/generate_request_archive_mock.py --check-determinism
```

All CSVs use UTF-8. Every non-null request reference points to a generated parent row. Lookup IDs and labels are the fixed values documented in issue #573; the category names and parent-child tree are invented examples.

## Load into local PostgreSQL

PostGIS is required because the schema declares two `geometry(Point,4326)` columns, even though the mock requests leave both geometry fields null. Install/enable PostGIS for your PostgreSQL version first. From the repository root, create the database, enable PostGIS, create the schema, and apply the DDL:

```bash
createdb saayam_mock && psql -d saayam_mock -v ON_ERROR_STOP=1 -c "CREATE EXTENSION postgis; CREATE SCHEMA virginia_dev_saayam_rdbms;" && psql -d saayam_mock -v ON_ERROR_STOP=1 -f data-analytics/sql/saayam_schema.sql
```

Then load all main fixture tables in dependency order:

```bash
psql -d saayam_mock -v ON_ERROR_STOP=1 -f data-analytics/sql/request_archive_mock/load_mock_data.sql
```

The loader supplies explicit column lists, which is important for `users.csv` (key column only) and uses `\N` as the unquoted SQL NULL marker. Empty strings are quoted in the CSV and stay distinct from NULL. The generated sequence IDs are inserted explicitly; the fixtures are intended for a disposable local database.

Do **not** load `broken_reference_fixture.csv` into the constrained schema. It deliberately references a creator absent from `users.csv` and would correctly fail the foreign-key constraint. Use it separately in a pipeline test that needs to confirm an inner join does not silently discard a broken reference.

## Special cases in this data

| # | Case | Where to inspect |
|---|---|---|
| 1 | Skewed nulls in every nullable request reference. 493 of 500 lead IDs are null; 18 of 500 beneficiary IDs are null. | `requests.csv`; the nullable references are `lead_volunteer_id` and `beneficiary_id`. All required references are populated. |
| 2 | Several rows have exactly the same microsecond timestamp. | Requests `REQ-000-000-000-0002` through `REQ-000-000-000-0006` have `last_updated_at = 2026-10-01 12:00:00.123456`. |
| 3 | An update timestamp earlier than submission. | `REQ-000-000-000-0007`. |
| 4 | Newlines, commas, and double quotes in free text. | `REQ-000-000-000-0008`. Read it with a CSV parser; the embedded line break is inside a quoted field. |
| 5 | Non-ASCII Spanish text and accents. | `REQ-000-000-000-0009` and the Spanish names in later fixtures. |
| 6 | Fictional phone numbers in multiple formats, email addresses, street addresses, and non-English names; one phone is written in words. | Request rows 10–14. `pii_fixture_rows.csv` lists each request and the planted detail types. The contact details use fictional/example values and must not be contacted. |
| 7 | Empty strings distinguished from NULL in every nullable text column on `requests`. | Rows `...0017`, `...0018`, and `...0019` carry empty strings in `req_doc_link`, `audio_req_desc`, and `deletion_reason`, respectively; row `...0020` has all three empty. Other rows also carry nulls. |
| 8 | Exact maximum-length values. | `REQ-000-000-000-0015` has a 125-character `req_subj`; `REQ-000-000-000-0016` has a 255-character `req_desc`; `REQ-000-000-000-0025` has a 255-character `audio_req_desc`. |
| 9 | Every lookup value appears in at least one request. | `requests.csv` uses all IDs in `request_for.csv`, `request_isleadvol.csv`, `request_types.csv`, `request_priorities.csv`, and `request_statuses.csv`, including CRITICAL and the RESOLVED, CANCELLED, and VOLUNTEER_NOT_FOUND statuses. |
| 10 | Lead flag says YES while the lead user reference is NULL. | `REQ-000-000-000-0010` has `req_islead_id = 1` and `lead_volunteer_id = NULL`. |
| 11 | Broken reference kept separate from loadable main data. | `broken_reference_fixture.csv` contains one request whose creator ID is absent from `users.csv`; do not load it with the main CSVs. |

The 500-row null distribution rounds the observed shape (218/221 missing leads and 8/221 missing beneficiaries) to the nearest whole rows. It is intentionally not uniform.
