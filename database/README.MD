# Mock Data Generation

## Purpose

This module generates realistic synthetic mock data for Saayam database tables.

The generated data is useful for:

- Testing
- Development
- ETL validation
- Dashboard demos
- Non-production environments

No real user data is used.

---

## Input Files

Schema reference files:

- `database/Saayam_Table.column.names_data.xlsx`
- `database/mock-data-generation/db_info.json`

Lookup/reference tables:

- `database/lookup_tables/`

---

## Generated Tables

### users

References:

- state_id → state
- country_id → country
- user_status_id → user_status
- user_category_id → user_category

### request

References:

- req_user_id → users
- req_for_id → request_for
- req_islead_id → request_isleadvol
- req_cat_id → help_categories
- req_type_id → request_type
- req_priority_id → request_priority
- req_status_id → request_status

---

## Technologies Used

- Python
- Pandas
- Faker

---

## Install Dependencies

```bash
pip install pandas faker openpyxl

