import csv
import json
import os
import random
from datetime import datetime, timedelta

random.seed(42)

ROW_COUNT = 400

US_STATES = [
    {"state_id": "AL", "state_name": "Alabama", "state_code": "US-AL", "cities": [("Birmingham", 33.5207, -86.8025), ("Montgomery", 32.3668, -86.3000), ("Huntsville", 34.7304, -86.5861)]},
    {"state_id": "AK", "state_name": "Alaska", "state_code": "US-AK", "cities": [("Anchorage", 61.2181, -149.9003), ("Fairbanks", 64.8378, -147.7164)]},
    {"state_id": "AZ", "state_name": "Arizona", "state_code": "US-AZ", "cities": [("Phoenix", 33.4484, -112.0740), ("Tucson", 32.2226, -110.9747), ("Mesa", 33.4152, -111.8315)]},
    {"state_id": "CA", "state_name": "California", "state_code": "US-CA", "cities": [("Los Angeles", 34.0522, -118.2437), ("San Francisco", 37.7749, -122.4194), ("San Jose", 37.3382, -121.8863), ("San Diego", 32.7157, -117.1611)]},
    {"state_id": "CO", "state_name": "Colorado", "state_code": "US-CO", "cities": [("Denver", 39.7392, -104.9903), ("Boulder", 40.0150, -105.2705)]},
    {"state_id": "FL", "state_name": "Florida", "state_code": "US-FL", "cities": [("Miami", 25.7617, -80.1918), ("Orlando", 28.5383, -81.3792), ("Tampa", 27.9506, -82.4572)]},
    {"state_id": "GA", "state_name": "Georgia", "state_code": "US-GA", "cities": [("Atlanta", 33.7490, -84.3880), ("Savannah", 32.0809, -81.0912), ("Augusta", 33.4735, -81.9748)]},
    {"state_id": "IL", "state_name": "Illinois", "state_code": "US-IL", "cities": [("Chicago", 41.8781, -87.6298), ("Springfield", 39.7817, -89.6501), ("Naperville", 41.7508, -88.1535)]},
    {"state_id": "NY", "state_name": "New York", "state_code": "US-NY", "cities": [("New York City", 40.7128, -74.0060), ("Buffalo", 42.8864, -78.8784), ("Albany", 42.6526, -73.7562)]},
    {"state_id": "TX", "state_name": "Texas", "state_code": "US-TX", "cities": [("Houston", 29.7604, -95.3698), ("Dallas", 32.7767, -96.7970), ("Austin", 30.2672, -97.7431), ("San Antonio", 29.4241, -98.4936)]},
    {"state_id": "VA", "state_name": "Virginia", "state_code": "US-VA", "cities": [("Richmond", 37.5407, -77.4360), ("Virginia Beach", 36.8529, -75.9780), ("Norfolk", 36.8508, -76.2859), ("Charlottesville", 38.0293, -78.4767)]},
    {"state_id": "WA", "state_name": "Washington", "state_code": "US-WA", "cities": [("Seattle", 47.6062, -122.3321), ("Tacoma", 47.2529, -122.4443), ("Spokane", 47.6588, -117.4260)]},
    {"state_id": "OH", "state_name": "Ohio", "state_code": "US-OH", "cities": [("Columbus", 39.9612, -82.9988), ("Cleveland", 41.4993, -81.6944), ("Cincinnati", 39.1031, -84.5120)]},
    {"state_id": "PA", "state_name": "Pennsylvania", "state_code": "US-PA", "cities": [("Philadelphia", 39.9526, -75.1652), ("Pittsburgh", 40.4406, -79.9959), ("Allentown", 40.6084, -75.4902)]},
    {"state_id": "NC", "state_name": "North Carolina", "state_code": "US-NC", "cities": [("Charlotte", 35.2271, -80.8431), ("Raleigh", 35.7796, -78.6382), ("Durham", 35.9940, -78.8986)]},
]

