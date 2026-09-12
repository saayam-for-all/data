# Saayam Mock Data Generation

This directory contains reusable synthetic data generation utilities for the
Virginia Saayam database tables used by Data Analytics.

The generated data is intended for:

- local development
- API testing
- dashboard testing
- demonstrations

No real user information is used.

## Tables

The generator creates one CSV for each of the following tables:

- countries
- states
- cities
- users
- volunteer_details
- user_skills
- volunteer_locations
- user_locations
- help_categories
- organizations

## Source Schema

The generator follows the latest Virginia database schema documented in the
Saayam database repository.

The current pluralized table names `countries`, `states`, and `cities` are used.

The `cities` table currently contains the schema column `lattitude`. The
spelling is retained intentionally so that the generated CSV header matches the
database schema exactly.

## Requirements

Python 3.10 or later is recommended.

No third-party Python packages are required.

## Generate Mock Data

From this directory run:

```bash
python generate_mock_data.py
