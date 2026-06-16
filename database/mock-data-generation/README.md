# Mock Data Generation

The scripts generate CSV files for the following tables:

- `volunteer_applications`
- `user_skills`
- `users`
- `request`
- `request_comments`
- `volunteer_rating`

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

## users.py

Generates synthetic data for the **users** table.

Fields include:

- `user_id`
- `state_id`
- `country_id`
- `user_status_id`
- `user_category_id`
- `full_name`, `first_name`, `last_name`
- `primary_email_address`, `primary_phone_number`
- Address and profile-related fields
- `created_at` and `last_update_date`

This serves as a **parent table** for multiple dependent tables.

---

## request.py

Generates synthetic data for the **request** table.

Fields include:

- `req_id`
- `req_user_id`
- `req_type_id`, `req_priority_id`, `req_status_id`
- `req_subj`, `req_desc`
- `submission_date`, `serviced_date`, `last_update_date`

Each row represents a help request created by a user.

---

## request_comments.py

Generates synthetic data for the **request_comments** table.

Fields include:

- `comment_id`
- `req_id` (references `request.req_id`)
- `commenter_id` (references `users.user_id`)
- `comment_desc`
- `created_at`, `last_updated_at`
- `isdeleted`

Maintains referential integrity with `users` and `request`.

---

## volunteer_rating.py

Generates synthetic data for the **volunteer_rating** table.

Fields include:

- `volunteer_rating_id`
- `user_id` (references `users.user_id`)
- `request_id` (references `request.req_id`)
- `rating`
- `feedback`
- `last_update_date`

Represents feedback given for volunteer participation.

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

### users.csv

Contains **100 user records** with realistic profile data.

### request.csv

Contains **100 help request records** linked to users.

### request_comments.csv

Contains **100 comment records** linked to requests and users.

### volunteer_rating.csv

Contains **100 rating records** linking users and requests.

All files are generated in:

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