INDIA_STATES = [
    {"state_id": "MH", "state_name": "Maharashtra", "state_code": "IN-MH", "cities": [("Mumbai", 19.0760, 72.8777), ("Pune", 18.5204, 73.8567)]},
    {"state_id": "KA", "state_name": "Karnataka", "state_code": "IN-KA", "cities": [("Bangalore", 12.9716, 77.5946), ("Mysore", 12.2958, 76.6394)]},
    {"state_id": "DL", "state_name": "Delhi", "state_code": "IN-DL", "cities": [("New Delhi", 28.6139, 77.2090)]},
    {"state_id": "TN", "state_name": "Tamil Nadu", "state_code": "IN-TN", "cities": [("Chennai", 13.0827, 80.2707), ("Coimbatore", 11.0168, 76.9558)]},
]

UK_STATES = [
    {"state_id": "ENG", "state_name": "England", "state_code": "GB-ENG", "cities": [("London", 51.5074, -0.1278), ("Manchester", 53.4808, -2.2426)]},
]

COUNTRIES = [
    {"country_id": 1, "country_name": "UNITED_STATES", "phone_code": "1", "country_code": "USA", "is_eu_member": False, "states": US_STATES},
    {"country_id": 2, "country_name": "INDIA", "phone_code": "91", "country_code": "IND", "is_eu_member": False, "states": INDIA_STATES},
    {"country_id": 3, "country_name": "UNITED_KINGDOM", "phone_code": "44", "country_code": "GBR", "is_eu_member": False, "states": UK_STATES},
]

HELP_CATEGORIES = [
    ("0.0.0.0.0", "GENERAL_CATEGORY", "GENERAL_CATEGORY_DESC"),
    ("1", "FOOD_AND_ESSENTIALS", "FOOD_AND_ESSENTIALS_DESC"),
    ("1.1", "FOOD_ASSISTANCE", "FOOD_ASSISTANCE_DESC"),
    ("1.2", "GROCERY_SHOPPING_AND_DELIVERY", "GROCERY_SHOPPING_AND_DELIVERY_DESC"),
    ("1.3", "COOKING_HELP", "COOKING_HELP_DESC"),
    ("2", "CLOTHING_ASSISTANCE", "CLOTHING_ASSISTANCE_DESC"),
    ("2.1", "DONATE_CLOTHES", "DONATE_CLOTHES_DESC"),
    ("2.2", "BORROW_CLOTHES", "BORROW_CLOTHES_DESC"),
    ("3", "HOUSING_ASSISTANCE", "HOUSING_ASSISTANCE_DESC"),
    ("3.1", "LEASE_SUPPORT", "LEASE_SUPPORT_DESC"),
    ("3.2", "TENANT_RENT_SUPPORT", "TENANT_RENT_SUPPORT_DESC"),
    ("3.3", "REPAIR_MAINTENANCE_SUPPORT", "REPAIR_MAINTENANCE_SUPPORT_DESC"),
    ("3.3.1", "PLUMBING", "PLUMBING_DESC"),
    ("3.3.2", "HANDYMAN", "HANDYMAN_DESC"),
    ("3.3.3", "ELECTRICIAN", "ELECTRICIAN_DESC"),
    ("4", "EDUCATION_CAREER_SUPPORT", "EDUCATION_CAREER_SUPPORT_DESC"),
    ("4.1", "COLLEGE_APPLICATION_HELP", "COLLEGE_APPLICATION_HELP_DESC"),
    ("4.2", "SOP_ESSAY_REVIEW", "SOP_ESSAY_REVIEW_DESC"),
    ("4.3", "TUTORING", "TUTORING_DESC"),
    ("4.6", "CAREER_GUIDANCE", "CAREER_GUIDANCE_DESC"),
    ("5", "HEALTHCARE_AND_WELLNESS", "HEALTHCARE_AND_WELLNESS_DESC"),
    ("5.1", "MEDICAL_CONSULTATION", "MEDICAL_CONSULTATION_DESC"),
    ("5.2", "MEDICINE_DELIVERY", "MEDICINE_DELIVERY_DESC"),
    ("5.3", "MENTAL_WELLBEING_SUPPORT", "MENTAL_WELLBEING_SUPPORT_DESC"),
    ("6", "ELDERLY_COMMUNITY_ASSISTANCE", "ELDERLY_COMMUNITY_ASSISTANCE_DESC"),
    ("6.1", "SENIOR_RELOCATION_SUPPORT", "SENIOR_RELOCATION_SUPPORT_DESC"),
    ("6.2", "DIGITAL_SUPPORT_FOR_SENIORS", "DIGITAL_SUPPORT_FOR_SENIORS_DESC"),
    ("6.5", "ERRANDS_EVENTS_TRANSPORTATION", "ERRANDS_EVENTS_TRANSPORTATION_DESC"),
]

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Christopher", "Karen", "Daniel", "Lisa", "Matthew", "Nancy",
    "Anthony", "Betty", "Mark", "Sandra", "Donald", "Ashley", "Steven", "Emily",
    "Andrew", "Donna", "Paul", "Michelle", "Joshua", "Carol", "Kenneth", "Amanda",
    "Raj", "Priya", "Amit", "Sunita", "Vikram", "Anita", "Sanjay", "Deepa",
    "Wei", "Mei", "Jun", "Ling", "Hiroshi", "Yuki", "Carlos", "Sofia",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Patel", "Shah", "Kumar", "Singh", "Sharma", "Gupta", "Reddy", "Nair",
    "Chen", "Wang", "Li", "Zhang", "Liu", "Tanaka", "Kim", "Nguyen",
]

