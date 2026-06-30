# Mock Data Generation

This folder contains the script and supporting files used to generate synthetic CSV data for selected database tables for testing and development.

## Tables generated

The script currently generates mock data for:

- `volunteer_details`
- `volunteers_assigned`

## Source input files

The script uses the following source files from this folder:

- `users.csv`
- `request.csv`
- `volunteer_applications.csv`

Additional reference files:

- `db_info.json`
- `Saayam_Table.column.names_data.xlsx` (reference only)

## Output location

Generated CSV files are written to:

`../mock_db/`

The output files are:

- `volunteer_details.csv`
- `volunteers_assigned.csv`

## Relationships maintained

The generated data preserves the required foreign key relationships:

- `volunteer_details.user_id` → `users.user_id`
- `volunteers_assigned.request_id` → `request.req_id`
- `volunteers_assigned.volunteer_id` → `users.user_id`

## Requirements

Install dependencies:

```bash
pip install pandas faker openpyxl
```
