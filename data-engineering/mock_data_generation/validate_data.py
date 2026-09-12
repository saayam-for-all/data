import csv

def load_csv(filename):
    with open(f"output/{filename}", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def check_unique(rows, key, table_name):
    values = [r[key] for r in rows]
    dupes = len(values) - len(set(values))
    status = "OK" if dupes == 0 else f"FAIL ({dupes} duplicates)"
    print(f"[{status}] {table_name}.{key} uniqueness")

def check_fk(child_rows, child_key, parent_ids, child_table, parent_table):
    orphans = []
    for r in child_rows:
        if r[child_key] not in parent_ids:
            orphans.append(r)
    status = "OK" if not orphans else f"FAIL ({len(orphans)} orphans)"
    print(f"[{status}] {child_table}.{child_key} -> {parent_table}")

countries = load_csv("countries.csv")
states = load_csv("states.csv")
cities = load_csv("cities.csv")
users = load_csv("users.csv")
volunteer_details = load_csv("volunteer_details.csv")
user_locations = load_csv("user_locations.csv")
volunteer_locations = load_csv("volunteer_locations.csv")
help_categories = load_csv("help_categories.csv")
user_skills = load_csv("user_skills.csv")
organizations = load_csv("organizations.csv")

check_unique(countries, "country_id", "countries")
check_unique(states, "state_id", "states")
check_unique(cities, "city_id", "cities")
check_unique(users, "user_id", "users")
check_unique(volunteer_details, "user_id", "volunteer_details")
check_unique(user_locations, "user_id", "user_locations")
check_unique(volunteer_locations, "user_id", "volunteer_locations")
check_unique(help_categories, "cat_id", "help_categories")
check_unique(organizations, "org_id", "organizations")

country_ids = {r["country_id"] for r in countries}
state_ids = {r["state_id"] for r in states}
user_ids = {r["user_id"] for r in users}
volunteer_ids = {r["user_id"] for r in volunteer_details}
cat_ids = {r["cat_id"] for r in help_categories}

check_fk(states, "country_id", country_ids, "states", "countries")
check_fk(cities, "state_id", state_ids, "cities", "states")
check_fk(volunteer_details, "user_id", user_ids, "volunteer_details", "users")
check_fk(user_locations, "user_id", user_ids, "user_locations", "users")
check_fk(volunteer_locations, "user_id", volunteer_ids, "volunteer_locations", "volunteer_details")
check_fk(user_skills, "user_id", user_ids, "user_skills", "users")
check_fk(user_skills, "cat_id", cat_ids, "user_skills", "help_categories")
check_fk(organizations, "state_id", state_ids, "organizations", "states")

skill_pairs = [(r["user_id"], r["cat_id"]) for r in user_skills]
dupes = len(skill_pairs) - len(set(skill_pairs))
status = "OK" if dupes == 0 else f"FAIL ({dupes} duplicates)"
print(f"[{status}] user_skills.(user_id, cat_id) composite uniqueness")

