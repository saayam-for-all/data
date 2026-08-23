# Mock Data Generation

The scripts generate CSV files for the following tables:

- `volunteer_applications`
- `user_skills`

# Scripts Overview

## generate_mock_data.py

Main script responsible for generating mock data.

Responsibilities:

- Calls table-specific data generation scripts
- Maintains relationships between tables
- Writes generated data to CSV files 

Run this script to generate all mock data.

---

## volunteer_applications.py

Generates synthetic data for the **volunteer_applications** table.

Fields include:

- `user_id`
- `terms_and_conditions`
- `terms_accepted_at`
- `govt_id_path`
- `skill_codes` (JSON array)
- `availability` (JSON object)
- `current_page`
- `application_status`
- `is_completed`
- `created_at`
- `last_updated_at`

Each row represents a volunteer application.

---

## user_skills.py

Generates data for the **user_skills** table.

This table is derived from the `skill_codes` field in `volunteer_applications`.

For each skill associated with a volunteer, a row is created.

Because volunteers may have multiple skills, this table can contain **more than 100 rows**.

---

## utils.py

Contains shared helper functions used across scripts.

Includes:

- Category ID constants
- Availability options
- Random data generators
- JSON formatting helpers
- Timestamp formatting
- CSV writing utility functions
- Random seed setup

This keeps the code modular and reusable.

---

# Output Files

After running the generator script, CSV files will be created 

Generated files:

### volunteer_applications.csv

Contains **100 volunteer application records**.

### user_skills.csv

Contains skill mappings for volunteers based on `skill_codes`.

Each skill produces a separate row.

---

# How to Run the Scripts

Open terminal in VS Code and run: python generate_mock_data.py

---

# What Happens When the Script Runs

The script will:

1. Generate **100 volunteer applications**
2. Assign **multiple skills per volunteer**
3. Create matching rows in `user_skills`
4. Maintain table relationships
5. Save CSV files in `database/mock_db`

