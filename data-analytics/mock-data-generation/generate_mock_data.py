import csv
import random
from datetime import datetime, timedelta
from faker import Faker  # pip install faker

fake = Faker()
random.seed(42)
Faker.seed(42)

# ---------------- Configuration ----------------
NUM_COUNTRIES = 5
NUM_STATES = 10
NUM_CITIES = 15
NUM_CATEGORIES = 20
NUM_USERS = 100
NUM_ORGANIZATIONS = 20
VOLUNTEER_RATIO = 0.4          # fraction of users who become volunteers
SKILLS_PER_VOLUNTEER = (1, 3)  # min, max skills per volunteer


def random_timestamp(max_days_ago=60, min_days_ago=0):
    days_ago = random.randint(min_days_ago, max_days_ago)
    dt = datetime.now() - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def make_user_id(i):
    padded = f"{i:015d}"
    parts = [padded[0:3], padded[3:6], padded[6:9], padded[9:12], padded[12:15]]
    return "SID-00-" + "-".join(parts)


def make_org_id(i):
    padded = f"{i:013d}"
    parts = [padded[0:3], padded[3:6], padded[6:9], padded[9:13]]
    return "ORG-" + "-".join(parts)


# ---------------- 1. countries (parent) ----------------
def generate_countries(n):
    countries = [
        {"country_id": 1, "country_name": "United States", "phone_code": "+1",  "country_code": "US", "is_eu_member": False},
        {"country_id": 2, "country_name": "India",         "phone_code": "+91", "country_code": "IN", "is_eu_member": False},
        {"country_id": 3, "country_name": "Ireland",       "phone_code": "+353","country_code": "IE", "is_eu_member": True},
        {"country_id": 4, "country_name": "Germany",       "phone_code": "+49", "country_code": "DE", "is_eu_member": True},
        {"country_id": 5, "country_name": "Canada",        "phone_code": "+1",  "country_code": "CA", "is_eu_member": False},
    ]
    for c in countries:
        c["last_updated_at"] = random_timestamp()
    return countries[:n]


# ---------------- 2. states (child of countries) ----------------
def generate_states(n, countries):
    states = []
    for i in range(1, n + 1):
        country = random.choice(countries)
        states.append({
            "state_id": f"ST-{i:03d}",
            "country_id": country["country_id"],
            "state_name": f"State {i}",
            "state_code": f"S{i:02d}",
            "last_updated_at": random_timestamp(),
        })
    return states


# ---------------- 3. cities (child of states) ----------------
def generate_cities(n, states):
    cities = []
    for i in range(1, n + 1):
        state = random.choice(states)
        cities.append({
            "city_id": f"CITY-{i:03d}",
            "state_id": state["state_id"],
            "city_name": f"City {i}",
            "lattitude": round(random.uniform(25.0, 49.0), 6),
            "longitude": round(random.uniform(-124.0, -67.0), 6),
            "last_updated_at": random_timestamp(),
        })
    return cities


# ---------------- 4. help_categories (parent) ----------------
def generate_help_categories(n):
    categories = []
    for i in range(1, n + 1):
        categories.append({
            "cat_id": str(i),
            "cat_name": f"CATEGORY_{i}",
            "cat_desc": f"Help category number {i}",
            "last_updated_at": random_timestamp(),
        })
    return categories


