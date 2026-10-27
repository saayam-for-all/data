# Mock data for the requests table (issue 587)

Generates synthetic data for the requests table and the nine tables it references,
so this pipeline can be developed and tested without touching the dev database.

Nothing here is copied from a database. The data is built directly from
saayam_schema.sql (the schema attached to issue 573), which is also committed in
this folder so the generator and the load instructions below are self contained.

## Why this exists

The CSV files that used to live in data-analytics/sql were exported at different
times, between two and seven months apart, so the references between them no
longer held. A request could point at a user that did not exist yet when
users.csv was exported. Five of the tables requests references were not in the
folder at all. This generator replaces those files with a dataset that is
internally consistent and loads cleanly against the real schema.

## How to run it

    python generate_mock_data.py

Running it twice with the same seed produces byte identical output. Options:

    python generate_mock_data.py --seed 7 --requests 800 --output-dir /some/path

Default output is data-analytics/sql (one level up from this script), which is
where the nine main CSVs below are committed. Two extra files are written next to
this script instead, since they must stay out of the main dataset:

- broken_reference_fixture.csv, case 11 below.
- pii_flagged_requests.csv, the row by row index for case 6 below.

## Output files

In data-analytics/sql:

    requests.csv
    users.csv                  (key column only, matches the schema)
    help_categories.csv
    help_categories_map.csv
    request_for.csv
    request_isleadvol.csv
    request_types.csv
    request_priorities.csv
    request_statuses.csv

In this folder:

    saayam_schema.sql          (copy of the schema attached to issue 573)
    broken_reference_fixture.csv
    pii_flagged_requests.csv

## How to load it into a local Postgres

    docker run -d --name mockdb -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=saayam \
        -p 5433:5432 postgis/postgis:16-3.4

    docker cp saayam_schema.sql mockdb:/schema.sql
    docker exec mockdb psql -U postgres -d saayam -v ON_ERROR_STOP=1 -f /schema.sql

    docker cp ../requests.csv mockdb:/requests.csv
    docker cp ../users.csv mockdb:/users.csv
    docker cp ../help_categories.csv mockdb:/help_categories.csv
    docker cp ../help_categories_map.csv mockdb:/help_categories_map.csv
    docker cp ../request_for.csv mockdb:/request_for.csv
    docker cp ../request_isleadvol.csv mockdb:/request_isleadvol.csv
    docker cp ../request_types.csv mockdb:/request_types.csv
    docker cp ../request_priorities.csv mockdb:/request_priorities.csv
    docker cp ../request_statuses.csv mockdb:/request_statuses.csv

    for t in users help_categories help_categories_map request_for request_isleadvol \
             request_types request_priorities request_statuses requests; do
      docker exec mockdb psql -U postgres -d saayam -v ON_ERROR_STOP=1 \
        -c "SET search_path TO virginia_dev_saayam_rdbms, public" \
        -c "\copy $t FROM '/$t.csv' WITH (FORMAT csv, HEADER true)"
    done

Load users, then the lookup tables, then requests last, since requests
references all of them. The broken reference fixture is deliberately excluded
from this load; it cannot pass the real foreign key constraints, which is the
point of it (see case 11).

## The eleven required cases

Each one has caused a real bug in this pipeline before, or is a known risk. Row
numbers below are from the --seed 42 default run; a different seed moves them to
different rows, but every case is always present.

1. Skewed nulls on lead_volunteer_id and beneficiary_id, matching the real
   proportions in the schema comment (218 of 221 and 8 of 221), not a uniform
   rate. With 500 requests: 493 null lead_volunteer_id, 18 null beneficiary_id.
2. Five rows share one last_updated_at value, to the microsecond, so a
   half open window boundary has more than one row sitting on it.
3. One row has a last_updated_at earlier than its own submission_date.
4. One row's req_desc has an embedded newline, a comma and a double quote.
5. One row's req_desc is in Spanish, so it is not plain ASCII.
6. Eleven rows plant personal details inside req_desc: phone numbers in
   several formats including two spelled out in words, email addresses, street
   addresses, and names, including non English ones. Which row has which kind
   of planted detail is listed in pii_flagged_requests.csv, not in requests.csv
   itself.
7. Two rows per nullable text column (req_doc_link, audio_req_desc,
   deletion_reason): one holds an empty string, a different one holds an actual
   null, so the two are distinguishable rather than collapsed into each other.
   On disk this relies on Python 3.12's csv.QUOTE_NOTNULL: every non null field
   is quoted, a null field is left bare and unquoted, which is exactly how
   Postgres COPY tells NULL apart from ''.
8. One row's req_subj is exactly 125 characters and its req_desc is exactly
   255 characters, the maximum each column allows.
9. Every lookup value is used by at least one request, including priority
   CRITICAL and statuses RESOLVED, CANCELLED and VOLUNTEER_NOT_FOUND, none of
   which any real request currently uses.
10. Thirteen rows have req_islead_id = 1 with a null lead_volunteer_id, the
    same contradiction that exists in the real data (nine requests flagged with
    a lead volunteer, only three actually have one recorded), scaled to 500 rows.
11. broken_reference_fixture.csv holds one request whose req_cat_id does not
    match any row in help_categories.csv. This cannot happen in the real database,
    the foreign key forbids it, but the archival pipeline still needs to be
    checked against it, since a plain inner join would silently drop a row like
    this rather than flag it. It is excluded from the main data for exactly that
    reason: the main data should load without errors, and this row should not
    load at all, by design.

After generating, run generate_mock_data.py's own printed report (shown on every
run) to see exactly which req_id covers which case for that seed.

## Validated

- Loaded all nine CSVs into PostgreSQL 16 with PostGIS, built from
  saayam_schema.sql, with zero constraint violations.
- Every non null reference in requests.csv resolves to a real row in its target
  table (checked directly, independent of the database, and again by the
  database's own foreign key constraints on load).
- Running the generator twice with the same seed produced byte identical output.
- The null versus empty string distinction for req_doc_link, audio_req_desc and
  deletion_reason was checked at the byte level in the CSV itself.
- Loading broken_reference_fixture.csv on its own against the real schema fails
  on the req_cat_id foreign key, confirming it is genuinely unloadable, which is
  what makes it a useful fixture for the pipeline's own error handling rather
  than something that could occur in production.
