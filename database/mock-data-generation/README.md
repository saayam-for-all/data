# Mock Data Generation

## Objective
Generate synthetic/mock CSV data for database tables for testing, development, and demo purposes.

## Project Files
- generate_data.py -> main generation script
- db_info.json -> schema metadata
- lookup_tables/ -> reference CSV files
- mock_db/ -> generated CSV outputs

## Features
- Generates one CSV per table
- Uses schema from db_info.json
- Loads lookup/reference data first
- Preserves foreign key relationships
- Custom generation for users and request tables

## Run

```bash
python generate_data.py
Last updated for PR submission.