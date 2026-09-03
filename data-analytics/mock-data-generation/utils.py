"""
Utility functions for synthetic mock data generation and validation for Saayam database schema.
"""

import csv
from datetime import datetime, timedelta
import os
import random

# Reference lookup data for logical geographic clustering
US_STATES_CITIES = {
    "California": {
        "code": "CA",
        "lat": 36.7783,
        "lon": -119.4179,
        "cities": [
            {"name": "San Jose", "lat": 37.3382, "lon": -121.8863},
            {"name": "San Francisco", "lat": 37.7749, "lon": -122.4194},
            {"name": "Los Angeles", "lat": 34.0522, "lon": -118.2437},
            {"name": "San Diego", "lat": 32.7157, "lon": -117.1611},
            {"name": "Sacramento", "lat": 38.5816, "lon": -121.4944},
        ],
    },
    "New York": {
        "code": "NY",
        "lat": 40.7128,
        "lon": -74.0060,
        "cities": [
            {"name": "New York City", "lat": 40.7128, "lon": -74.0060},
            {"name": "Buffalo", "lat": 42.8864, "lon": -78.8784},
            {"name": "Rochester", "lat": 43.1566, "lon": -77.6088},
            {"name": "Albany", "lat": 42.6526, "lon": -73.7562},
            {"name": "Syracuse", "lat": 43.0481, "lon": -76.1474},
        ],
    },
    "Texas": {
        "code": "TX",
        "lat": 31.9686,
        "lon": -99.9018,
        "cities": [
            {"name": "Houston", "lat": 29.7604, "lon": -95.3698},
            {"name": "Austin", "lat": 30.2672, "lon": -97.7431},
            {"name": "Dallas", "lat": 32.7767, "lon": -96.7970},
            {"name": "San Antonio", "lat": 29.4241, "lon": -98.4936},
            {"name": "Fort Worth", "lat": 32.7555, "lon": -97.3308},
        ],
    },
    "New Jersey": {
        "code": "NJ",
        "lat": 40.0583,
        "lon": -74.4057,
        "cities": [
            {"name": "Jersey City", "lat": 40.7178, "lon": -74.0431},
            {"name": "Newark", "lat": 40.7357, "lon": -74.1724},
            {"name": "Hoboken", "lat": 40.7440, "lon": -74.0324},
            {"name": "Paterson", "lat": 40.9168, "lon": -74.1718},
            {"name": "Trenton", "lat": 40.2170, "lon": -74.7429},
        ],
    },
    "Florida": {
        "code": "FL",
        "lat": 27.6648,
        "lon": -81.5158,
        "cities": [
            {"name": "Miami", "lat": 25.7617, "lon": -80.1918},
            {"name": "Orlando", "lat": 28.5383, "lon": -81.3792},
            {"name": "Tampa", "lat": 27.9506, "lon": -82.4572},
            {"name": "Jacksonville", "lat": 30.3322, "lon": -81.6557},
            {"name": "Tallahassee", "lat": 30.4383, "lon": -84.2807},
        ],
    },
}

FIRST_NAMES = [
    "Aarav",
    "Ananya",
    "Liam",
    "Emma",
    "Noah",
    "Olivia",
    "Ethan",
    "Sophia",
    "Raj",
    "Priya",
    "Carlos",
    "Isabella",
    "Marcus",
    "Maya",
    "Rohan",
    "Sana",
    "David",
    "Zara",
    "Alex",
    "Chloe",
]
LAST_NAMES = [
    "Thakkar",
    "Desai",
    "Patel",
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Rodriguez",
    "Martinez",
    "Hernandez",
    "Lopez",
    "Gonzalez",
    "Wilson",
    "Anderson",
    "Thomas",
    "Taylor",
]

CATEGORY_NAMES = [
    "Food Assistance",
    "Medical Support",
    "Educational Tutoring",
    "Emergency Transport",
    "Disaster Relief",
    "Elderly Care",
    "Community Shelter",
    "Tech Support",
]

ORG_NAMES = [
    "Saayam Hope Foundation",
    "Global Relief Network",
    "Community Food Basket",
    "Youth Empowerment Alliance",
    "Elder Care Helpers",
    "Clean Ocean Initiative",
    "Bright Future Tutors",
    "Apex Health Volunteers",
]


def generate_timestamp(start_year=2025):
  """Generates a random PostgreSQL-compatible timestamp string."""
  start = datetime(start_year, 1, 1, 0, 0, 0)
  end = datetime(2026, 8, 30, 23, 59, 59)
  delta = end - start
  random_seconds = random.randint(0, int(delta.total_seconds()))
  dt = start + timedelta(seconds=random_seconds)
  return dt.strftime("%Y-%m-%d %H:%M:%S")


def add_seconds_to_timestamp(
    ts_str, min_seconds=3600, max_seconds=86400 * 30
):
  """Derives a logically later timestamp enforcing created_at <= updated_at."""
  dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
  dt += timedelta(seconds=random.randint(min_seconds, max_seconds))
  if dt > datetime(2026, 8, 31, 23, 59, 59):
    dt = datetime(2026, 8, 31, 23, 59, 59)
  return dt.strftime("%Y-%m-%d %H:%M:%S")


