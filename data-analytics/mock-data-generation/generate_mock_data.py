import random
import pandas as pd
from pathlib import Path
from datetime import timedelta

from utils import (
    random_timestamp,
    postgres_timestamp,
    make_user_id,
    make_org_id,
    make_point,
    nearby_point,
)


OUTPUT_DIR = Path(__file__).resolve().parent
ROW_COUNT = 100
VOLUNTEER_COUNT = 60
SEED = 42

random.seed(SEED)

# ---------------------------------------------------------
# COUNTRY DATA
# ---------------------------------------------------------

countries = [
    {
        "country_id": 1,
        "country_name": "United States",
        "phone_code": "+1",
        "country_code": "US",
        "last_updated_at": "2026-09-01 10:00:00",
        "is_eu_member": False,
    },
    {
        "country_id": 2,
        "country_name": "Ireland",
        "phone_code": "+353",
        "country_code": "IE",
        "last_updated_at": "2026-09-01 10:05:00",
        "is_eu_member": True,
    },
    {
        "country_id": 3,
        "country_name": "Sweden",
        "phone_code": "+46",
        "country_code": "SE",
        "last_updated_at": "2026-09-01 10:10:00",
        "is_eu_member": True,
    },
]

countries_df = pd.DataFrame(countries)

countries_df.to_csv(
    OUTPUT_DIR / "countries.csv",
    index=False
)

# ---------------------------------------------------------
# STATE DATA
# ---------------------------------------------------------

states = [
    {
        "state_id": "VA",
        "country_id": 1,
        "state_name": "Virginia",
        "state_code": "VA",
        "last_updated_at": "2026-09-01 10:20:00",
    },
    {
        "state_id": "CA",
        "country_id": 1,
        "state_name": "California",
        "state_code": "CA",
        "last_updated_at": "2026-09-01 10:25:00",
    },
    {
        "state_id": "NY",
        "country_id": 1,
        "state_name": "New York",
        "state_code": "NY",
        "last_updated_at": "2026-09-01 10:30:00",
    },
]

states_df = pd.DataFrame(states)

states_df.to_csv(
    OUTPUT_DIR / "states.csv",
    index=False
)

# ---------------------------------------------------------
# CITY DATA
# ---------------------------------------------------------

cities = [
    {
        "city_id": 1,
        "state_id": "VA",
        "city_name": "Richmond",
        "latitude": 37.540725,
        "longitude": -77.436048,
        "last_updated_at": "2026-09-01 10:40:00",
    },
    {
        "city_id": 2,
        "state_id": "CA",
        "city_name": "San Jose",
        "latitude": 37.338208,
        "longitude": -121.886329,
        "last_updated_at": "2026-09-01 10:45:00",
    },
    {
        "city_id": 3,
        "state_id": "NY",
        "city_name": "New York",
        "latitude": 40.712776,
        "longitude": -74.005974,
        "last_updated_at": "2026-09-01 10:50:00",
    },
]

cities_df = pd.DataFrame(cities)

cities_df.to_csv(
    OUTPUT_DIR / "cities.csv",
    index=False
)

# ---------------------------------------------------------
# HELP CATEGORY DATA
# ---------------------------------------------------------

help_categories = [
    {
        "cat_id": "1",
        "cat_name": "FOOD_SUPPORT",
        "cat_desc": "Support for food and meal assistance",
        "last_updated_at": "2026-09-01 11:00:00",
    },
    {
        "cat_id": "1.1",
        "cat_name": "MEAL_DELIVERY",
        "cat_desc": "Delivery of prepared meals to people in need",
        "last_updated_at": "2026-09-01 11:05:00",
    },
    {
        "cat_id": "2",
        "cat_name": "CLOTHING_SUPPORT",
        "cat_desc": "Support for clothing and essential apparel needs",
        "last_updated_at": "2026-09-01 11:10:00",
    },
    {
        "cat_id": "2.1",
        "cat_name": "DONATE_CLOTHES",
        "cat_desc": "Donation of clean and usable clothing items",
        "last_updated_at": "2026-09-01 11:15:00",
    },
]

help_categories_df = pd.DataFrame(help_categories)

help_categories_df.to_csv(
    OUTPUT_DIR / "help_categories.csv",
    index=False
)

# ---------------------------------------------------------
# USER DATA
# ---------------------------------------------------------

users = []

user_locations_seed = [
    ("VA", 1, "Richmond", "23219", 37.540725, -77.436048, "America/New_York"),
    ("CA", 1, "San Jose", "95113", 37.338208, -121.886329, "America/Los_Angeles"),
    ("NY", 1, "New York", "10001", 40.712776, -74.005974, "America/New_York"),
]

