import os
import csv
import random
from faker import Faker

from utils import generate_user_id, generate_org_id, generate_state_id, random_point_near, random_timestamp

fake = Faker()
random.seed(42)
Faker.seed(42)

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

COUNTRIES = [
    {"country_name": "United States", "phone_code": "+1", "country_code": "US", "is_eu_member": False},
    {"country_name": "India", "phone_code": "+91", "country_code": "IN", "is_eu_member": False},
    {"country_name": "Ireland", "phone_code": "+353", "country_code": "IE", "is_eu_member": True},
]

COUNTRY_CENTERS = {
    "US": (39.8, -98.5),
    "IN": (22.0, 79.0),
    "IE": (53.4, -8.2),
}

HELP_CATEGORY_TREE = {
    "1": ("Food & Essentials", "Help with food, groceries, and daily essentials"),
    "1.1": ("Grocery Delivery", "Delivering groceries to those in need"),
    "1.2": ("Cooking Help", "Meal preparation and cooking assistance"),
    "2": ("Shelter", "Housing and shelter-related assistance"),
    "2.1": ("Temporary Housing", "Short-term shelter arrangements"),
    "3": ("Healthcare", "Medical and health-related support"),
    "3.1": ("Medication Pickup", "Picking up prescriptions"),
}

def write_csv(filename, fieldnames, rows):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {path}")


def build_countries():
    rows = []
    for i, c in enumerate(COUNTRIES, start=1):
        rows.append({
            "country_id": i,
            "country_name": c["country_name"],
            "phone_code": c["phone_code"],
            "country_code": c["country_code"],
            "last_updated_at": random_timestamp(fake),
            "is_eu_member": c["is_eu_member"],
        })
    return rows

def build_states(countries):
    rows = []
    state_lookup = []
    for country in countries:
        cc = country["country_code"]
        for i in range(1, 4 + 1):
            state_id = generate_state_id(cc, i)
            rows.append({
                "state_id": state_id,
                "country_id": country["country_id"],
                "state_name": fake.state() if cc == "US" else f"{fake.city()} Region",
                "state_code": fake.lexify(text="??").upper(),
                "last_updated_at": random_timestamp(fake),
            })
            state_lookup.append((state_id, country["country_id"], cc))
    return rows, state_lookup

def build_cities(state_lookup):
    rows = []
    city_lookup = []
    city_id = 1
    for state_id, country_id, cc in state_lookup:
        center_lat, center_lon = COUNTRY_CENTERS[cc]
        for _ in range(4):
            lat, lon = random_point_near(center_lat, center_lon, spread=3.0)
            rows.append({
                "city_id": city_id,
                "state_id": state_id,
                "city_name": fake.city()[:30],
                "lattitude": lat,
                "longitude": lon,
                "last_updated_at": random_timestamp(fake),
            })
            city_lookup.append((city_id, state_id, cc))
            city_id += 1
    return rows, city_lookup

def build_users(countries, state_lookup):
    rows = []
    user_ids = []
    genders = ["Male", "Female", "Non-binary", "Prefer not to say"]

    for seq in range(1, 100 + 1):
        user_id = generate_user_id(seq)
        country = random.choice(countries)
        matching_states = [s for s in state_lookup if s[1] == country["country_id"]]
        state_id, _, _ = random.choice(matching_states)

        first = fake.first_name()
        last = fake.last_name()

        rows.append({
            "user_id": user_id,
            "state_id": state_id,
            "country_id": country["country_id"],
            "full_name": f"{first} {last}",
            "first_name": first,
            "last_name": last,
            "primary_email_address": fake.unique.email(),
            "primary_phone_number": fake.phone_number()[:20],
            "city_name": fake.city(),
            "zip_code": fake.postcode(),
            "last_updated_at": random_timestamp(fake),
            "gender": random.choice(genders),
            "dob": fake.date_of_birth(minimum_age=18, maximum_age=80).isoformat(),
            "is_eu": country["is_eu_member"],
        })
        user_ids.append(user_id)
    return rows, user_ids

def build_volunteer_details(user_ids):
    rows = []
    volunteer_ids = random.sample(user_ids, int(len(user_ids) * 0.4))
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    for uid in volunteer_ids:
        created = random_timestamp(fake)
        rows.append({
            "user_id": uid,
            "terms_and_conditions": True,
            "terms_accepted_at": created,
            "availability_days": str(random.sample(days, k=random.randint(1, 4))).replace("'", '"'),
            "created_at": created,
            "last_updated_at": created,
        })
    return rows, volunteer_ids

def build_user_locations(users_rows, countries):
    country_by_id = {c["country_id"]: c["country_code"] for c in countries}
    rows = []
    for u in users_rows:
        cc = country_by_id[u["country_id"]]
        center_lat, center_lon = COUNTRY_CENTERS[cc]
        prev_lat, prev_lon = random_point_near(center_lat, center_lon, spread=2.0)
        curr_lat, curr_lon = random_point_near(center_lat, center_lon, spread=2.0)
        rows.append({
            "user_id": u["user_id"],
            "prev_loc": f"POINT({prev_lon} {prev_lat})",
            "curr_loc": f"POINT({curr_lon} {curr_lat})",
            "last_updated_at": random_timestamp(fake),
        })
    return rows

