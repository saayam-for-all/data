# Saayam Mock Data Generation

Generates realistic **synthetic** mock data in CSV format for 10 core tables of
the `virginia_dev_saayam_rdbms` schema. Intended for local development, API
testing, dashboard development, and demos — **no real personal data is ever
produced**.

Resolves [saayam-for-all/data#301](https://github.com/saayam-for-all/data/issues/301).
Column definitions follow the current ("Table after changes") schema and the
pluralization section in the database wiki,
["Changes to the Database, Waiting for Microservice"](https://github.com/saayam-for-all/database/wiki/%2A-Changes-to-the-Database%2C-Waiting-for-Microservice).

## Tables produced

One CSV per table, written to `output_csv_files/`:

| CSV | Purpose | ~rows (default) |
|-----|---------|-----------------|
| `countries.csv` | Countries (reference) | 6 |
| `states.csv` | States/provinces per country | 18 |
| `cities.csv` | Cities per state (real + synthesized) | ~110 |
| `help_categories.csv` | Hierarchical help categories | 36 |
| `users.csv` | Application users | 400 |
| `user_skills.csv` | User ↔ category skills (composite PK) | ~1180 |
| `user_locations.csv` | Current/previous user geolocation | ~290 |
| `volunteer_details.csv` | Volunteer onboarding details | ~180 |
| `volunteer_locations.csv` | Volunteer geolocation | ~150 |
| `organizations.csv` | Partner/aggregated organizations | 400 |

Reference/geo tables (`countries`, `states`, `cities`, `help_categories`) are
sized from curated real-world data rather than padded to 400 rows — padding them
would break geographic consistency. Transactional tables default to ~400 rows
and are configurable.

## Quick start

```bash
cd data-analytics/mock-data-generation
python generate_mock_data.py
```

No dependencies — Python 3.8+ standard library only.

### Options

```bash
python generate_mock_data.py --users 1000 --orgs 500   # resize (>= 0; 0 allowed)
python generate_mock_data.py --seed 7                   # different reproducible set
python generate_mock_data.py --out ./csv                # custom output dir
python generate_mock_data.py --no-validate              # skip validation
```

Invalid inputs are rejected before generation with a clear `ConfigError`
(negative counts, ratios outside `[0,1]`, `skills_max < skills_min`, negative
city counts). Run `--help` for the full list.

## Validation

Tables are built parents-first, and every run validates the whole dataset
in-memory before writing, aborting with an explicit `ValidationError`
(never a bare `assert` — those disappear under `python -O`) on any failure of:

- **Schema / headers / required fields** — all 10 tables present; each table's
  columns exactly match the schema set and order; no missing/extra fields; NOT
  NULL / PK columns non-empty.
- **Types (parsed, not just regex)** — integers, `DECIMAL(9,6)` precision,
  `date`/`timestamp` parsed with `datetime.strptime` (so `2021-02-30` or month
  `13` are rejected), native `point` `(lon,lat)`, `geography` EWKT, `jsonb`
  (must parse), booleans.
- **Ranges & lengths** — `org_rating` 1–5, integer bounds, `varchar(n)` length
  limits, enum membership (`org_type`, `org_size`, `skill_level`, gender, auth
  provider).
- **Timestamp ordering** — `created_at ≤ last_updated_at`; volunteer_details
  document updates (`terms_accepted_at`, `path1/2_updated_at`) fall within
  `[created_at, last_updated_at]`; `volunteer_locations.last_updated_at` is at or
  after the matching `volunteer_details.created_at`.
- **Geography** — coordinates within global bounds and within ~0.5° of the
  assigned city; `time_zone` matches the state's canonical IANA zone; postal code
  matches the city's country-appropriate format and its expected city value.
- **External lookups** — `user_status_id` and `language_1/2/3` checked against
  the verified lookup id sets (see below), not assumed ranges.
- **PK uniqueness & FK validity** — including the composite
  `user_skills(user_id, cat_id)` and, critically,
  `volunteer_locations.user_id → volunteer_details.user_id`.
- **Geographic consistency** — every `users`/`organizations`
  `(city_name, state_id, country_id)` exists in the geo tables.

## Determinism

Output is seeded (`--seed`, default `42`), so the same seed produces
byte-identical CSVs. Change the seed for a different but equally valid dataset.
The test suite asserts the committed CSVs equal a default regeneration.

## Data conventions

- **Timestamps** — all timestamp columns are `TIMESTAMP WITHOUT TIME ZONE`,
  formatted `YYYY-MM-DD HH:MM:SS` (this includes
  `volunteer_locations.last_updated_at`).
- **Dates** — `dob` as `YYYY-MM-DD`.
- **`users.last_location`** — native PostgreSQL `point`: `(lon,lat)`.
- **`geography(Point,4326)`** (`user_locations`, `volunteer_locations`
  `prev_loc`/`curr_loc`) — EWKT `SRID=4326;POINT(lon lat)`.
- **Languages** — `users.language_1/2/3` are numeric `language_id`s.
- **jsonb** — compact JSON (`availability_days`, `availability_times`).
- **Booleans** — `True` / `False`.
- **Enums** — `organizations.org_type` ∈ {`non_profit`, `for_profit`};
  `organizations.org_size` ∈ {`small`, `medium`, `large`}.
- **Postal codes** — country-appropriate: US/DE 5-digit, AU 4-digit, IN 6-digit,
  CA `A1A 1A1`, UK `SW1A 1AA`. The postal is a property of the city (all rows in
  a city share it), so it always belongs to that city — never a numeric offset.
- **NULLs** — emitted as empty fields.
- **user_id** — Cognito-`sub`-style UUID (fully synthetic; see loading note).
- **Emails / websites** — `example.org` for users and the reserved `.example`
  TLD (RFC 2606) for organizations, so a generated domain can never belong to a
  real organization.
- **Phones** — reserved fictional `555-01xx` range.

## Required seed / verified lookup data

Two tables carry foreign keys into out-of-scope lookups. The generator emits
only **verified** ids and validates against the same sets — it does not assume
`1–N` exists.

**Provenance.** The verified id sets were read on **2026-09-08** from the
`saayam-for-all/database` repository, pinned to commit
[`a9a14a18aaac012f425b946ae4639e0535f7efce`](https://github.com/saayam-for-all/database/commit/a9a14a18aaac012f425b946ae4639e0535f7efce),
from these exact files:

- [`lookup_tables/supporting_languages.csv`](https://github.com/saayam-for-all/database/blob/a9a14a18aaac012f425b946ae4639e0535f7efce/lookup_tables/supporting_languages.csv)
  — `language_id` **1–12** (12 rows).
- [`lookup_tables/user_status.csv`](https://github.com/saayam-for-all/database/blob/a9a14a18aaac012f425b946ae4639e0535f7efce/lookup_tables/user_status.csv)
  — only `user_status_id` **1 (ACTIVE)** is committed.

`reference_data.VERIFIED_LANGUAGE_IDS` / `VERIFIED_USER_STATUS_IDS` mirror those
exact rows, and `config.LANGUAGE_IDS` / `config.USER_STATUS_IDS` are the single
place to widen them **after** the corresponding lookup rows are actually seeded.
An empty list makes the generator emit `NULL` for that column.

**Seeding the lookups locally.** [`seed_local_lookups.sql`](seed_local_lookups.sql)
inserts exactly those 12 language rows and the single `user_status` row
(`ON CONFLICT … DO NOTHING`) and then, in a `DO` block, **fails loudly** if a
pre-existing lookup row disagrees with the pinned mapping rather than silently
trusting it. It is transcribed from the same commit; the current schema renames
`iso_639_1_code → iso_code` and `last_update_date → last_updated_at`. The
one-shot loader below runs it for you (`\ir seed_local_lookups.sql`); to seed the
lookups on their own:

```bash
psql -X -v ON_ERROR_STOP=1 -d saayam_mock_301 -f seed_local_lookups.sql
```

Before loading `users`, seed `supporting_languages`, `user_status`, plus
`countries`/`states`/`cities` from the generated CSVs (they are the FK parents
for `users`).

## Loading into PostgreSQL (local dev)

> **Live import exercised.** The load path was run against an isolated local
> PostgreSQL/PostGIS test database via [`tests/check_postgres.py`](tests/check_postgres.py).
> All **2,777** generated rows imported; the CSV `user_id`/`org_id` values were
> preserved by disabling **only** `before_insert_users` and
> `before_insert_organizations` for the duration of the transaction, both
> triggers were restored before `COMMIT`, and FK/check constraints stayed active
> throughout. Deterministic CSV content and every in-memory check are also
> covered by the unit test suite.

### One-shot loader (recommended)

[`load_local.sql`](load_local.sql) performs the **entire** load as one ordered,
transactional procedure against a **fresh, isolated** local database. From this
directory:

```bash
psql -X -v ON_ERROR_STOP=1 -d saayam_mock_301 -f load_local.sql
```

In order, inside a single `BEGIN … COMMIT`, it:

1. Locks the ten in-scope tables and **refuses to run** if any is non-empty
   (nothing is truncated or dropped).
2. Runs [`seed_local_lookups.sql`](seed_local_lookups.sql) to seed
   `supporting_languages` / `user_status` (see the provenance section above).
3. Disables **only the two ID-replacement triggers** — `before_insert_users`
   and `before_insert_organizations` — leaving every FK/check trigger active.
4. `\copy`-loads all ten CSVs **parents-first** (`countries` → `states` →
   `cities` → `help_categories` → `users` → dependents → `organizations`).
5. Re-enables both triggers **before `COMMIT`**, then advances the `SERIAL` /
   `BIGSERIAL` sequences past the explicit ids so later inserts still work.

### Why the ID triggers must be disabled for the load

`users` and `organizations` each carry a `BEFORE INSERT` trigger that
**replaces any supplied primary key** with a generated one:

| Table | Trigger | Function | Replaces `…` with |
|-------|---------|----------|-------------------|
| `users` | `before_insert_users` | `generate_sid()` | `SID-…` |
| `organizations` | `before_insert_organizations` | `generate_org_id()` | `ORG-…` |

If either fires during the bulk load, the CSV keys are discarded: the `users`
UUIDs vanish and every dependent table (`user_skills`, `user_locations`,
`volunteer_details`, `volunteer_locations`) is orphaned. Disabling **the
specific ID trigger by name** — not `DISABLE TRIGGER USER`, which would also
switch off other user-defined triggers on the table — preserves the CSV keys
while keeping referential checks live. The loader restores both triggers before
`COMMIT`:

```sql
BEGIN;
ALTER TABLE virginia_dev_saayam_rdbms.users        DISABLE TRIGGER before_insert_users;
ALTER TABLE virginia_dev_saayam_rdbms.organizations DISABLE TRIGGER before_insert_organizations;
-- \copy the CSVs parents-first here …
ALTER TABLE virginia_dev_saayam_rdbms.users        ENABLE TRIGGER before_insert_users;
ALTER TABLE virginia_dev_saayam_rdbms.organizations ENABLE TRIGGER before_insert_organizations;
COMMIT;
```

`ALTER TABLE … DISABLE TRIGGER` **changes the table's persistent trigger state
in the catalog** — it is *not* a session-scoped setting and does not revert on
its own. That is exactly why the trigger is re-enabled inside the same
transaction: if the load fails, the surrounding `ROLLBACK` (via
`ON_ERROR_STOP`) also reverts the `DISABLE`, so the table never remains with a
trigger switched off. Run this **only** against a disposable local dev database;
do **not** run it against production, and do **not** alter the trigger
definitions themselves.

## Testing

```bash
python -m unittest discover -s tests    # or: python -m pytest tests
```

The suite (52 tests) covers: rejection of every invalid-config and
invalid-data case — including PostgreSQL `INTEGER`/`BIGINT` overflow,
`varchar(n)` length limits, out-of-bounds city coordinates, and non-finite /
out-of-range `jsonb` numbers — plus defaults, multiple seeds,
zero/single/large datasets, determinism, and that the committed CSVs match a
default regeneration. Tests write only to temporary directories, so they leave
no artifacts.

## Layout

```
data-analytics/mock-data-generation/
├── generate_mock_data.py   # CLI entry point + all validators (exception-based)
├── generators.py           # one build_* function per table + build_geo aux maps
├── reference_data.py       # curated geo tree (tz + real postal per city), categories, verified lookup ids, pools
├── config.py               # row counts, seed, verified lookup sets, config validation
├── utils.py                # seeding, formatting, postal synthesis, CSV writer, exceptions
├── requirements.txt        # (stdlib only — no dependencies)
├── seed_local_lookups.sql  # pinned supporting_languages / user_status seed (+ conflict guard)
├── load_local.sql          # one-shot transactional CSV loader (parents-first, ID triggers handled)
├── .gitignore              # excludes __pycache__ / *.pyc / .pytest_cache
├── README.md
├── tests/
│   ├── test_generate.py    # regression suite
│   ├── schema.sql          # isolated integration-test schema (incl. ID-replacement triggers)
│   └── check_postgres.py   # optional live-PostgreSQL smoke test
└── output_csv_files/       # generated CSVs
```

## Notes on schema fidelity

- Names/order match the wiki "Table after changes"; reference tables use the
  plural physical names (`countries`, `states`, `cities`).
- `users` has no `user_category_id`; volunteers are selected by ratio
  (`config.VOLUNTEER_RATIO`) since the schema carries no user-category column.
- `organizations` references `state_id`, and carries `org_type`, `org_size`,
  `org_rating`, `is_collaborator`, `is_contributor` (no `cat_id`/`source`).
- `state_id` is `VARCHAR` and is emitted as integer-valued strings (`"1"`, …).
- `user_skills.skill_level` uses the `skill_levels` enum, defined in the schema
  wiki as exactly `BEGINNER`, `INTERMEDIATE`, `ADVANCED`, `EXPERT`. The
  generator emits those four values (`reference_data.SKILL_LEVELS`) and
  validation checks membership against them; the enum is authoritative and
  needs no additional seeding.
