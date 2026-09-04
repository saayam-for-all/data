# Mock Data Generation for Virginia Analytics Tables

## Purpose
Generate realistic synthetic mock data in CSV format for 10 Virginia database tables. Used for local development, API testing, dashboard testing, and demonstrations. No real or sensitive data is used.

## Tables Included
- countries
- states
- cities
- users
- volunteer_details
- user_skills
- volunteer_locations
- user_locations
- help_categories
- organizations

## Table Relationships
- users.country_id → countries.country_id
- users.state_id → states.state_id
- states.country_id → countries.country_id
- cities.state_id → states.state_id
- volunteer_details.user_id → users.user_id
- user_skills.user_id → users.user_id
- user_skills.cat_id → help_categories.cat_id
- volunteer_locations.user_id → volunteer_details.user_id
- user_locations.user_id → users.user_id
- organizations.state_id → states.state_id

## Required Dependencies
- Python 3.8+
- No external packages required (uses only csv, json, os, random, datetime from standard library)

## How to Run
```
cd data-analytics/mock-data-generation
python generate_mock_data.py
```

## Configuring Row Counts
Edit the `ROW_COUNT` variable at the top of `generate_mock_data.py`:
```python
ROW_COUNT = 400
```
Change to any value (e.g., 100, 1000, 40000). The script will generate that many rows for users, volunteer_details, user_locations, and organizations. Related tables scale accordingly.

## Output Files
All CSV files are generated in the same directory as the script:
- countries.csv
- states.csv
- cities.csv
- help_categories.csv
- users.csv
- volunteer_details.csv
- user_skills.csv
- volunteer_locations.csv
- user_locations.csv
- organizations.csv

## Geographic Data
- Coordinates in volunteer_locations and user_locations are derived from the user's assigned state/city (jittered near city centroid)
- Country → State → City → ZIP/coordinates are logically consistent
- Three countries included: United States (15 states), India (4 states), United Kingdom (1 state)

## Validation
The script ensures:
- All primary keys are unique
- All foreign key references point to valid parent records
- No orphan IDs exist
- created_at <= last_updated_at where both columns exist
- Geographic coordinates are plausible for the assigned city
- Date/timestamp values are valid PostgreSQL-compatible format
- No real names, emails, phone numbers, or sensitive data
