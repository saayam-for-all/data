# Mock data generator for `requests` (issue #587)

Generates CSVs for `requests` and every table it references, from the schema only.
No database access; no real or dev data.

## Run

```bash
python generate_mock_data.py                 # writes ./output, seed 587, 500 requests
python generate_mock_data.py --seed 1 --out /tmp/x --n-requests 1000
```

Same seed => byte-identical output (UTF-8, LF, no BOM, fixed timestamps, no `now()`).

## Load into local Postgres

```bash
./load_local.sh saayam_mock path/to/saayam_schema.sql
```

Loads in FK order: request_statuses, request_priorities, request_types, request_for,
request_isleadvol, help_categories, help_categories_map, users, requests.
NULL is written as a bare empty field and an empty string as `""`, so Postgres
`COPY ... CSV` keeps them distinct.

`requests_broken_refs.csv` is **not** loaded by the script (see case 11).

## Output files

| File | Contents |
|---|---|
| `requests.csv` | 500 requests |
| `help_categories.csv`, `help_categories_map.csv` | plausible 2-level category tree |
| `request_for/_isleadvol/_types/_priorities/_statuses.csv` | lookup values |
| `users.csv` | key column only |
| `requests_pii_flags.csv` | `req_id, pii_types` for rows with planted PII (case 6) |
| `requests_case_map.csv` | `req_id, cases` : which numbered cases each row covers |
| `requests_broken_refs.csv` | case 11 fixture, same columns as `requests.csv` |

## Cases (numbered in the order of the issue)

Find rows with `requests_case_map.csv` (cases are `;`-separated).

| # | Case | Where |
|---|---|---|
| 1 | Skewed nulls: ~1.4% have a lead volunteer, ~3.6% have no beneficiary (live: 218/221 and 8/221) | `lead_volunteer_id`, `beneficiary_id` |
| 2 | 10 rows with `last_updated_at = 2025-06-15 12:00:00.123456`, plus one row at -1 µs and one at +1 µs | case map `2` |
| 3 | 5 rows with `last_updated_at` < `submission_date` | case map `3` |
| 4 | Newlines (LF and CRLF), commas, double quotes in `req_desc`/`req_subj` | case map `4` |
| 5 | Non-ASCII (Spanish, French, Chinese, Russian, Polish, emoji) | case map `5` |
| 6 | PII: phones in several formats, spoken digits ("four eight zero"), emails, street addresses, names incl. non-English | `requests_pii_flags.csv` |
| 7 | 3 empty-string and 3 NULL rows for each nullable text column | case map `7` |
| 8 | `req_subj` exactly 125 chars, `req_desc` exactly 255 chars (one ASCII, one multibyte) | case map `8` |
| 9 | Every lookup value used at least once; dedicated rows for CRITICAL, RESOLVED, CANCELLED, VOLUNTEER_NOT_FOUND | case map `9` (dedicated rows); generator asserts full coverage |
| 10 | `req_islead_id = 1` with NULL `lead_volunteer_id` | case map `10` |
| 11 | Rows pointing at non-existent user, category, status, priority, beneficiary, lead volunteer (ids 900001-900006) | `requests_broken_refs.csv` |

## Verify against the schema before committing

The generator was written without `saayam_schema.sql`. The `SCHEMA` block at the top of
`generate_mock_data.py` holds every assumed table/column name and lookup value
(including that `lead_volunteer_id`/`beneficiary_id` reference `users.user_id`, and
the `help_categories` columns). Check it against #573 and edit as needed. If `users` has other
NOT NULL columns, the key-only load in `load_local.sh` will need defaults.
