# Mock data for the request archival pipeline (issue #587)

Generates `requests` and every table it references, built from `saayam_schema.sql` only. No real or dev data is read or copied. Replaces the old, mutually inconsistent CSVs in `data-analytics/sql`.

## Quick start

Requirements: Python 3.7+ (standard library only) and a local Postgres with the PostGIS extension available (`requests.req_loc` and `created_loc` are `geometry` columns). With Docker, the `postgis/postgis` image works. Copy `saayam_schema.sql` from issue #573 into this folder.

Create an empty database once (`createdb saayam_mock`), then from this folder:

```
python3 generate.py
psql -d saayam_mock -f load.sql
```

`load.sql` enables PostGIS, drops and recreates the `virginia_dev_saayam_rdbms` schema, runs `saayam_schema.sql`, loads every CSV, and moves the lookup sequences past the inserted IDs. It is safe to rerun. To check that every case survived loading, run `psql -d saayam_mock -f verify.sql`.

Options: `--seed` (default 573), `--requests` (default 500), `--users` (default 150), `--out` (default `./output`). The same seed and options always produce byte-identical files. All randomness goes through `random.Random.random()`, whose sequence Python guarantees across versions, and nothing reads the clock. The script runs a self-check before writing and exits with an error if any case is missing.

## Output

| File | Contents |
|---|---|
| `request_for.csv`, `request_isleadvol.csv`, `request_types.csv`, `request_priorities.csv`, `request_statuses.csv` | Lookup tables with their real IDs and values from the schema comments |
| `help_categories.csv` | 61 invented categories in the live format |
| `help_categories_map.csv` | One parent → child row per non-top-level category |
| `users.csv` | `user_id` only |
| `requests.csv` | 500 requests |
| `case_index.csv` | Every special row and the case it covers |
| `pii_rows.csv` | Which rows and columns hold planted personal details, and what kind |
| `fixtures/requests_broken_reference.csv` | Case 11, kept out of the main data |

CSV conventions: UTF-8, `\n` line endings, header row. Text is always quoted and NULL is an empty unquoted field, so under Postgres `COPY ... CSV` a quoted `""` loads as an empty string and a bare empty field loads as NULL. Geometry is EWKT (`SRID=4326;POINT(lon lat)`). Timestamps are written as plain UTC with no offset, matching the schema's `without time zone` columns.

## Cases

The numbers follow the order the cases are listed in issue #587. `case_index.csv` lists the exact `req_id` for every special row; the IDs below are for the default seed.

| # | Case | How it is covered |
|---|---|---|
| 1 | Skewed nulls in nullable references | Scaled from dev's 221 rows: 493 of 500 `lead_volunteer_id` NULL, 18 `beneficiary_id` NULL. An inner join on lead volunteer returns 7 rows. |
| 2 | Shared `last_updated_at` | 4 rows at `2026-09-01 00:00:00.000000` (a likely window edge) and 4 at `2026-07-14 09:30:15.482913`. |
| 3 | `last_updated_at` before `submission_date` | 3 rows: `REQ-000-000-000-0074`, `-0139`, `-0226`. |
| 4 | Newlines, commas, double quotes | 3 rows: `\n` inside text, `\r\n` inside text, and a value ending in a newline. |
| 5 | Non-ASCII text | 10 Spanish rows, plus Vietnamese, Hindi, Chinese and emoji. Several case 6 and 8 rows are also non-ASCII. |
| 6 | Planted personal details | 13 rows across `req_subj`, `req_desc`, `deletion_reason` and `audio_req_desc`: phone numbers in several formats and as words (English and Spanish), plain and obfuscated emails, street and PO box addresses, names including non-English ones. All fictional (555-01xx numbers, the UK 020 7946 0xxx drama range, `example.*` domains). Marked in `pii_rows.csv`. |
| 7 | Empty string vs NULL | `req_doc_link`, `audio_req_desc` and `deletion_reason` each hold both `''` and NULL. Every lookup `_desc` column holds both too. |
| 8 | Maximum length | `req_subj` at 125 and `req_desc` at 255, each once in ASCII and once with multi-byte characters (so byte length exceeds the limit), and `audio_req_desc` at 255. Category `7.5` fills `cat_name` (100) and `cat_desc` (150). `CRITICAL` and `CANCELLED` fill their 125-character desc. |
| 9 | Every lookup value used | Every status, priority, type, for and islead value, and every category, is used by at least one request. CRITICAL, RESOLVED, CANCELLED and VOLUNTEER_NOT_FOUND have no natural weight and are forced into 2 rows each. |
| 10 | `req_islead_id = 1` with NULL `lead_volunteer_id` | 20 rows flagged, 7 with a lead volunteer, 13 without, matching dev's proportions (9 flagged, 3 recorded). |
| 11 | Broken reference | `fixtures/requests_broken_reference.csv`: one request whose `creator_id` matches no user. See below. |

Not a numbered case: 2 rows have a NULL `submission_date`, since the column allows it.

### Loading the broken-reference fixture

It fails the foreign keys by design, so load it into a copy of `requests` without constraints:

```sql
CREATE TABLE virginia_dev_saayam_rdbms.requests_broken
    (LIKE virginia_dev_saayam_rdbms.requests INCLUDING DEFAULTS);
\copy virginia_dev_saayam_rdbms.requests_broken FROM 'output/fixtures/requests_broken_reference.csv' WITH (FORMAT csv, HEADER true)
```

## Design decisions

- **Lookup values** come from the comments in `saayam_schema.sql`. The issue mentions a comment on #573 listing them, but there is none. Descriptions are invented.
- **ID formats** follow the schema comments: `REQ-000-000-000-0000` and `SID-00-000-000-000-000-026`. The generator writes them directly; `saayam_schema.sql` does not include the triggers that create them in dev.
- **Category tree** is invented but follows the live format: dotted-path IDs, up to three levels, UPPER_SNAKE names, `NAME_DESC` descriptions, and a `0.0.0.0.0` catch-all. It includes a parent with 12 children (`3.1.10` sorts before `3.1.2` as text), one row out of file order (`3.1.12`), and parentheses in a name.
- **Top-level categories and `0.0.0.0.0` have no row in `help_categories_map`.** Only children do. Change this if dev turns out to store top-level rows with a NULL `parent_id`.
- **Two-row lookup tables** (`request_for`, `request_isleadvol`, `request_types`) carry one NULL and one `''` description, since case 7 needs both in every nullable text column. That leaves no room for a max-length description in those tables.
- **`request_types.req_type` is nullable** in the schema but is kept at its real values, since those are fixed. It is the one nullable text column without `''` and NULL.
- **Lookup name columns** (`req_status` etc.) are not filled to their limits, since they hold real values.

## Removing the old CSVs

Delete the old CSV files in `data-analytics/sql` only after this output has been reviewed and the pipeline has run against it.