def build_volunteer_locations(volunteer_ids, users_by_id, countries):
    country_by_id = {c["country_id"]: c["country_code"] for c in countries}
    rows = []
    for uid in volunteer_ids:
        cc = country_by_id[users_by_id[uid]["country_id"]]
        center_lat, center_lon = COUNTRY_CENTERS[cc]
        prev_lat, prev_lon = random_point_near(center_lat, center_lon, spread=2.0)
        curr_lat, curr_lon = random_point_near(center_lat, center_lon, spread=2.0)
        rows.append({
            "user_id": uid,
            "prev_loc": f"POINT({prev_lon} {prev_lat})",
            "curr_loc": f"POINT({curr_lon} {curr_lat})",
            "last_updated_at": random_timestamp(fake),
        })
    return rows

def build_help_categories():
    rows = []
    for cat_id, (name, desc) in HELP_CATEGORY_TREE.items():
        rows.append({
            "cat_id": cat_id,
            "cat_name": name,
            "cat_desc": desc,
            "last_updated_at": random_timestamp(fake),
        })
    return rows

def build_user_skills(volunteer_ids):
    rows = []
    cat_ids = list(HELP_CATEGORY_TREE.keys())
    skill_levels = ["BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"]
    seen_pairs = set()

    for uid in volunteer_ids:
        n_skills = random.randint(1, 3)
        chosen_cats = random.sample(cat_ids, n_skills)
        for cat_id in chosen_cats:
            if (uid, cat_id) in seen_pairs:
                continue
            seen_pairs.add((uid, cat_id))
            created = random_timestamp(fake)
            rows.append({
                "user_id": uid,
                "cat_id": cat_id,
                "skill_level": random.choice(skill_levels),
                "created_at": created,
                "last_updated_at": created,
            })
    return rows

def build_organizations(state_lookup):
    rows = []
    org_types = ["non_profit", "for_profit"]
    org_sizes = ["small", "medium", "large"]

    for seq in range(1, 15 + 1):
        org_id = generate_org_id(seq)
        state_id, _, _ = random.choice(state_lookup)
        org_name = fake.company()

        rows.append({
            "org_id": org_id,
            "org_name": org_name,
            "city_name": fake.city(),
            "state_id": state_id,
            "zip_code": fake.postcode(),
            "phone": fake.phone_number()[:20],
            "email": f"contact@{org_name.lower().replace(' ', '').replace(',', '')}.org",
            "org_type": random.choice(org_types),
            "org_size": random.choice(org_sizes),
            "created_at": random_timestamp(fake),
            "last_updated_at": random_timestamp(fake),
        })
    return rows

if __name__ == "__main__":
    countries = build_countries()
    write_csv(
        "countries.csv",
        ["country_id", "country_name", "phone_code", "country_code", "last_updated_at", "is_eu_member"],
        countries,
    )

    states, state_lookup = build_states(countries)
    write_csv(
        "states.csv",
        ["state_id", "country_id", "state_name", "state_code", "last_updated_at"],
        states,
    )

    cities, city_lookup = build_cities(state_lookup)
    write_csv(
        "cities.csv",
        ["city_id", "state_id", "city_name", "lattitude", "longitude", "last_updated_at"],
        cities,
    )

    users, user_ids = build_users(countries, state_lookup)
    write_csv(
        "users.csv",
        ["user_id", "state_id", "country_id", "full_name", "first_name", "last_name",
         "primary_email_address", "primary_phone_number", "city_name", "zip_code",
         "last_updated_at", "gender", "dob", "is_eu"],
        users,
    )

    users_by_id = {u["user_id"]: u for u in users}

    volunteer_details, volunteer_ids = build_volunteer_details(user_ids)
    write_csv(
        "volunteer_details.csv",
        ["user_id", "terms_and_conditions", "terms_accepted_at", "availability_days",
         "created_at", "last_updated_at"],
        volunteer_details,
    )

    user_locations = build_user_locations(users, countries)
    write_csv(
        "user_locations.csv",
        ["user_id", "prev_loc", "curr_loc", "last_updated_at"],
        user_locations,
    )

    volunteer_locations = build_volunteer_locations(volunteer_ids, users_by_id, countries)
    write_csv(
        "volunteer_locations.csv",
        ["user_id", "prev_loc", "curr_loc", "last_updated_at"],
        volunteer_locations,
    )

    help_categories = build_help_categories()
    write_csv(
        "help_categories.csv",
        ["cat_id", "cat_name", "cat_desc", "last_updated_at"],
        help_categories,
    )

    user_skills = build_user_skills(volunteer_ids)
    write_csv(
        "user_skills.csv",
        ["user_id", "cat_id", "skill_level", "created_at", "last_updated_at"],
        user_skills,
    )

    organizations = build_organizations(state_lookup)
    write_csv(
        "organizations.csv",
        ["org_id", "org_name", "city_name", "state_id", "zip_code", "phone",
         "email", "org_type", "org_size", "created_at", "last_updated_at"],
        organizations,
    )
