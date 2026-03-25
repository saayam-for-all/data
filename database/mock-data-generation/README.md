# Mock Data Generation
The scripts generate CSV files for the following tables:
- `volunteer_applications`
- `user_skills`
- `request_comments`
- `volunteer_rating`
# Scripts Overview
## generate_mock_data.py
Main script responsible for generating mock data for volunteer_applications and user_skills.
Responsibilities:
- Calls table-specific data generation scripts
- Maintains relationships between tables
- Writes generated data to CSV files
Run this script to generate volunteer_applications and user_skills mock data.
---
## generate_comments_and_ratings.py
Generates mock data for request_comments and volunteer_rating tables.
Responsibilities:
- Generates shared user IDs and request IDs for foreign key consistency
- Calls request_comments and volunteer_rating generators
- Writes generated data to CSV files
Run this script to generate request_comments and volunteer_rating mock data.
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
Generates data for the user_skills table.
This table is derived from the skill_codes field in volunteer_applications.
For each skill associated with a volunteer, a row is created.
Because volunteers may have multiple skills, this table can contain more than 100 rows.

---
## request_comments.py
Generates synthetic data for the **request_comments** table.
Fields include:
- `comment_id` (primary key)
- `req_id` (foreign key to request table)
- `commenter_id` (foreign key to users table)
- `comment_desc`
- `created_at`
- `last_updated_at`
- `isdeleted`
Each row represents a comment left on a help request.
---
## volunteer_rating.py
Generates synthetic data for the **volunteer_rating** table.
Fields include:
- `volunteer_rating_id` (primary key)
- `user_id` (foreign key to users table)
- `request_id` (foreign key to request table)
- `rating` (enum, 1-5)
- `feedback`
- `last_update_date`
Each row represents a rating given to a volunteer after a help request is handled.
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
After running the generator scripts, CSV files will be created in the output_csv_files folder.
Generated files:
### volunteer_applications.csv
Contains **100 volunteer application records**.
### user_skills.csv
Contains skill mappings for volunteers based on `skill_codes`.
Each skill produces a separate row.
### request_comments.csv
Contains **100 request comment records**.
### volunteer_rating.csv
Contains **100 volunteer rating records**.
---
# How to Run the Scripts
Open terminal in VS Code and run:
- For volunteer_applications and user_skills: `python generate_mock_data.py`
- For request_comments and volunteer_rating: `python generate_comments_and_ratings.py`
---
# What Happens When the Scripts Run
generate_mock_data.py will:
1. Generate **100 volunteer applications**
2. Assign **multiple skills per volunteer**
3. Create matching rows in `user_skills`
4. Maintain table relationships
5. Create CSV files
generate_comments_and_ratings.py will:
1. Generate **100 shared user IDs and request IDs**
2. Generate **100 request comments** linked to those users and requests
3. Generate **100 volunteer ratings** linked to those users and requests
4. Maintain foreign key relationships
5. Create CSV files
