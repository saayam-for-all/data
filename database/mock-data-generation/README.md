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


---

# 🔹 Additional Contribution (#119): request_comments & volunteer_rating

## Overview
This module extends the mock data generation to include:

- `request_comments`
- `volunteer_rating`

These tables simulate user interactions such as comments on requests and volunteer feedback ratings.

---

## Script: generate_request_data.py

This script generates synthetic data for:

### request_comments
Fields:
- `comment_id` (Primary Key)
- `req_id` (Foreign Key → request)
- `commenter_id` (Foreign Key → users)
- `comment_desc`
- `created_at`
- `last_updated_at`
- `isdeleted`

---

### volunteer_rating
Fields:
- `volunteer_rating_id` (Primary Key)
- `user_id` (Foreign Key → users)
- `request_id` (Foreign Key → request)
- `rating` (Enum: 1–5)
- `feedback`
- `last_update_date`

---

## Features
- Generates realistic text using Faker
- Maintains referential integrity for user_id and request_id
- Ensures logical timestamp ordering (created_at ≤ last_updated_at)
- Supports boolean and enum fields
- Easily scalable for large datasets

---

## How to Run

Navigate to: database/mock-data-generation
Run : python generate_request_data.py

---

## output Files:

Genereated files will be in :
database/mock_db/


Files:
- `request_comments.csv`
- `volunteer_rating.csv`

---

## Notes
- Currently generates 100 rows per table (as per acceptance criteria)
- Can be scaled to 40,000+ rows by adjusting configuration
- Data structure follows schema defined in `db_info.json`
