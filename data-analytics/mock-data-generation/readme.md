
# Saayam Mock Data Generation

## Purpose

This folder contains reusable scripts and synthetic CSV data for local development, API testing, dashboard testing, and demonstrations.

All generated data is synthetic. No real Saayam user, volunteer, organization, beneficiary, or sensitive information is used.

## Tables Included

The generator creates mock CSV data for the following tables:

- countries
- states
- cities
- help_categories
- users
- volunteer_details
- user_skills
- volunteer_locations
- user_locations
- organizations

## Files

```text
data-analytics/mock-data-generation/
├── generate_mock_data.py
├── utils.py
├── countries.csv
├── states.csv
├── cities.csv
├── help_categories.csv
├── users.csv
├── volunteer_details.csv
├── user_skills.csv
├── volunteer_locations.csv
├── user_locations.csv
├── organizations.csv
└── readme.md

## Requirements

Python 3 and pandas are required.

Install pandas if needed:

```bash
pip install pandas