ORG_NAMES = [
    "Hope Foundation", "Bright Future Alliance", "Community Care Network",
    "Helping Hands International", "Green Earth Initiative", "Youth Empowerment League",
    "Shelter for All", "Food Bank United", "Education First Trust",
    "Medical Aid Society", "Veterans Support Group", "Elder Care Alliance",
    "Tech for Good", "Disaster Relief Corps", "Clean Water Project",
    "Animal Rescue League", "Housing Aid Foundation", "Mental Health Partners",
    "Literacy Now", "Job Training Center", "Cultural Bridge Foundation",
    "Rural Development Trust", "Urban Renewal Initiative", "Child Welfare Society",
    "Women Empowerment Network", "Refugee Support Alliance", "Environmental Defense Fund",
    "Public Health Alliance", "Sports for Youth", "Arts and Culture Foundation",
]

MISSIONS = [
    "Dedicated to improving lives through community-driven programs.",
    "Empowering underserved communities with education and resources.",
    "Providing essential services to those in need across the nation.",
    "Building sustainable solutions for social challenges.",
    "Creating pathways to self-sufficiency for vulnerable populations.",
    "Advancing equity and justice through advocacy and direct services.",
    "Connecting resources with communities to create lasting change.",
    "Supporting individuals and families on their journey to stability.",
    "Fostering innovation in social services delivery.",
    "Strengthening communities through collaboration and partnership.",
]

SKILL_LEVELS = ["BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"]
GENDERS = ["Male", "Female", "Non-binary", "Prefer not to say"]
TIMEZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "Asia/Kolkata", "Europe/London"]


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def random_ts(start_year=2025, end_year=2026):
    start = datetime(start_year, 6, 1)
    end = datetime(end_year, 8, 31)
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta), hours=random.randint(0, 23), minutes=random.randint(0, 59), seconds=random.randint(0, 59))


def make_user_id(seq):
    padded = str(seq).zfill(15)
    return f"SID-00-{padded[0:3]}-{padded[3:6]}-{padded[6:9]}-{padded[9:12]}-{padded[12:15]}"


def make_org_id(seq):
    padded = str(seq).zfill(13)
    return f"ORG-{padded[0:3]}-{padded[3:6]}-{padded[6:9]}-{padded[9:13]}"


def jitter_coord(lat, lng, max_offset=0.05):
    return (
        round(lat + random.uniform(-max_offset, max_offset), 6),
        round(lng + random.uniform(-max_offset, max_offset), 6),
    )


def make_point(lat, lng):
    return f"SRID=4326;POINT({lng} {lat})"


def write_csv_file(filepath, rows, fieldnames):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate_countries():
    rows = []
    for c in COUNTRIES:
        rows.append({
            "country_id": c["country_id"],
            "country_name": c["country_name"],
            "phone_code": c["phone_code"],
            "country_code": c["country_code"],
            "last_updated_at": fmt_ts(random_ts()),
            "is_eu_member": str(c["is_eu_member"]),
        })
    return rows


