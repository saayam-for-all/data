# Mock Data Generation

This directory contains scripts for generating synthetic CSV data for the Saayam database.

## Scripts

### generate_mock_data.py
Generates synthetic volunteer application and user skill data.

### volunteer_applications.py
Generates volunteer application records, including skill codes, availability, application status, and timestamps.

### user_skills.py
Generates user skill records derived from volunteer applications.

### generate_requests_mock_data.py
Generates synthetic data for the `users` and `requests` tables.

The script reads lookup values from `database/lookup_tables/` and generates:
- `users.csv` — 150 synthetic user records.
- `requests.csv` — 100 synthetic request records.

It creates unique IDs, maintains user references, uses existing lookup IDs, and generates request details, timestamps, and synthetic location coordinates.

A fixed random seed (`42`) makes the generated data reproducible.

### utils.py
Contains shared helper functions.

## How to Run

Run these commands from this directory:

Generate volunteer application and user skill data:

    python generate_mock_data.py

Generate request and user data:

    python generate_requests_mock_data.py

## Output

Generated CSV files are written to `output_csv_files/`.

This directory is excluded from Git because the data can be regenerated using the scripts.