# ---------------- 5. users (child of states, countries) ----------------
def generate_users(n, states, countries):
    country_lookup = {c["country_id"]: c for c in countries}
    users = []
    for i in range(1, n + 1):
        state = random.choice(states)
        country = country_lookup[state["country_id"]]  # keeps state/country consistent
        first, last = fake.first_name(), fake.last_name()
        users.append({
            "user_id": make_user_id(i),
            "state_id": state["state_id"],
            "country_id": country["country_id"],
            "full_name": f"{first} {last}",
            "first_name": first,
            "middle_name": "",
            "last_name": last,
            "primary_email_address": f"user{i}@example.com",
            "primary_phone_number": fake.phone_number()[:20],
            "addr_ln1": fake.street_address(),
            "addr_ln2": "",
            "addr_ln3": "",
            "city_name": f"City {random.randint(1, NUM_CITIES)}",
            "zip_code": fake.postcode()[:10],
            "last_location": "",
            "last_updated_at": random_timestamp(),
            "time_zone": "UTC",
            "profile_picture_path": "",
            "gender": random.choice(["Male", "Female", "Other"]),
            "promotion_wizard_stage": random.randint(1, 5),
            "promotion_wizard_last_updated_at": random_timestamp(),
            "external_auth_provider": "",
            "dob": fake.date_of_birth(minimum_age=18, maximum_age=70).strftime("%Y-%m-%d"),
            "is_eu": country["is_eu_member"],
        })
    return users


# ---------------- 6. volunteer_details (child of users) ----------------
def generate_volunteer_details(users, ratio=VOLUNTEER_RATIO):
    volunteers = random.sample(users, k=int(len(users) * ratio))
    details = []
    for u in volunteers:
        created = random_timestamp(90, 30)   # older
        updated = random_timestamp(30, 0)    # newer, so created_at <= last_updated_at
        details.append({
            "user_id": u["user_id"],
            "terms_and_conditions": True,
            "terms_accepted_at": created,
            "govt_id_path1": f"/mock/ids/{u['user_id']}_front.png",
            "govt_id_path2": f"/mock/ids/{u['user_id']}_back.png",
            "path1_updated_at": created,
            "path2_updated_at": created,
            "availability_days": '["Monday","Wednesday","Friday"]',
            "availability_times": '["Morning","Evening"]',
            "created_at": created,
            "last_updated_at": updated,
        })
    return details


# ---------------- 7. user_skills (child of volunteer_details, help_categories) ----------------
def generate_user_skills(volunteer_details, categories, skills_range=SKILLS_PER_VOLUNTEER):
    skills = []
    for v in volunteer_details:
        chosen = random.sample(categories, k=random.randint(*skills_range))
        for cat in chosen:
            skills.append({
                "user_id": v["user_id"],
                "cat_id": cat["cat_id"],
                "skill_level": random.choice(["BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"]),
                "created_at": v["created_at"],
                "last_updated_at": v["created_at"],
            })
    return skills


# ---------------- 8. user_locations (child of users) ----------------
def generate_user_locations(users, cities):
    cities_by_state = {}
    for c in cities:
        cities_by_state.setdefault(c["state_id"], []).append(c)

    locations = []
    for u in users:
        candidates = cities_by_state.get(u["state_id"])
        if candidates:
            city = random.choice(candidates)
            lat = city["lattitude"] + random.uniform(-0.05, 0.05)
            lon = city["longitude"] + random.uniform(-0.05, 0.05)
        else:
            lat = round(random.uniform(25.0, 49.0), 6)
            lon = round(random.uniform(-124.0, -67.0), 6)
        locations.append({
            "user_id": u["user_id"],
            "prev_loc": "",
            "curr_loc": f"POINT({lon:.6f} {lat:.6f})",
            "last_updated_at": random_timestamp(),
        })
    return locations


# ---------------- 9. volunteer_locations (child of volunteer_details) ----------------
def generate_volunteer_locations(volunteer_details, users, cities):
    users_by_id = {u["user_id"]: u for u in users}
    cities_by_state = {}
    for c in cities:
        cities_by_state.setdefault(c["state_id"], []).append(c)

    locations = []
    for v in volunteer_details:
        u = users_by_id[v["user_id"]]
        candidates = cities_by_state.get(u["state_id"])
        if candidates:
            city = random.choice(candidates)
            lat = city["lattitude"] + random.uniform(-0.05, 0.05)
            lon = city["longitude"] + random.uniform(-0.05, 0.05)
        else:
            lat = round(random.uniform(25.0, 49.0), 6)
            lon = round(random.uniform(-124.0, -67.0), 6)
        locations.append({
            "user_id": v["user_id"],
            "prev_loc": "",
            "curr_loc": f"POINT({lon:.6f} {lat:.6f})",
            "last_updated_at": random_timestamp(),
        })
    return locations