def generate_states():
    rows = []
    for c in COUNTRIES:
        for s in c["states"]:
            rows.append({
                "state_id": s["state_id"],
                "country_id": c["country_id"],
                "state_name": s["state_name"],
                "state_code": s["state_code"],
                "last_updated_at": fmt_ts(random_ts()),
            })
    return rows


def generate_cities(states_data):
    rows = []
    city_id = 1
    for c in COUNTRIES:
        for s in c["states"]:
            for city_name, lat, lng in s["cities"]:
                rows.append({
                    "city_id": city_id,
                    "state_id": s["state_id"],
                    "city_name": city_name,
                    "lattitude": lat,
                    "longitude": lng,
                    "last_updated_at": fmt_ts(random_ts()),
                })
                city_id += 1
    return rows


def generate_help_categories():
    rows = []
    ts = fmt_ts(random_ts())
    for cat_id, cat_name, cat_desc in HELP_CATEGORIES:
        rows.append({
            "cat_id": cat_id,
            "cat_name": cat_name,
            "cat_desc": cat_desc,
            "last_updated_at": ts,
        })
    return rows


def generate_users(count, all_states):
    rows = []
    for i in range(1, count + 1):
        state = random.choice(all_states)
        country_id = None
        for c in COUNTRIES:
            for s in c["states"]:
                if s["state_id"] == state["state_id"]:
                    country_id = c["country_id"]
                    break

        city_data = random.choice(state["cities"])
        city_name = city_data[0]

        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        full_name = f"{first} {last}"
        created = random_ts()
        updated = created + timedelta(days=random.randint(0, 60))

        rows.append({
            "user_id": make_user_id(i),
            "state_id": state["state_id"],
            "country_id": country_id,
            "user_status_id": random.choices([1, 2, 3], weights=[80, 10, 10], k=1)[0],
            "full_name": full_name,
            "first_name": first,
            "middle_name": "",
            "last_name": last,
            "primary_email_address": f"{first.lower()}.{last.lower()}{i}@example.com",
            "primary_phone_number": f"+1{random.randint(2000000000, 9999999999)}",
            "addr_ln1": f"{random.randint(100, 9999)} {random.choice(['Main', 'Oak', 'Elm', 'Park', 'Cedar'])} St",
            "addr_ln2": "",
            "addr_ln3": "",
            "city_name": city_name,
            "zip_code": f"{random.randint(10000, 99999)}",
            "last_location": "",
            "last_updated_at": fmt_ts(updated),
            "time_zone": random.choice(TIMEZONES),
            "profile_picture_path": "",
            "gender": random.choice(GENDERS),
            "language_1": "",
            "language_2": "",
            "language_3": "",
            "promotion_wizard_stage": "",
            "promotion_wizard_last_updated_at": "",
            "external_auth_provider": "",
            "dob": f"{random.randint(1960, 2005)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
            "is_eu": str(False),
        })
        rows[-1]["_state"] = state
        rows[-1]["_city_data"] = city_data

    return rows


def generate_volunteer_details(users, count):
    vol_users = random.sample(users, min(count, len(users)))
    rows = []
    for u in vol_users:
        created = random_ts()
        updated = created + timedelta(days=random.randint(1, 90))
        has_terms = random.random() > 0.1
        terms_accepted = created + timedelta(minutes=random.randint(5, 300)) if has_terms else ""

        rows.append({
            "user_id": u["user_id"],
            "terms_and_conditions": str(has_terms),
            "terms_accepted_at": fmt_ts(terms_accepted) if terms_accepted else "",
            "govt_id_path1": f"uploads/govt/{u['user_id']}/id-front.jpg" if random.random() > 0.4 else "",
            "govt_id_path2": f"uploads/govt/{u['user_id']}/id-back.jpg" if random.random() > 0.6 else "",
            "path1_updated_at": fmt_ts(created + timedelta(days=random.randint(1, 30))) if random.random() > 0.4 else "",
            "path2_updated_at": fmt_ts(created + timedelta(days=random.randint(1, 30))) if random.random() > 0.6 else "",
            "availability_days": json.dumps(random.sample(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], random.randint(1, 5))),
            "availability_times": json.dumps(random.sample(["morning", "afternoon", "evening"], random.randint(1, 3))),
            "created_at": fmt_ts(created),
            "last_updated_at": fmt_ts(updated),
        })
    return rows