def perturb_coordinates(lat, lon, max_offset_km=15.0):
  """Generates realistic coordinates clustered near a city's centroid."""
  lat_offset = (random.uniform(-max_offset_km, max_offset_km)) / 111.0
  lon_offset = (random.uniform(-max_offset_km, max_offset_km)) / (
      111.0 * max(0.2, abs(round(lat / 90.0, 2)))
  )
  return round(lat + lat_offset, 6), round(lon + lon_offset, 6)


def validate_csv_data(output_dir):
  """Validates schema, primary keys, referential integrity, and timestamp logic across generated CSV files."""
  print("\n" + "=" * 60)
  print("STARTING COMPREHENSIVE MOCK DATA INTEGRITY VALIDATION")
  print("=" * 60)

  files = [f for f in os.listdir(output_dir) if f.endswith(".csv")]
  data = {}
  for f in files:
    filepath = os.path.join(output_dir, f)
    with open(filepath, mode="r", encoding="utf-8") as file:
      reader = csv.DictReader(file)
      data[f] = list(reader)

  errors = []

  def get_ids(filename, key):
    return {row[key] for row in data[filename]}

  # 1. Primary Key Uniqueness Check
  pk_map = {
      "countries.csv": "country_id",
      "states.csv": "state_id",
      "cities.csv": "city_id",
      "users.csv": "user_id",
      "volunteer_details.csv": "volunteer_detail_id",
      "user_skills.csv": "skill_id",
      "volunteer_locations.csv": "loc_id",
      "user_locations.csv": "loc_id",
      "help_categories.csv": "cat_id",
      "organizations.csv": "org_id",
  }

  for fname, pk in pk_map.items():
    if fname in data:
      rows = data[fname]
      pks = [r[pk] for r in rows]
      if len(pks) != len(set(pks)):
        errors.append(
            f"Duplicate primary keys found in {fname} for column {pk}."
        )
      else:
        print(
            f"[PASS] Primary key uniqueness verified for {fname} ({len(pks)}"
            " rows)."
        )

  # 2. Foreign Key Integrity Checks
  countries_ids = get_ids("countries.csv", "country_id")
  states_ids = get_ids("states.csv", "state_id")
  users_ids = get_ids("users.csv", "user_id")
  v_details_ids = get_ids("volunteer_details.csv", "user_id")
  cats_ids = get_ids("help_categories.csv", "cat_id")

  for r in data["states.csv"]:
    if r["country_id"] not in countries_ids:
      errors.append(f"Orphan country_id {r['country_id']} in states.csv")

  for r in data["cities.csv"]:
    if r["state_id"] not in states_ids:
      errors.append(f"Orphan state_id {r['state_id']} in cities.csv")

  for r in data["users.csv"]:
    if r["country_id"] not in countries_ids:
      errors.append(f"Orphan country_id {r['country_id']} in users.csv")
    if r["state_id"] not in states_ids:
      errors.append(f"Orphan state_id {r['state_id']} in users.csv")

  for r in data["volunteer_details.csv"]:
    if r["user_id"] not in users_ids:
      errors.append(f"Orphan user_id {r['user_id']} in volunteer_details.csv")

  for r in data["user_skills.csv"]:
    if r["user_id"] not in users_ids:
      errors.append(f"Orphan user_id {r['user_id']} in user_skills.csv")
    if r["cat_id"] not in cats_ids:
      errors.append(f"Orphan cat_id {r['cat_id']} in user_skills.csv")

  for r in data["volunteer_locations.csv"]:
    if r["user_id"] not in v_details_ids:
      errors.append(
          f"Orphan volunteer user_id {r['user_id']} in volunteer_locations.csv"
          " (must exist in volunteer_details)"
      )

  for r in data["user_locations.csv"]:
    if r["user_id"] not in users_ids:
      errors.append(f"Orphan user_id {r['user_id']} in user_locations.csv")

  for r in data["organizations.csv"]:
    if r["state_id"] not in states_ids:
      errors.append(f"Orphan state_id {r['state_id']} in organizations.csv")

  # 3. Timestamp Sanity
  for fname, rows in data.items():
    for i, r in enumerate(rows):
      if "created_at" in r and "updated_at" in r and r["updated_at"]:
        c_at = datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S")
        u_at = datetime.strptime(r["updated_at"], "%Y-%m-%d %H:%M:%S")
        if c_at > u_at:
          errors.append(
              f"Timestamp anomaly in {fname} at row {i+1}: created_at ({c_at})"
              f" > updated_at ({u_at})"
          )

  if not errors:
    print("=" * 60)
    print("ALL VALIDATION CHECKS PASSED SUCCESSFULLY! ZERO ERRORS.")
    print("=" * 60)
    return True
  else:
    print("Validation errors encountered:")
    for err in errors:
      print(f" - {err}")
    return False