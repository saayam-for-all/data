# Virginia analytics mock data

Synthetic fixtures for local development, API and dashboard testing, and demonstrations.
No source user records are read. Names are assembled from generic pools; addresses are
explicitly marked as mock data. Emails and URLs use reserved `example.com`/`example.org`
domains. Phone fields are empty (SQL NULL), since these international fixtures have no
single safe fictional numbering range. Reference country, state, and city names are real
geographic labels, not personal data.

## Schema source

Verified **2026-09-08** against the updated table definitions in the
[Virginia database wiki](https://github.com/saayam-for-all/database/wiki/*-Changes-to-the-Database,-Waiting-for-Microservice),
referenced by [issue #301](https://github.com/saayam-for-all/data/issues/301).
The pluralized names `countries`, `states`, and `cities` are used. The schema's spelling
`lattitude` is intentionally preserved. `schema.json` records column order, types, lengths,
and required fields; `schema.sql` records the corresponding table definitions for local
import verification. These are dated snapshots, not live database introspection.

## Files and relationships

| CSV | Default rows | Primary key | Foreign keys |
| --- | ---: | --- | --- |
| countries.csv | 242 | country_id | â€” |
| states.csv | 5,045 | state_id | country_id â†’ countries |
| cities.csv | 63 | city_id | state_id â†’ states |
| users.csv | 400 | user_id | country_id â†’ countries; state_id â†’ states; user_status_id â†’ user_status; language_1/2/3 â†’ supporting_languages |
| volunteer_details.csv | 240 | user_id | user_id â†’ users |
| help_categories.csv | 80 | cat_id | â€” |
| user_skills.csv | 400 | user_id, cat_id | user_id â†’ users; cat_id â†’ help_categories |
| user_locations.csv | 320 | user_id | user_id â†’ users |
| volunteer_locations.csv | 240 | user_id | user_id â†’ volunteer_details |
| organizations.csv | 400 | org_id | state_id â†’ states |

Lookup counts reflect the checked-in source files and can change when those sources change.
`--count` controls users, organizations, and user-skill mappings. Cities are limited
to `min(count, 63)` distinct curated places with the bundled lookup snapshot.
Volunteer and tracked-user records are reproducible random subsets, rather than
only the first user IDs. Default subset fractions are 60% and 80%, respectively.
Each volunteer has exactly one volunteer-location record. Skills are sampled as
unique user/category pairs and need not cover every user.

## Requirements and generation

Python 3.10+; generation, validation, and regression tests use only the standard library.
Run from the repository root:

```bash
python data-analytics/mock-data-generation/generate_mock_data.py
python data-analytics/mock-data-generation/generate_mock_data.py --count 1000 --seed 12345
python data-analytics/mock-data-generation/generate_mock_data.py --count 100 --output-dir ./custom_output
```

The default output is this script's directory, regardless of the working directory.
Explicit relative paths resolve from the current working directory. `--count` must be
positive. The same count, seed, code, and lookup files produce identical CSV bytes.
Files are staged and validated before output files are replaced.

`--lookup-dir PATH` defaults to this folder's `reference_data/` snapshot.
The snapshot is bundled because `dev` does not contain the shared lookup tables;
see [reference_data/README.md](reference_data/README.md) for its pinned source commit.
It must contain nonempty `country.csv`, `state.csv`, `help_categories.csv`,
`supporting_languages.csv`, and `user_status.csv`. Missing or invalid lookup data causes
failure rather than fallback IDs. Language and status IDs come from these files.

To adjust the volunteer and tracked-user populations:

```bash
python data-analytics/mock-data-generation/generate_mock_data.py --count 400 --volunteer-fraction 0.5 --user-location-fraction 0.75
```

Both fractions accept values from 0 to 1. Sizes are rounded down; a positive fraction
keeps at least one row for small datasets. Zero creates valid header-only optional
CSVs, enabling empty-volunteer or untracked-user dashboard scenarios. Use `1` for
both fractions when testing a population where every user volunteers and is tracked.

Before importing into an existing local schema, seed matching `supporting_languages` and
`user_status` records. They are prerequisites outside the ten-table deliverable.
Empty CSV cells represent SQL NULL with PostgreSQL `COPY ... FORMAT csv` defaults.

## Geographic coverage and scaling

City anchors preserve state, country, ZIP, time zone, and centroid relationships.
Cities are bounded reference data: larger entity counts do not pad the city table
with duplicate place names. Add a verified anchor to `SEEDED_CITIES` in `geography.py`
to expand coverage. Users and location records receive small coordinate offsets
around those anchors. Validation checks proximity, not administrative boundaries.

Native `users.last_location` uses `(latitude, longitude)` as documented by the schema.
PostGIS locations use `POINT(longitude latitude)` in WGS84. User IDs follow
`SID-00-000-000-000-000-001`; organization IDs follow `ORG-000-000-000-0001`.

## Validation and regression tests

```bash
python data-analytics/mock-data-generation/validate_mock_data.py
python data-analytics/mock-data-generation/validate_mock_data.py --data-dir ./custom_output
python -m unittest discover -s data-analytics/mock-data-generation -p test_mock_data.py -v
```

For custom lookup sources, pass the same `--lookup-dir` to generation and validation.
Checks include exact headers and CSV field counts; all ten primary keys; all scoped and
external lookup foreign keys; required values and VARCHAR limits; integer ranges,
booleans, enums, ratings, JSON availability arrays, dates and timestamps; timestamp order;
reserved contact domains; and country/state/city/ZIP/time-zone/location relationships.
The validator enforces the fixture conventions as well as SQL constraints, so it is
not intended as a general validator for arbitrary production exports.

Regression tests cover counts 1, 400, and 1,000; deterministic output; bad CLI arguments;
duplicate location keys and city names; malformed CSVs; empty/partial/full subsets;
invalid fractions; and deliberately corrupted fields and relations.

## Code layout and style

- `generate_mock_data.py`: generation and CLI orchestration.
- `validate_mock_data.py`: schema, relationship, timestamp, and geography passes.
- `schema.py`, `schema.json`, `schema.sql`: shared paths and dated schema contract.
- `geography.py`: shared city anchors.
- `utils.py`: serialization, identifiers, coordinate offsets, and synthetic value pools.
- `test_mock_data.py`: standard-library regression tests.
- `test_postgres_import.py`: optional Docker integration test.

Ruff is optional development tooling; it is not needed to run the scripts. To check
formatting, imports, annotations, and docstrings with the folder's `ruff.toml`:

```bash
python -m pip install ruff==0.16.6
ruff check data-analytics/mock-data-generation
ruff format --check data-analytics/mock-data-generation
```

## Optional PostgreSQL/PostGIS import test

Requires Docker running Linux containers and access to the configured PostGIS image:

```bash
python data-analytics/mock-data-generation/test_postgres_import.py
python data-analytics/mock-data-generation/test_postgres_import.py --data-dir ./custom_output
```

The test creates an isolated container without host ports or mounted directories, loads
`schema.sql`, seeds the two external lookup key sets, imports all ten files in dependency
order, and verifies row counts. It removes its container and volumes afterward.
Use `--image IMAGE` to select a compatible PostgreSQL/PostGIS image.

The local schema deliberately omits insert ID-generation triggers so supplied fixture IDs
are preserved. An existing database's triggers can overwrite those IDs; importing into
such a database needs an explicit ID-preservation/remapping strategy. This test checks
table types and constraints, not the full production trigger/application behavior.

Docker and PostgreSQL were unavailable in the implementation workspace, so the actual
PostgreSQL/PostGIS import test has **not been run**. Python validation and regression tests
are separate from that remaining integration check. Do not deploy these fixtures to AWS;
submit the code and CSVs through the issue's pull-request workflow.
