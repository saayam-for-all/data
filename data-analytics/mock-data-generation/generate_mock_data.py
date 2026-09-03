"""
Main driver script to generate synthetic mock CSV data for Saayam platform schema.
Outputs 10 CSV files and executes validation upon completion.
"""

import csv
import os
import random

from utils import (
    CATEGORY_NAMES,
    FIRST_NAMES,
    LAST_NAMES,
    ORG_NAMES,
    US_STATES_CITIES,
    add_seconds_to_timestamp,
    generate_timestamp,
    perturb_coordinates,
    validate_csv_data,
)


def generate_all_data(output_dir="."):
  os.makedirs(output_dir, exist_ok=True)
  print(f"Generating synthetic mock data in: {os.path.abspath(output_dir)}")

  # 1. Countries
  countries = [{"country_id": 1, "country_name": "United States", "code": "US"}]
  with open(
      os.path.join(output_dir, "countries.csv"), "w", newline="", encoding="utf-8"
  ) as f:
    writer = csv.DictWriter(
        f, fieldnames=["country_id", "country_name", "code"]
    )
    writer.writeheader()
    writer.writerows(countries)

  # 2. States
  states = []
  state_id_counter = 1
  state_lookup = {}
  for state_name, info in US_STATES_CITIES.items():
    s_rec = {
        "state_id": state_id_counter,
        "country_id": 1,
        "state_name": state_name,
        "state_code": info["code"],
        "latitude": info["lat"],
        "longitude": info["lon"],
    }
    states.append(s_rec)
    state_lookup[state_name] = state_id_counter
    state_id_counter += 1

  with open(
      os.path.join(output_dir, "states.csv"), "w", newline="", encoding="utf-8"
  ) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "state_id",
            "country_id",
            "state_name",
            "state_code",
            "latitude",
            "longitude",
        ],
    )
    writer.writeheader()
    writer.writerows(states)

  # 3. Cities
  cities = []
  city_id_counter = 1
  city_pool = []
  for state_name, info in US_STATES_CITIES.items():
    sid = state_lookup[state_name]
    for c in info["cities"]:
      c_rec = {
          "city_id": city_id_counter,
          "state_id": sid,
          "city_name": c["name"],
          "latitude": c["lat"],
          "longitude": c["lon"],
      }
      cities.append(c_rec)
      city_pool.append(c_rec)
      city_id_counter += 1

  with open(
      os.path.join(output_dir, "cities.csv"), "w", newline="", encoding="utf-8"
  ) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "city_id",
            "state_id",
            "city_name",
            "latitude",
            "longitude",
        ],
    )
    writer.writeheader()
    writer.writerows(cities)

  # 4. Users (300 records)
  users = []
  genders = ["Male", "Female", "Non-Binary", "Prefer not to say"]
  for i in range(1, 301):
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    email = f"{first.lower()}.{last.lower()}{i}@example.org"
    phone = (
        f"+1{random.randint(200,999)}{random.randint(100,999)}{random.randint(1000,9999)}"
    )
    c_at = generate_timestamp(2025)
    u_at = add_seconds_to_timestamp(c_at, 3600, 86400 * 60)
    city_ref = random.choice(city_pool)

    users.append({
        "user_id": i,
        "first_name": first,
        "last_name": last,
        "email": email,
        "phone_number": phone,
        "gender": random.choice(genders),
        "age": random.randint(18, 70),
        "profile_picture": (
            f"https://storage.saayam.org/avatars/user_{i}.jpg"
            if random.random() > 0.3
            else ""
        ),
        "is_active": True if random.random() > 0.05 else False,
        "country_id": 1,
        "state_id": city_ref["state_id"],
        "created_at": c_at,
        "updated_at": u_at,
    })

  with open(
      os.path.join(output_dir, "users.csv"), "w", newline="", encoding="utf-8"
  ) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "user_id",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "gender",
            "age",
            "profile_picture",
            "is_active",
            "country_id",
            "state_id",
            "created_at",
            "updated_at",
        ],
    )
    writer.writeheader()
    writer.writerows(users)

  # 5. Volunteer Details (~120 volunteers)
  volunteer_details = []
  v_detail_id = 1
  volunteer_user_ids = []

  for u in users:
    if u["user_id"] % 2 == 0 or u["user_id"] % 5 == 0:
      volunteer_user_ids.append(u["user_id"])
      c_at = add_seconds_to_timestamp(u["created_at"], 600, 86400 * 5)
      u_at = add_seconds_to_timestamp(c_at, 3600, 86400 * 30)

      volunteer_details.append({
          "volunteer_detail_id": v_detail_id,
          "user_id": u["user_id"],
          "bio": (
              f"Dedicated volunteer passionate about community support and"
              f" service. User #{u['user_id']}."
          ),
          "background_check_passed": True if random.random() > 0.1 else False,
          "hours_available_per_week": random.choice([5, 10, 15, 20, 25, 30]),
          "rating": round(random.uniform(3.5, 5.0), 2),
          "created_at": c_at,
          "updated_at": u_at,
      })
      v_detail_id += 1

  with open(
      os.path.join(output_dir, "volunteer_details.csv"),
      "w",
      newline="",
      encoding="utf-8",
  ) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "volunteer_detail_id",
            "user_id",
            "bio",
            "background_check_passed",
            "hours_available_per_week",
            "rating",
            "created_at",
            "updated_at",
        ],
    )
    writer.writeheader()
    writer.writerows(volunteer_details)

  # 6. Help Categories
  categories = []
  for idx, cat in enumerate(CATEGORY_NAMES, start=1):
    categories.append({
        "cat_id": idx,
        "category_name": cat,
        "description": f"Assistance and services related to {cat.lower()}.",
    })

  with open(
      os.path.join(output_dir, "help_categories.csv"),
      "w",
      newline="",
      encoding="utf-8",
  ) as f:
    writer = csv.DictWriter(
        f, fieldnames=["cat_id", "category_name", "description"]
    )
    writer.writeheader()
    writer.writerows(categories)

  # 7. User Skills
  user_skills = []
  skill_id = 1
  levels = ["Beginner", "Intermediate", "Advanced", "Expert"]
  for uid in volunteer_user_ids:
    assigned_cats = random.sample(
        range(1, len(CATEGORY_NAMES) + 1), k=random.randint(1, 3)
    )
    for cid in assigned_cats:
      user_skills.append({
          "skill_id": skill_id,
          "user_id": uid,
          "cat_id": cid,
          "proficiency_level": random.choice(levels),
          "years_experience": random.randint(1, 12),
      })
      skill_id += 1

  with open(
      os.path.join(output_dir, "user_skills.csv"),
      "w",
      newline="",
      encoding="utf-8",
  ) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "skill_id",
            "user_id",
            "cat_id",
            "proficiency_level",
            "years_experience",
        ],
    )
    writer.writeheader()
    writer.writerows(user_skills)

  # 8. Volunteer Locations
  v_locations = []
  loc_id = 1
  for vid in volunteer_user_ids:
    target_city = random.choice(city_pool)
    p_lat, p_lon = perturb_coordinates(
        target_city["latitude"], target_city["longitude"]
    )
    v_locations.append({
        "loc_id": loc_id,
        "user_id": vid,
        "latitude": p_lat,
        "longitude": p_lon,
        "is_primary": True,
        "updated_at": generate_timestamp(2026),
    })
    loc_id += 1

  with open(
      os.path.join(output_dir, "volunteer_locations.csv"),
      "w",
      newline="",
      encoding="utf-8",
  ) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "loc_id",
            "user_id",
            "latitude",
            "longitude",
            "is_primary",
            "updated_at",
        ],
    )
    writer.writeheader()
    writer.writerows(v_locations)

  # 9. User Locations
  u_locations = []
  u_loc_id = 1
  for u in users:
    target_city = random.choice(city_pool)
    p_lat, p_lon = perturb_coordinates(
        target_city["latitude"], target_city["longitude"]
    )
    u_locations.append({
        "loc_id": u_loc_id,
        "user_id": u["user_id"],
        "latitude": p_lat,
        "longitude": p_lon,
        "address_line": f"{random.randint(100, 9999)} Main St",
        "city_id": target_city["city_id"],
    })
    u_loc_id += 1

  with open(
      os.path.join(output_dir, "user_locations.csv"),
      "w",
      newline="",
      encoding="utf-8",
  ) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "loc_id",
            "user_id",
            "latitude",
            "longitude",
            "address_line",
            "city_id",
        ],
    )
    writer.writeheader()
    writer.writerows(u_locations)

  # 10. Organizations
  organizations = []
  for idx, name in enumerate(ORG_NAMES, start=1):
    c_at = generate_timestamp(2025)
    u_at = add_seconds_to_timestamp(c_at, 3600, 86400 * 20)
    organizations.append({
        "org_id": idx,
        "org_name": name,
        "contact_email": f"contact@{name.lower().replace(' ', '')}.org",
        "state_id": random.randint(1, len(US_STATES_CITIES)),
        "is_verified": True if random.random() > 0.2 else False,
        "created_at": c_at,
        "updated_at": u_at,
    })

  with open(
      os.path.join(output_dir, "organizations.csv"),
      "w",
      newline="",
      encoding="utf-8",
  ) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "org_id",
            "org_name",
            "contact_email",
            "state_id",
            "is_verified",
            "created_at",
            "updated_at",
        ],
    )
    writer.writeheader()
    writer.writerows(organizations)

  print("All 10 synthetic CSV datasets generated successfully.")

  # Execute automated validation
  validate_csv_data(output_dir)


if __name__ == "__main__":
  generate_all_data()