# ---------------- 10. organizations (child of states) ----------------
def generate_organizations(n, states):
    orgs = []
    for i in range(1, n + 1):
        state = random.choice(states)
        created = random_timestamp(90, 30)
        updated = random_timestamp(30, 0)
        orgs.append({
            "org_id": make_org_id(i),
            "org_name": f"{fake.company()} Foundation",
            "street": fake.street_address(),
            "city_name": f"City {random.randint(1, NUM_CITIES)}",
            "state_id": state["state_id"],
            "zip_code": fake.postcode()[:10],
            "mission": "Helping the community through volunteer-driven programs.",
            "web_url": f"https://www.example-org{i}.org",
            "phone": fake.phone_number()[:20],
            "email": f"contact{i}@example-org.org",
            "org_type": random.choice(["non_profit", "for_profit"]),
            "org_size": random.choice(["small", "medium", "large"]),
            "org_rating": random.randint(1, 5),
            "is_collaborator": random.choice([True, False]),
            "is_contributor": random.choice([True, False]),
            "created_at": created,
            "last_updated_at": updated,
        })
    return orgs


# ---------------- shared CSV writer ----------------
def save_csv(rows, filename, fieldnames):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    countries = generate_countries(NUM_COUNTRIES)
    save_csv(countries, "countries.csv",
             ["country_id", "country_name", "phone_code", "country_code", "last_updated_at", "is_eu_member"])

    states = generate_states(NUM_STATES, countries)
    save_csv(states, "states.csv",
             ["state_id", "country_id", "state_name", "state_code", "last_updated_at"])

    cities = generate_cities(NUM_CITIES, states)
    save_csv(cities, "cities.csv",
             ["city_id", "state_id", "city_name", "lattitude", "longitude", "last_updated_at"])

    categories = generate_help_categories(NUM_CATEGORIES)
    save_csv(categories, "help_categories.csv",
             ["cat_id", "cat_name", "cat_desc", "last_updated_at"])

    users = generate_users(NUM_USERS, states, countries)
    save_csv(users, "users.csv",
             ["user_id", "state_id", "country_id", "full_name", "first_name", "middle_name", "last_name",
              "primary_email_address", "primary_phone_number", "addr_ln1", "addr_ln2", "addr_ln3",
              "city_name", "zip_code", "last_location", "last_updated_at", "time_zone",
              "profile_picture_path", "gender", "promotion_wizard_stage",
              "promotion_wizard_last_updated_at", "external_auth_provider", "dob", "is_eu"])

    volunteer_details = generate_volunteer_details(users)
    save_csv(volunteer_details, "volunteer_details.csv",
             ["user_id", "terms_and_conditions", "terms_accepted_at", "govt_id_path1", "govt_id_path2",
              "path1_updated_at", "path2_updated_at", "availability_days", "availability_times",
              "created_at", "last_updated_at"])

    user_skills = generate_user_skills(volunteer_details, categories)
    save_csv(user_skills, "user_skills.csv",
             ["user_id", "cat_id", "skill_level", "created_at", "last_updated_at"])

    user_locations = generate_user_locations(users, cities)
    save_csv(user_locations, "user_locations.csv",
             ["user_id", "prev_loc", "curr_loc", "last_updated_at"])

    volunteer_locations = generate_volunteer_locations(volunteer_details, users, cities)
    save_csv(volunteer_locations, "volunteer_locations.csv",
             ["user_id", "prev_loc", "curr_loc", "last_updated_at"])

    organizations = generate_organizations(NUM_ORGANIZATIONS, states)
    save_csv(organizations, "organizations.csv",
             ["org_id", "org_name", "street", "city_name", "state_id", "zip_code", "mission", "web_url",
              "phone", "email", "org_type", "org_size", "org_rating", "is_collaborator",
              "is_contributor", "created_at", "last_updated_at"])

    print("All 10 CSV files generated.")