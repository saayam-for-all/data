# Virginia Analytics Mock Data Generator (Task 301)

Generates fully synthetic mock CSV data for local development, API
testing, dashboard testing, and demos of the Virginia analytics
database tables. No real or sensitive information is used anywhere.

## Tables generated

| File | Table | Notes |
|---|---|---|
| `countries.csv` | `countries` | Reference/lookup table |
| `states.csv` | `states` | Reference/lookup table, FK -> `countries` |
| `cities.csv` | `cities` | Reference/lookup table, FK -> `states` |
| `help_categories.csv` | `help_categories` | Reference/lookup table |
| `organizations.csv` | `organizations` | FK -> `states` |
| `users.csv` | `users` | FK -> `countries`, `states` |
| `volunteer_details.csv` | `volunteer_details` | FK -> `users` (1:1 subset of users) |
| `user_skills.csv` | `user_skills` | FK -> `users`, `help_categories` |
| `volunteer_locations.csv` | `volunteer_locations` | FK -> `volunteer_details.user_id` (not `users.user_id` directly) |
| `user_locations.csv` | `user_locations` | FK -> `users.user_id` directly |

### A note on row counts

The ticket asked for "~100 records per table" in one place and
"400 rows per file" in another. This generator resolves that by
treating the tables as two groups:

- **Reference/lookup tables** (`countries`, `states`, `cities`,
  `help_categories`) are intentionally **not** padded to a fixed row
  count. Their size is driven by the real, geographically-consistent
  reference set in `utils.py` (3 countries, their states, and each
  state's cities). Inflating these with made-up countries/states/cities
  would violate the "geographic relationships must be logically
  consistent" requirement, so they stay small and real-looking.
- **Fact-style tables** (`users`, `organizations`, `volunteer_details`,
  `user_skills`, `volunteer_locations`, `user_locations`) scale with
  `--num-users` / `--num-orgs`. Pass `--num-users 400` to get the
  "400 rows per file" version the ticket suggested as an option; the
  default is 100 to match the "~100 records per table" option.

### Schema assumptions

The task's linked wiki page (`Changes to the Database, Waiting for
Microservice`) was not reachable from this environment, so table/column
names below reflect the task description plus the pluralization rename
noted in the ticket (`states`, `cities`, `countries`). **Before merging,
double-check these column names and types against the current wiki page**
and adjust `generate_mock_data.py` / `utils.py` if anything has moved:

- `countries(country_id PK, country_name)`
- `states(state_id PK, state_name, state_code, country_id FK NOT NULL)`
- `cities(city_id PK, city_name, state_id FK, latitude, longitude)`
- `help_categories(cat_id PK, cat_name, description)`
- `organizations(org_id PK, org_name, state_id FK, city_name, created_at, last_updated_at)`
- `users(user_id PK, first_name, last_name, email, phone_number, country_id FK, state_id FK, city_name, created_at, last_updated_at)`
- `volunteer_details(user_id PK+FK -> users.user_id, availability_hours_per_week, skills_summary, is_active, created_at, last_updated_at)`
- `user_skills(user_skill_id PK, user_id FK -> users, cat_id FK -> help_categories, proficiency_level, created_at)`
- `volunteer_locations(location_id PK, user_id FK -> volunteer_details.user_id, curr_lat, curr_lng, prev_lat, prev_lng, updated_at)`
- `user_locations(location_id PK, user_id FK -> users.user_id, curr_lat, curr_lng, prev_lat, prev_lng, updated_at)`

`users` and `organizations` store `city_name` as free text (not a
`city_id` FK), matching the note in the ticket. `volunteer_locations`
and `user_locations` store raw `curr_lat/curr_lng` and `prev_lat/prev_lng`
columns instead of a `city_id`/`state_id`, also per the ticket — the
coordinates are jittered from the real centroid of the user's own city
so they land plausibly nearby.

## Requirements

```
pip install faker
```

(Standard library `csv`, `random`, `datetime`, `argparse` cover everything else.)

## How to run

From this directory:

```bash
# Default: 100 users, 100 orgs, seed 42
python generate_mock_data.py

# Match the ticket's "400 rows per file" suggestion
python generate_mock_data.py --num-users 400 --num-orgs 400

# Fully custom
python generate_mock_data.py --num-users 250 --num-orgs 150 --volunteer-fraction 0.6 --location-fraction 0.9 --seed 7 --output-dir ./out
```

### Configuration flags

| Flag | Default | Meaning |
|---|---|---|
| `--num-users` | 100 | Number of `users` rows |
| `--num-orgs` | 100 | Number of `organizations` rows |
| `--volunteer-fraction` | 0.7 | Fraction of users who also get a `volunteer_details` row |
| `--location-fraction` | 0.85 | Fraction of eligible users who get a location row |
| `--seed` | 42 | Random seed, for reproducible output |
| `--output-dir` | `.` | Where to write the CSV files |

## Validating the output

```bash
python validate_mock_data.py --dir .
```

Checks performed:
- Primary keys unique in every table
- No orphan foreign keys (`state_id`, `country_id`, `user_id`, `cat_id`, etc.)
- `created_at <= last_updated_at` wherever both columns exist
- Every `city_name` actually belongs to its row's `state_id`
- No blank values in required fields

Exits with a non-zero status if any check fails, so it can be wired
into CI later if useful.

## Table relationships (summary)

```
countries ──< states ──< cities
                │
                ├──< organizations
                │
                └──< users ──< volunteer_details ──< volunteer_locations
                       │             │
                       │             └── (1:1 subset of users)
                       ├──< user_skills >── help_categories
                       └──< user_locations
```

## Output location

CSV files and this generator are meant to live at:

```
data-analytics/mock-data-generation/
├── generate_mock_data.py
├── validate_mock_data.py
├── utils.py
├── README.md
├── countries.csv
├── states.csv
├── cities.csv
├── help_categories.csv
├── organizations.csv
├── users.csv
├── volunteer_details.csv
├── user_skills.csv
├── volunteer_locations.csv
└── user_locations.csv
```
