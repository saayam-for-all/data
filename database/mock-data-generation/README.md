harini-anakala_120_generate_synthetic_csv
Mock Data Generation
Overview

This module generates realistic synthetic (mock) data for the Saayam database using the schema defined in db_info.json.

The script dynamically creates CSV files for all tables while ensuring:

Correct data types and formats
Realistic values (names, emails, phone numbers, etc.)
Referential integrity (foreign key relationships)
Scalability for large datasets
Features
Automatically generates data for all tables in db_info.json
Maintains primary key and foreign key relationships
Uses Faker for realistic data generation
Configurable number of records (default: 100)
Outputs CSV files to database/mock_db/
Easily extensible for new tables or schema updates
Files
File	Description
generate_data.py	Main script to generate mock data
db_info.json	Schema containing table and column definitions
mock_db/	Output folder containing generated CSV files
Requirements
Python 3.10+
Install dependencies:
pip install -r requirements.txt
Required libraries:
pandas
faker
How to Run
Activate virtual environment
# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
Navigate to the script directory
cd database/mock-data-generation
Run the script
python generate_data.py
View generated CSVs
cd ../mock_db
ls
Configuration
Default number of records per table:
NUM_RECORDS = 100
You can increase this (e.g., 40000) for large-scale testing.
Data Quality

The generated data satisfies the following:

String/Text fields: Realistic names, emails, phone numbers, addresses
Numeric fields: Reasonable ranges (e.g., age 18–80)
Date/Time fields: Valid and recent dates
Foreign Keys: Valid references across related tables
Column Relationships: Logical consistency where applicable
Adding New Tables

To generate data for new tables:

Add the table schema in db_info.json under "tables"
Ensure foreign keys reference valid tables or lookup values
Run the script again

The script will automatically generate the corresponding CSV file.

Output
One CSV file per table
Stored in:
database/mock_db/
Example files:
request_guest_details.csv
req_add_info.csv
users.csv
and others

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
5. Creates CSV files`

