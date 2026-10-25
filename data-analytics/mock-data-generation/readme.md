# Issue #301 Mock Data Generation

This directory contains reusable mock-data generation scripts and CSV datasets for dashboard implementation, API testing, local development, and demos.

The latest Virginia database wiki is the source of truth for the Issue #301 table definitions. The current wiki confirms the pluralized table names `states`, `cities`, and `countries`, and the updated column names/types used by this package. Lookup values such as countries, states, cities, and hierarchical category IDs are retained so foreign-key relationships remain compatible with the project schema.

## Files

```text
mock-data-generation/
├── generate_mock_data.py
├── utils.py
├── README.md
├── states.csv
├── users.csv
├── volunteer_details.csv
├── cities.csv
├── user_skills.csv
├── volunteer_locations.csv
├── user_locations.csv
├── countries.csv
├── help_categories.csv
└── organizations.csv
```

## CSV purpose

- `countries.csv` — country lookup data.
- `states.csv` — state/region lookup data linked to `countries.csv`.
- `cities.csv` — city lookup data linked to `states.csv`; the schema uses the existing spelling `lattitude`.
- `users.csv` — synthetic user profiles linked to country and state values and consistently associated with a city.
- `volunteer_details.csv` — volunteer records linked one-to-one to `users.csv`.
- `user_skills.csv` — one-to-many skill mappings linked to `users.csv` and `help_categories.csv`.
- `volunteer_locations.csv` — previous/current WKT geography points for volunteer users.
- `user_locations.csv` — previous/current WKT geography points for users.
- `help_categories.csv` — hierarchical skill/category lookup values; `cat_id` is text.
- `organizations.csv` — synthetic organizations using valid city/state combinations and dashboard-compatible organization attributes.

## Schema alignment notes

The current `users` CSV follows the latest table definition: `user_category_id` is omitted, `last_updated_at` and `promotion_wizard_last_updated_at` use the current names, `language_1`/`language_2`/`language_3` contain numeric language IDs for the `BIGINT` foreign keys, and `is_eu` is included.

The current `user_skills` CSV includes the `skill_level` enum values `BEGINNER`, `INTERMEDIATE`, `ADVANCED`, and `EXPERT`.

`organizations.org_type` and `organizations.org_size` use the current PostgreSQL enum values `non_profit`/`for_profit` and `small`/`medium`/`large`.

`users.last_location` is represented as a PostgreSQL point literal `(longitude,latitude)`. The `user_locations` and `volunteer_locations` geography fields are represented as WKT `POINT(longitude latitude)`.

`volunteer_details.csv` retains the volunteer-detail columns from the project mock-data/database definition used for this task. The current wiki page does not publish a replacement `volunteer_details` table definition, so those columns are not changed based on unrelated tables.

## Geographic consistency

City/state assignments are the source for generated locations. `users.last_location`, `user_locations.prev_loc`, `user_locations.curr_loc`, `volunteer_locations.prev_loc`, and `volunteer_locations.curr_loc` are generated within a small offset of the assigned city's latitude/longitude, keeping the points geographically consistent with the user's city and state.

## Generate new data

Run from this directory:

```bash
python generate_mock_data.py
```

By default, generated files are written to `output_csv_files/`.

### Configurable row counts

```bash
python generate_mock_data.py --users 400 --volunteers 300 --organizations 400 --min-skills 1 --max-skills 3
```

For a different deterministic dataset:

```bash
python generate_mock_data.py --users 250 --volunteers 150 --organizations 200 --seed 123 --output output_csv_files
```

The generator validates its parameters, preserves the CSV foreign-key relationships, uses a supplied random seed for reproducibility, and does not generate real personal information.

## Validation before PR

Verify:

1. All ten CSV files have the expected header and column order.
2. Primary keys, including the composite `(user_id, cat_id)` key in `user_skills`, are unique.
3. All foreign-key values exist in their parent CSVs.
4. User and organization city/state combinations exist in `cities.csv`.
5. User and volunteer geography values parse correctly and remain near the assigned city.
6. Timestamp fields use the expected format and `created_at <= last_updated_at` where applicable.
7. Enum/boolean/numeric fields conform to the current schema.
8. No real personal or sensitive information is included.

## Testing against Issue #228

Issue #228's Organization Analytics API reads the `organizations` table and uses `org_type`, `org_size`, `state_id`, `city_name`, `org_rating`, `is_collaborator`, `is_contributor`, and the timestamp fields for dashboard analytics and filters.

For a true database-level test, load `organizations.csv` into a temporary/local PostgreSQL `organizations` table using the current schema, then run the Issue #228 tests or invoke the API functions against that local database. Do not deploy to AWS just for this mock-data validation.

## Testing against Issue #273

Issue #273 uses `users` plus a separate `volunteers` table with `application_status` and `last_updated_at`. Those columns are not part of the ten Issue #301 tables. Therefore, the Issue #301 CSV package alone cannot fully exercise the #273 query.

To test #273 locally, use `users.csv` together with a temporary `volunteers` test fixture containing `user_id`, `application_status`, and `last_updated_at` (the existing #273 test fixture already follows that shape). This verifies the actual #273 filtering, sorting, pagination, and user join without changing the Issue #301 deliverables.

## Existing database/mock_data_generation directory

The older scripts under `database/mock_data_generation` generate `volunteer_applications` and related data for a different workflow. They should remain unchanged. The three files in this directory are the Issue #301 deliverables for the ten dashboard tables.
