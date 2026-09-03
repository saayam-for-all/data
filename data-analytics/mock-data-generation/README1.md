# Synthetic Mock Data Generation & Validation Engine

## Overview
This module provides automated generation and validation of synthetic CSV datasets modeled after the Saayam platform relational database schema. The generated datasets enable local development, API integration testing, ETL pipeline testing, and spatial analytics benchmarking without requiring production database connections or real user PII.

---

## Directory Structure
data-analytics/mock-data-generation/
├── utils.py               # Reference geographic/lookup data, timestamp/coord helpers, and validation engine
├── generate_mock_data.py  # Main execution script generating 10 CSV files
├── README1.md             # Documentation and execution guide
├── countries.csv          # Country lookup table
├── states.csv             # State geographical data
├── cities.csv             # City centroid coordinates
├── users.csv              # User account demographic records
├── volunteer_details.csv  # Volunteer verification, ratings, and availability
├── help_categories.csv    # Skill and help category taxonomies
├── user_skills.csv        # User skill mappings and experience levels
├── volunteer_locations.csv# High-precision clustered location points for volunteers
├── user_locations.csv     # Base addresses and coordinates for general users
└── organizations.csv      # Partner and NGO organization records

---

## Key Features & Constraints
* **Primary Key Uniqueness**: All primary keys are strictly unique across all tables.
* **Referential Integrity**: 100% foreign key matching across parent and child tables (`states` -> `countries`, `cities` -> `states`, `users` -> `states`/`countries`, `volunteer_details` -> `users`, `volunteer_locations` -> `volunteer_details`, `user_skills` -> `help_categories`).
* **Timestamp Consistency**: Guaranteed logical sequencing where `created_at` <= `updated_at`.
* **Spatial Clustering**: Geographic coordinates are offset relative to real city centroids (using standard spherical approximation) to model realistic service coverage areas (~10–15 km radius).

---

## Execution Guide

### 1. Generate Datasets and Run Validation
To regenerate all 10 CSV datasets and run automated verification checks:

python generate_mock_data.py

### 2. Standalone Validation
To run validation independently on existing CSV files in the folder:

from utils import validate_csv_data
validate_csv_data(".")

---

## Generated Schemas Summary

| File Name | Row Count | Primary Key | Key Foreign Keys |
| :--- | :--- | :--- | :--- |
| countries.csv | 1 | country_id | — |
| states.csv | 5 | state_id | country_id |
| cities.csv | 25 | city_id | state_id |
| users.csv | 300 | user_id | country_id, state_id |
| volunteer_details.csv | ~180 | volunteer_detail_id | user_id |
| help_categories.csv | 8 | cat_id | — |
| user_skills.csv | ~380 | skill_id | user_id, cat_id |
| volunteer_locations.csv | ~180 | loc_id | user_id (volunteer_details) |
| user_locations.csv | 300 | loc_id | user_id, city_id |
| organizations.csv | 8 | org_id | state_id |