def generate_user_skills(users, help_cats, count):
    cat_ids = [c["cat_id"] for c in help_cats]
    rows = []
    used = set()
    skill_users = random.sample(users, min(count, len(users)))

    for u in skill_users:
        num_skills = random.randint(1, 4)
        skills = random.sample(cat_ids, min(num_skills, len(cat_ids)))
        for cat_id in skills:
            key = (u["user_id"], cat_id)
            if key not in used:
                used.add(key)
                created = random_ts()
                rows.append({
                    "user_id": u["user_id"],
                    "cat_id": cat_id,
                    "skill_level": random.choice(SKILL_LEVELS),
                    "created_at": fmt_ts(created),
                    "last_updated_at": fmt_ts(created + timedelta(days=random.randint(0, 30))),
                })
    return rows


def generate_volunteer_locations(vol_details, users_lookup):
    rows = []
    for vd in vol_details:
        uid = vd["user_id"]
        user = users_lookup.get(uid)
        if not user:
            continue

        city_data = user.get("_city_data")
        if not city_data:
            continue

        base_lat, base_lng = city_data[1], city_data[2]
        curr_lat, curr_lng = jitter_coord(base_lat, base_lng, 0.03)
        prev_lat, prev_lng = jitter_coord(base_lat, base_lng, 0.05)
        has_prev = random.random() > 0.3

        rows.append({
            "user_id": uid,
            "prev_loc": make_point(prev_lat, prev_lng) if has_prev else "",
            "curr_loc": make_point(curr_lat, curr_lng),
            "last_updated_at": fmt_ts(random_ts()),
        })
    return rows


def generate_user_locations(users, count):
    loc_users = random.sample(users, min(count, len(users)))
    rows = []
    for u in loc_users:
        city_data = u.get("_city_data")
        if not city_data:
            continue

        base_lat, base_lng = city_data[1], city_data[2]
        curr_lat, curr_lng = jitter_coord(base_lat, base_lng, 0.03)
        prev_lat, prev_lng = jitter_coord(base_lat, base_lng, 0.05)
        has_prev = random.random() > 0.3

        rows.append({
            "user_id": u["user_id"],
            "prev_loc": make_point(prev_lat, prev_lng) if has_prev else "",
            "curr_loc": make_point(curr_lat, curr_lng),
            "last_updated_at": fmt_ts(random_ts()),
        })
    return rows


def generate_organizations(count, all_states):
    rows = []
    for i in range(1, count + 1):
        state = random.choice(all_states)
        city_data = random.choice(state["cities"])
        created = random_ts()
        updated = created + timedelta(days=random.randint(0, 60))
        has_rating = random.random() > 0.2

        rows.append({
            "org_id": make_org_id(i),
            "org_name": f"{random.choice(ORG_NAMES)} {state['state_code'][:2]}",
            "street": f"{random.randint(100, 9999)} {random.choice(['Main', 'Oak', 'Elm', 'Park', 'Cedar'])} St",
            "city_name": city_data[0],
            "state_id": state["state_id"],
            "zip_code": f"{random.randint(10000, 99999)}",
            "mission": random.choice(MISSIONS),
            "web_url": f"https://www.org{i}.example.org",
            "phone": f"({random.randint(200, 999)}) {random.randint(200, 999)}-{random.randint(1000, 9999)}",
            "email": f"contact@org{i}.example.org",
            "org_type": random.choices(["non_profit", "for_profit"], weights=[70, 30], k=1)[0],
            "org_size": random.choices(["small", "medium", "large"], weights=[30, 45, 25], k=1)[0],
            "org_rating": random.choices([1, 2, 3, 4, 5], weights=[3, 5, 15, 40, 37], k=1)[0] if has_rating else "",
            "is_collaborator": str(random.random() > 0.65),
            "is_contributor": str(random.random() > 0.45),
            "created_at": fmt_ts(created),
            "last_updated_at": fmt_ts(updated),
        })
    return rows


