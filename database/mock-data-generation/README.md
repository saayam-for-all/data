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