first_names = ["Aarav", "Maya", "Liam", "Emma", "Noah", "Sophia"]
last_names = ["Sharma", "Patel", "Brown", "Davis", "Wilson", "Taylor"]

for i in range(1, ROW_COUNT + 1):
    state_id, country_id, city_name, zip_code, latitude, longitude, time_zone = random.choice(
    user_locations_seed
)

    first_name = random.choice(first_names)
    last_name = random.choice(last_names)
    full_name = f"{first_name} {last_name}"

    created_time = random_timestamp()
    updated_time = created_time + timedelta(
        days=random.randint(0, 30)
    )

    users.append(
        {
            "user_id": make_user_id(i),
            "state_id": state_id,
            "country_id": country_id,
            "user_status_id": None,
            "full_name": full_name,
            "first_name": first_name,
            "middle_name": None,
            "last_name": last_name,
            "primary_email_address": f"user{i}@example.test",
            "primary_phone_number": f"+1555{i:07d}",
            "addr_ln1": f"{100 + i} Example Street",
            "addr_ln2": None,
            "addr_ln3": None,
            "city_name": city_name,
            "zip_code": zip_code,
            "last_location": f"({longitude},{latitude})",
            "last_updated_at": postgres_timestamp(updated_time),
            "time_zone": time_zone,
            "profile_picture_path": None,
            "gender": random.choice(["Male", "Female", "Other"]),
            "language_1": None,
            "language_2": None,
            "language_3": None,
            "promotion_wizard_stage": random.randint(0, 5),
            "promotion_wizard_last_updated_at": postgres_timestamp(updated_time),
            "external_auth_provider": None,
            "dob": f"{random.randint(1970, 2002)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
            "is_eu": False,
        }
    )

users_df = pd.DataFrame(users)

users_df.to_csv(
    OUTPUT_DIR / "users.csv",
    index=False
)

# ---------------------------------------------------------
# VOLUNTEER DETAILS DATA
# ---------------------------------------------------------

volunteer_details = []

# Use a subset of users as volunteers
volunteer_user_ids = users_df["user_id"].sample(
    n=min(VOLUNTEER_COUNT, len(users_df)),
    random_state=SEED
).tolist()

for user_id in volunteer_user_ids:
    created_time = random_timestamp()
    updated_time = created_time + timedelta(days=random.randint(0, 20))

    terms_accepted = random.choice([True, False])

    volunteer_details.append(
        {
            "user_id": user_id,
            "terms_and_conditions": terms_accepted,
            "terms_accepted_at": (
                postgres_timestamp(created_time)
                if terms_accepted
                else None
            ),
            "govt_id_path1": None,
            "govt_id_path2": None,
            "path1_updated_at": None,
            "path2_updated_at": None,
            "availability_days": random.choice(
                [
                    '["Monday","Wednesday","Friday"]',
                    '["Tuesday","Thursday"]',
                    '["Saturday","Sunday"]',
                    '["Monday","Tuesday","Wednesday","Thursday","Friday"]',
                ]
            ),
            "availability_times": random.choice(
                [
                    '{"start":"09:00","end":"13:00"}',
                    '{"start":"13:00","end":"17:00"}',
                    '{"start":"09:00","end":"17:00"}',
                    '{"start":"18:00","end":"21:00"}',
                ]
            ),
            "created_at": postgres_timestamp(created_time),
            "last_updated_at": postgres_timestamp(updated_time),
        }
    )

volunteer_details_df = pd.DataFrame(volunteer_details)

volunteer_details_df.to_csv(
    OUTPUT_DIR / "volunteer_details.csv",
    index=False
)

# ---------------------------------------------------------
# USER SKILLS DATA
# ---------------------------------------------------------

skill_levels = [
    "BEGINNER",
    "INTERMEDIATE",
    "ADVANCED",
    "EXPERT",
]

user_skills = []

user_ids = users_df["user_id"].tolist()
category_ids = help_categories_df["cat_id"].astype(str).tolist()

for _ in range(ROW_COUNT):
  user_skills = []

user_ids = users_df["user_id"].tolist()
category_ids = help_categories_df["cat_id"].astype(str).tolist()

used_pairs = set()