def main():
    output_dir = os.path.dirname(os.path.abspath(__file__))

    all_states = []
    for c in COUNTRIES:
        all_states.extend(c["states"])

    print("Generating countries...")
    countries = generate_countries()
    write_csv_file(os.path.join(output_dir, "countries.csv"), countries,
                   ["country_id", "country_name", "phone_code", "country_code", "last_updated_at", "is_eu_member"])

    print("Generating states...")
    states = generate_states()
    write_csv_file(os.path.join(output_dir, "states.csv"), states,
                   ["state_id", "country_id", "state_name", "state_code", "last_updated_at"])

    print("Generating cities...")
    cities = generate_cities(states)
    write_csv_file(os.path.join(output_dir, "cities.csv"), cities,
                   ["city_id", "state_id", "city_name", "lattitude", "longitude", "last_updated_at"])

    print("Generating help_categories...")
    help_cats = generate_help_categories()
    write_csv_file(os.path.join(output_dir, "help_categories.csv"), help_cats,
                   ["cat_id", "cat_name", "cat_desc", "last_updated_at"])

    print(f"Generating {ROW_COUNT} users...")
    users = generate_users(ROW_COUNT, all_states)
    users_lookup = {u["user_id"]: u for u in users}
    users_csv = [{k: v for k, v in u.items() if not k.startswith("_")} for u in users]
    write_csv_file(os.path.join(output_dir, "users.csv"), users_csv,
                   ["user_id", "state_id", "country_id", "user_status_id", "full_name", "first_name",
                    "middle_name", "last_name", "primary_email_address", "primary_phone_number",
                    "addr_ln1", "addr_ln2", "addr_ln3", "city_name", "zip_code", "last_location",
                    "last_updated_at", "time_zone", "profile_picture_path", "gender",
                    "language_1", "language_2", "language_3", "promotion_wizard_stage",
                    "promotion_wizard_last_updated_at", "external_auth_provider", "dob", "is_eu"])

    print(f"Generating volunteer_details...")
    vol_details = generate_volunteer_details(users, ROW_COUNT)
    write_csv_file(os.path.join(output_dir, "volunteer_details.csv"), vol_details,
                   ["user_id", "terms_and_conditions", "terms_accepted_at", "govt_id_path1", "govt_id_path2",
                    "path1_updated_at", "path2_updated_at", "availability_days", "availability_times",
                    "created_at", "last_updated_at"])

    print(f"Generating user_skills...")
    user_skills = generate_user_skills(users, help_cats, ROW_COUNT)
    write_csv_file(os.path.join(output_dir, "user_skills.csv"), user_skills,
                   ["user_id", "cat_id", "skill_level", "created_at", "last_updated_at"])

    print(f"Generating volunteer_locations...")
    vol_locations = generate_volunteer_locations(vol_details, users_lookup)
    write_csv_file(os.path.join(output_dir, "volunteer_locations.csv"), vol_locations,
                   ["user_id", "prev_loc", "curr_loc", "last_updated_at"])

    print(f"Generating user_locations...")
    user_locs = generate_user_locations(users, ROW_COUNT)
    write_csv_file(os.path.join(output_dir, "user_locations.csv"), user_locs,
                   ["user_id", "prev_loc", "curr_loc", "last_updated_at"])

    print(f"Generating {ROW_COUNT} organizations...")
    orgs = generate_organizations(ROW_COUNT, all_states)
    write_csv_file(os.path.join(output_dir, "organizations.csv"), orgs,
                   ["org_id", "org_name", "street", "city_name", "state_id", "zip_code", "mission",
                    "web_url", "phone", "email", "org_type", "org_size", "org_rating",
                    "is_collaborator", "is_contributor", "created_at", "last_updated_at"])

    print(f"\nGenerated files:")
    print(f"  countries.csv: {len(countries)} rows")
    print(f"  states.csv: {len(states)} rows")
    print(f"  cities.csv: {len(cities)} rows")
    print(f"  help_categories.csv: {len(help_cats)} rows")
    print(f"  users.csv: {len(users)} rows")
    print(f"  volunteer_details.csv: {len(vol_details)} rows")
    print(f"  user_skills.csv: {len(user_skills)} rows")
    print(f"  volunteer_locations.csv: {len(vol_locations)} rows")
    print(f"  user_locations.csv: {len(user_locs)} rows")
    print(f"  organizations.csv: {len(orgs)} rows")
    print(f"\nAll files saved to: {output_dir}")


if __name__ == "__main__":
    main()
