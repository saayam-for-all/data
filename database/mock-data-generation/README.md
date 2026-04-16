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


# Mock data generation for Task 121

This implementation generates synthetic CSV data for the following tables:

* `fraud_requests`
* `notifications`

The data is generated using Python and pandas, ensuring schema consistency, realistic values, and logical relationships between fields.

---

## Script Overview

### fraud_requests.ipynb

Generates synthetic data for the `fraud_requests` table.

Responsibilities:

* Creates sequential `fraud_request_id` values
* Uses valid `user_id` values in VARCHAR format (e.g., `U101`)
* Generates realistic `request_datetime` timestamps
* Assigns fraud-related reasons from a predefined list
* Ensures correct data types and structure
* Exports data to CSV

---

### notifications.ipynb

Generates synthetic data for the `notifications` table.

Responsibilities:

* Creates sequential `notification_id` values
* Uses valid `user_id` values
* Samples `type_id` and `channel_id` from lookup tables
* Generates realistic notification messages
* Uses controlled values for `status`
* Generates `created_at` timestamps
* Ensures `last_update_date ≥ created_at`
* Maintains logical consistency across all fields
* Exports data to CSV

---

## Generated Tables

### fraud_requests

Fields:

* `fraud_request_id` (integer, primary key)
* `user_id` (character varying)
* `request_datetime` (timestamp)
* `reason` (text)

Each row represents a fraud request associated with a user.

---

### notifications

Fields:

* `notification_id` (integer)
* `user_id` (character varying)
* `type_id` (integer)
* `channel_id` (integer)
* `message` (text)
* `status` (user-defined)
* `created_at` (timestamp)
* `last_update_date` (timestamp)

Each row represents a notification event.

Key details:

* `type_id` and `channel_id` are sampled from lookup tables
* `status` uses controlled categorical values
* `last_update_date` is always greater than or equal to `created_at`
* Messages simulate real system-generated alerts

---

## Output Files

CSV files are generated in:

```
database/mock_db/
```

Generated files:

* `fraud_requests.csv` → up to 800 records
* `notifications.csv` → up to 30000 records

---

## How to Run

Open terminal in the repository root and run:

```bash
python database/mock-data-generation/generate_mock_data.py
```

---

## Notes

* Data maintains referential integrity using valid lookup values
* All timestamps follow realistic temporal relationships
* No null or invalid rows are included in final outputs
* Suitable for testing, validation, and demonstration purposes





