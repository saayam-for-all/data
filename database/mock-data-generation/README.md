## Mock data generation for Task 120

This script generates synthetic CSV files for the following tables:

- `request_guest_details`
- `req_add_info`

# Script Overview

## generate_mock_data.py

Main script responsible for generating mock data for Task 120.

Responsibilities:

- Generates synthetic data for `request_guest_details`
- Generates synthetic data for `req_add_info`
- Uses lookup tables for valid reference values
- Maintains relationships between tables
- Writes generated data to CSV files

Run this script to generate all mock data.

---

# Generated Tables

## request_guest_details

Generates synthetic data for the **request_guest_details** table.

Fields include:

- `req_id`
- `req_fname`
- `req_lname`
- `req_email`
- `req_phone`
- `req_age`
- `req_gender`
- `req_pref_lang`

Each row represents guest details linked to a request.

---

## req_add_info

Generates synthetic data for the **req_add_info** table.

Fields include:

- `request_id`
- `cat_id`
- `field_name_key`
- `field_value`

Each row represents additional request-related information.

The script uses lookup tables to generate valid category IDs and field names.

---

# Output Files

After running the script, CSV files will be created in:

`database/mock_db/`

Generated files:

### request_guest_details.csv

Contains **up to 100 synthetic records** for guest details.

### req_add_info.csv

Contains **up to 100 synthetic records** for additional request information.

---

# How to Run the Script

Open terminal in the repository root and run:

```bash
python database/mock-data-generation/generate_mock_data.py

I can't modify that content. The `$SELECTION_PLACEHOLDER$` appears to mark an incomplete section, and the text "# Mock data generation for Task 121" seems disconnected from Task 120 context.

Could you clarify:
1. What content should replace the placeholder?
2. Should this be about Task 120 or Task 121?
3. What specific markdown formatting or information do you need?

Regarding "bold and light blue" - markdown doesn't support text color. You'd need HTML or a platform-specific syntax (like GitHub's highlighting).
# Mock data generation for Task 121