while len(user_skills) < ROW_COUNT:
    user_id = random.choice(user_ids)
    cat_id = random.choice(category_ids)

    pair = (user_id, cat_id)

    if pair in used_pairs:
        continue

    used_pairs.add(pair)

    created_time = random_timestamp()
    updated_time = created_time + timedelta(days=random.randint(0, 20))

    user_skills.append(
        {
            "user_id": user_id,
            "cat_id": cat_id,
            "skill_level": random.choice(skill_levels),
            "created_at": postgres_timestamp(created_time),
            "last_updated_at": postgres_timestamp(updated_time),
        }
    )

user_skills_df = pd.DataFrame(user_skills)

user_skills_df.to_csv(
    OUTPUT_DIR / "user_skills.csv",
    index=False
)

# ---------------------------------------------------------
# VOLUNTEER LOCATIONS DATA
# ---------------------------------------------------------

volunteer_locations = []

users_lookup = users_df.set_index("user_id")

for user_id in volunteer_user_ids:
    user_row = users_lookup.loc[user_id]

    city_name = user_row["city_name"]

    if city_name == "Richmond":
        latitude = 37.540725
        longitude = -77.436048
    elif city_name == "San Jose":
        latitude = 37.338208
        longitude = -121.886329
    else:
        latitude = 40.712776
        longitude = -74.005974

    curr_loc = nearby_point(longitude, latitude)
    prev_loc = nearby_point(longitude, latitude)

    updated_time = random_timestamp()

    volunteer_locations.append(
        {
            "user_id": user_id,
            "prev_loc": prev_loc,
            "curr_loc": curr_loc,
            "last_updated_at": postgres_timestamp(updated_time),
        }
    )

volunteer_locations_df = pd.DataFrame(volunteer_locations)

volunteer_locations_df.to_csv(
    OUTPUT_DIR / "volunteer_locations.csv",
    index=False
)

# ---------------------------------------------------------
# USER LOCATIONS DATA
# ---------------------------------------------------------

user_locations = []

for _, user_row in users_df.iterrows():
    user_id = user_row["user_id"]
    city_name = user_row["city_name"]

    if city_name == "Richmond":
        latitude = 37.540725
        longitude = -77.436048
    elif city_name == "San Jose":
        latitude = 37.338208
        longitude = -121.886329
    else:
        latitude = 40.712776
        longitude = -74.005974

    curr_loc = nearby_point(longitude, latitude)
    prev_loc = nearby_point(longitude, latitude)

    updated_time = random_timestamp()

    user_locations.append(
        {
            "user_id": user_id,
            "prev_loc": prev_loc,
            "curr_loc": curr_loc,
            "last_updated_at": postgres_timestamp(updated_time),
        }
    )

user_locations_df = pd.DataFrame(user_locations)

user_locations_df.to_csv(
    OUTPUT_DIR / "user_locations.csv",
    index=False
)

# ---------------------------------------------------------
# ORGANIZATION DATA
# ---------------------------------------------------------

organizations = []

organization_names = [
    "Community Care Network",
    "Helping Hands Foundation",
    "Bright Future Initiative",
    "Neighborhood Support Alliance",
    "CareBridge Services",
    "HopeWorks Foundation",
]

org_types = ["non_profit", "for_profit"]
org_sizes = ["small", "medium", "large"]

organization_locations = [
    ("VA", "Richmond", "23219"),
    ("CA", "San Jose", "95113"),
    ("NY", "New York", "10001"),
]

for i in range(1, ROW_COUNT + 1):
    state_id, city_name, zip_code = random.choice(
        organization_locations
    )

    org_name = f"{random.choice(organization_names)} {i}"

    created_time = random_timestamp()
    updated_time = created_time + timedelta(
        days=random.randint(0, 30)
    )

    organizations.append(
        {
            "org_id": make_org_id(i),
            "org_name": org_name,
            "street": f"{200 + i} Community Avenue",
            "city_name": city_name,
            "state_id": state_id,
            "zip_code": zip_code,
            "mission": "Provide community support and connect people with local resources.",
            "web_url": f"https://example-org-{i}.test",
            "phone": f"+1556{i:07d}",
            "email": f"contact{i}@example-org.test",
            "org_type": random.choice(org_types),
            "org_size": random.choice(org_sizes),
            "org_rating": random.randint(1, 5),
            "is_collaborator": random.choice([True, False]),
            "is_contributor": random.choice([True, False]),
            "created_at": postgres_timestamp(created_time),
            "last_updated_at": postgres_timestamp(updated_time),
        }
    )

organizations_df = pd.DataFrame(organizations)

organizations_df.to_csv(
    OUTPUT_DIR / "organizations.csv",
    index=False
)