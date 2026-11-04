# Synthetic requests data (Issue #587)

Fully synthetic, deterministic data for `requests` and the eight tables it references, built from
`saayam_schema.sql` (the schema attached to Issue #573). No real or development data is read or copied.

## Generate

```bash
python3 data-engineering/mock_data/requests/generate.py            # default seed 587
python3 data-engineering/mock_data/requests/generate.py --seed 1 --out /tmp/other
```

Same seed gives byte-identical files. The generator uses only the standard library and fixed dates (no clock).
Lookup rows are taken from `database/lookup_tables/`, plus status 8 `VOLUNTEER_NOT_FOUND`, which the schema
defines but that file lacks. Nothing else is added.

## Output

| Path | Contents |
|---|---|
| `csv/*.csv` | The nine tables, with headers, in foreign-key load order: `help_categories`, `help_categories_map`, `request_for`, `request_isleadvol`, `request_types`, `request_priorities`, `request_statuses`, `users` (`user_id` only), `requests` (500 rows) |
| `special_cases_manifest.csv` | Which request IDs and columns exercise each numbered edge case, including the synthetic personal details |
| `fixtures/broken_fk/requests_broken_fk.csv` | Nine rows, each breaking one foreign key. **Never part of the main load.** |

## CSV convention

Matches `COPY ... WITH (FORMAT csv, HEADER true, NULL '\N')`.

| Value | Written as |
|---|---|
| SQL `NULL` | `\N`, unquoted |
| empty string | an empty field |
| boolean | `true` / `false` |
| geometry | EWKT, `SRID=4326;POINT(lon lat)` |
| timestamp | `YYYY-MM-DD HH:MM:SS.ffffff`, UTC by convention |

UTF-8, NFC-normalised, no BOM, rows end with `\n`. Tools such as pandas read `\N` as text unless told
`na_values=["\\N"]`.

## Edge cases

| # | Case | Test (`data-engineering/tests/test_mock_requests_data.py`) |
|---|---|---|
| 1 | 493/500 null leads, 18/500 null beneficiaries | `test_case_1_skewed_null_references` |
| 2 | Identical microsecond `last_updated_at`, day-end and midnight ties | `test_case_2_...`, `test_timestamp_boundaries_follow_the_archive_pipeline_sql` |
| 3 | Updated before submitted | `test_case_3_updated_before_submitted` |
| 4 | Newlines, commas, quotes | `test_case_4_csv_special_characters_round_trip` |
| 5 | Unicode and Spanish | `test_case_5_unicode_and_spanish_text` |
| 6 | Synthetic personal details | `test_case_6_synthetic_personal_details_are_tracked` |
| 7 | `''` vs `NULL` | `test_case_7_empty_string_is_distinct_from_null` |
| 8 | Exact maximum lengths | `test_case_8_exact_maximum_lengths` |
| 9 | Every lookup value, CRITICAL, status 8 | `test_case_9_every_lookup_value_is_used` |
| 10 | `req_islead_id = 1`, NULL lead | `test_case_10_islead_yes_with_null_lead_volunteer` |
| 11 | Broken FK fixture, kept out of the load | `test_case_11_broken_fk_fixture_is_separate_and_broken` |

Personal details use reserved fictional values only: `555-01xx` phone numbers, `example.test` emails and
placeholder names and addresses.

## Timestamp boundaries

`archive.export_requests_to_s3` selects `last_updated_at > watermark_start AND <= watermark_end`, then splits
by day with `>= day_start AND < day_start + 1 day`. The tie clusters sit at `2026-09-30 23:59:59.999999`,
`2026-10-01 00:00:00.000000` and `2026-08-15 12:34:56.123456`; the tests check the window and partition
predicates against that SQL.

## Load into a local PostgreSQL/PostGIS database

Required tools (macOS, Homebrew): `brew install postgresql@17 postgis`, plus Python with `psycopg2`
(`pip install -r data-engineering/requirements.txt`).

```bash
python3 data-engineering/mock_data/requests/generate.py     # 1. generate (only needed after changes)
python3 data-engineering/mock_data/requests/load_local.py   # 2. load into a throwaway database
```

`load_local.py` never connects to an existing server. It creates a new cluster in a temp directory
(`saayam587_pg_*`), listens on `127.0.0.1` at a random free port, creates the PostGIS extension and the
`virginia_dev_saayam_rdbms` schema, applies `saayam_schema.sql`, loads the nine CSVs in foreign-key order with
`COPY ... NULL '\N'`, resets the serial sequences, prints row counts and foreign-key status, then stops the
server and deletes that temp directory. Pass `--keep` to leave it running; the command to connect and the
exact cleanup command are printed. Nothing outside the temp directory is touched.

The broken-foreign-key fixture is never loaded by this script; the database tests load it one row at a time
inside rolled-back transactions.

## Tests

```bash
cd data-engineering
python -m pytest tests/test_mock_requests_data.py   # Python checks, no database needed
python -m pytest tests/test_mock_requests_db.py     # starts its own temporary cluster; skipped if PostgreSQL is missing
```

The Python tests parse `saayam_schema.sql` directly for columns, types, varchar limits, NOT NULL and foreign
keys. The database tests check the real load: row counts, foreign keys, NULL vs `''`, maximum lengths, value
round-trips (Unicode, quotes, commas, newlines, geometry, microsecond timestamps), the archive window and day
partition predicates in SQL against the mock table, the broken fixture failing with SQLSTATE 23503, and the
serial sequences continuing after explicit ids.
