# Mock data for the requests table

This folder has a script that makes fake data for the `requests` table and every table it references. It lets us build and test the archive pipeline without touching the dev database. Nothing in the output is copied from real data.

The old CSV exports in `data-analytics/sql` were taken months apart, so their references no longer line up. This replaces them.

## Run the generator

    python generate_requests_mock_data.py --seed 42 --out output

You only need Python 3, there is nothing to install. The same seed always gives the same files, byte for byte. To check that yourself, run it twice with different output folders and compare the files.

## Load it into a local Postgres

You need `saayam_schema.sql` from issue #573.

1. Create the database and the schema:

        createdb -U postgres saayam_mock
        psql -U postgres -d saayam_mock -c "CREATE EXTENSION postgis;" -c "CREATE SCHEMA virginia_dev_saayam_rdbms;"
        psql -U postgres -d saayam_mock -f saayam_schema.sql

2. Load the data. Run this from this folder:

        psql -U postgres -d saayam_mock -f load_local.sql

It loads the lookup tables first, then the category tree, users and requests, and ends with a small summary query. Expected result: 500 requests, 494 with no lead volunteer, 29 with no beneficiary, 6 flagged as having a lead volunteer but without one recorded.

**If PostGIS is not installed.** `requests` has two `geometry` columns, which need PostGIS. Without it, skip the `CREATE EXTENSION` part and load a copy of the schema where `public.geometry(Point,4326)` is replaced with `text`. The generator writes locations as plain text, so both versions load fine. On Mac or Linux:

    sed 's/public\.geometry(Point,4326)/text/' saayam_schema.sql > saayam_schema_nogis.sql

On Windows, write the copy without a byte order mark, because Postgres rejects the mark:

    $text = (Get-Content -Raw -Encoding UTF8 saayam_schema.sql) -replace 'public\.geometry\(Point,4326\)', 'text'
    [System.IO.File]::WriteAllText("saayam_schema_nogis.sql", $text, (New-Object System.Text.UTF8Encoding($false)))

Do not add the live triggers to the local database. `trg_request_updated_at` rewrites `last_updated_at`, which would wipe out cases 2 and 3 below.

## What gets generated

| File | Contents |
|---|---|
| requests.csv | 500 requests |
| users.csv | 60 user ids, key column only |
| help_categories.csv, help_categories_map.csv | a made-up category tree, 50 rows |
| request_for.csv, request_isleadvol.csv, request_types.csv, request_priorities.csv, request_statuses.csv | the lookup tables with their real values |
| pii_rows.csv | which requests have personal details planted in their text |
| fixture_broken_reference.csv | one request that points at a user who does not exist |

`fixture_broken_reference.csv` is not loaded by `load_local.sql`. The foreign keys reject it, which is the reason it lives in its own file. It is there for testing the pipeline against a broken reference.

NULLs are written as nothing between two commas. Text is always quoted, so an empty string comes out as `""`. Postgres tells the two apart when it loads the file.

## Where each case is

The request number is the end of the `req_id`. Request 14 is `REQ-000-000-000-0014`.

| # | Case | Where |
|---|---|---|
| 1 | Skewed nulls | Whole table. 494 of 500 have no lead volunteer and 29 have no beneficiary. Requests 80 to 82 always have no beneficiary. |
| 2 | Several rows with the same last_updated_at | Requests 1 to 10, all 2026-03-01 12:00:00.123456 |
| 3 | last_updated_at earlier than submission_date | Requests 11 to 13 |
| 4 | Newlines, commas and double quotes in text | Requests 14 and 15 |
| 5 | Non-ASCII text | Requests 16 and 17 (also 24 and 28) |
| 6 | Personal details in free text | Requests 18 to 25, listed in pii_rows.csv. Covers phone numbers in several formats, one written as words, an email, a street address and names. |
| 7 | Empty string instead of NULL | Request 26, in req_doc_link, audio_req_desc and deletion_reason |
| 8 | Text at the maximum length | Request 27 (subject 125, description 255, audio description 255). Request 28 does the same with non-ASCII text. |
| 9 | Every lookup value used | Statuses 0 to 8 in requests 30 to 38, priorities 0 to 3 in 40 to 43, types in 50 and 51, request_for in 60 and 61 |
| 10 | req_islead_id = 1 with no lead volunteer | Requests 70 to 75. Requests 76 to 78 have both, for comparison. |
| 11 | Reference to a row that does not exist | fixture_broken_reference.csv, request `REQ-000-000-000-9999`, creator `SID-00-000-000-000-099-999` |

## Notes

- Case 9 covers the values that no real request uses yet: the CRITICAL priority and the RESOLVED, CANCELLED and VOLUNTEER_NOT_FOUND statuses.
- The empty-string case (7) only covers the nullable text columns of `requests`. The lookup descriptions are always filled in.
- All timestamps are fixed dates in 2026, so the output does not depend on when the script runs.