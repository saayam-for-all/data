import csv
from collections import Counter


def read_csv(filename):
    with open(filename, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check_unique(rows, key_cols, table_name):
    keys = [tuple(row[k] for k in key_cols) for row in rows]
    counts = Counter(keys)
    duplicates = [k for k, c in counts.items() if c > 1]
    if duplicates:
        print(f"[FAIL] {table_name}: duplicate keys {duplicates[:5]}")
    else:
        print(f"[OK]   {table_name}: {len(rows)} rows, keys unique")


def check_fk(child_rows, child_col, parent_rows, parent_col, table_name):
    parent_ids = {row[parent_col] for row in parent_rows}
    orphans = [row[child_col] for row in child_rows
               if row[child_col] and row[child_col] not in parent_ids]
    if orphans:
        print(f"[FAIL] {table_name}.{child_col}: {len(orphans)} orphan values, e.g. {orphans[:5]}")
    else:
        print(f"[OK]   {table_name}.{child_col}: no orphans")


def check_required(rows, required_cols, table_name):
    for col in required_cols:
        missing = sum(1 for row in rows if not row[col].strip())
        if missing:
            print(f"[FAIL] {table_name}.{col}: {missing} blank required values")
        else:
            print(f"[OK]   {table_name}.{col}: no blanks")


if __name__ == "__main__":
    countries = read_csv("countries.csv")
    states = read_csv("states.csv")
    cities = read_csv("cities.csv")
    categories = read_csv("help_categories.csv")
    users = read_csv("users.csv")
    volunteer_details = read_csv("volunteer_details.csv")
    user_skills = read_csv("user_skills.csv")
    user_locations = read_csv("user_locations.csv")
    volunteer_locations = read_csv("volunteer_locations.csv")
    organizations = read_csv("organizations.csv")

    print("--- Primary key uniqueness ---")
    check_unique(countries, ["country_id"], "countries")
    check_unique(states, ["state_id"], "states")
    check_unique(cities, ["city_id"], "cities")
    check_unique(categories, ["cat_id"], "help_categories")
    check_unique(users, ["user_id"], "users")
    check_unique(volunteer_details, ["user_id"], "volunteer_details")
    check_unique(user_skills, ["user_id", "cat_id"], "user_skills")
    check_unique(user_locations, ["user_id"], "user_locations")
    check_unique(volunteer_locations, ["user_id"], "volunteer_locations")
    check_unique(organizations, ["org_id"], "organizations")

    print("\n--- Foreign key checks (no orphans) ---")
    check_fk(states, "country_id", countries, "country_id", "states")
    check_fk(cities, "state_id", states, "state_id", "cities")
    check_fk(users, "state_id", states, "state_id", "users")
    check_fk(users, "country_id", countries, "country_id", "users")
    check_fk(volunteer_details, "user_id", users, "user_id", "volunteer_details")
    check_fk(user_skills, "user_id", users, "user_id", "user_skills")
    check_fk(user_skills, "cat_id", categories, "cat_id", "user_skills")
    check_fk(user_locations, "user_id", users, "user_id", "user_locations")
    check_fk(volunteer_locations, "user_id", volunteer_details, "user_id", "volunteer_locations")
    check_fk(organizations, "state_id", states, "state_id", "organizations")

    print("\n--- Required fields ---")
    check_required(countries, ["country_name", "phone_code", "country_code"], "countries")
    check_required(states, ["country_id", "state_name"], "states")
    check_required(cities, ["state_id", "city_name"], "cities")
    check_required(categories, ["cat_name", "cat_desc"], "help_categories")
    check_required(users, ["user_id"], "users")
    check_required(organizations, ["org_name"], "organizations")

    print("\nValidation complete.")