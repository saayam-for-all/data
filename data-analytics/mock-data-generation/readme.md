# Mock Data Generation — Virginia Analytics Tables

## Purpose
Generates realistic, fully synthetic mock data for local development, API testing,
dashboard testing, and demonstrations. No real or sensitive user data is used.
Related to issue #301.

## Tables Included
- countries
- states
- cities
- help_categories
- users
- volunteer_details
- user_skills
- user_locations
- volunteer_locations
- organizations

## Table Relationships
countries ─┬─< states ─┬─< cities
│ └─< organizations
└─< users ─┬─< volunteer_details ─< volunteer_locations
├─< user_skills >─ help_categories
└─< user_locations

`A ─< B` means "A is the parent of B" (B holds the foreign key).

## Requirements
- Python 3.10+
- [Faker](https://pypi.org/project/Faker/): `pip install faker`

## How to Run
```bash
python generate_mock_data.py
```
This generates all 10 CSV files in the current directory.

## Configuring Row Counts
Edit the constants at the top of `generate_mock_data.py`:
```python
NUM_COUNTRIES = 5
NUM_STATES = 10
NUM_CITIES = 15
NUM_CATEGORIES = 20
NUM_USERS = 100
NUM_ORGANIZATIONS = 20
VOLUNTEER_RATIO = 0.4   # fraction of users who become volunteers
```
The script is seeded (`random.seed(42)`), so re-running with the same
settings produces the same output.

## Output Location
All CSV files are written to `data-analytics/mock-data-generation/`.

## Validation
Run the validation script after generating data:
```bash
python validate_data.py
```
It checks:
- Primary key uniqueness across all tables
- No orphan foreign keys (every child row references a valid parent)
- No blank required fields

## Notes
- All data is synthetic. Names, emails, phone numbers, and addresses are
  generated with Faker and do not correspond to real people.
- `user_id` and `org_id` follow the production ID formats
  (`SID-00-XXX-XXX-XXX-XXX-XXX` and `ORG-XXX-XXX-XXX-XXXX`).