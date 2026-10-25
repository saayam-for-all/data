"""Validate the generated CSVs for issue #301's Data Quality checklist.

Run after generate_mock_data.py:
    python validate_data.py

Checks: unique primary keys, no orphan foreign keys, no real-looking
contact info, valid date ordering, and that geo coordinates parse.
"""

import csv
import re
import sys


def load(name):
    with open(f"{name}.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fail(msg, errors):
    errors.append(msg)


def main():
    errors = []

    countries = load("countries")
    states = load("states")
    cities = load("cities")
    users = load("users")
    volunteer_details = load("volunteer_details")
    user_skills = load("user_skills")
    volunteer_locations = load("volunteer_locations")
    user_locations = load("user_locations")
    help_categories = load("help_categories")
    organizations = load("organizations")

    # --- Primary key uniqueness ---
    def check_unique_pk(rows, key, table):
        values = [r[key] for r in rows]
        if len(values) != len(set(values)):
            fail(f"{table}: duplicate {key} values found", errors)

    check_unique_pk(countries, "country_id", "countries")
    check_unique_pk(states, "state_id", "states")
    check_unique_pk(cities, "city_id", "cities")
    check_unique_pk(users, "user_id", "users")
    check_unique_pk(volunteer_details, "user_id", "volunteer_details")
    check_unique_pk(help_categories, "cat_id", "help_categories")
    check_unique_pk(organizations, "org_id", "organizations")

    skill_pairs = [(r["user_id"], r["cat_id"]) for r in user_skills]
    if len(skill_pairs) != len(set(skill_pairs)):
        fail("user_skills: duplicate (user_id, cat_id) pairs found", errors)

    # --- Foreign key integrity (no orphans) ---
    country_ids = {r["country_id"] for r in countries}
    state_ids = {r["state_id"] for r in states}
    user_ids = {r["user_id"] for r in users}
    volunteer_user_ids = {r["user_id"] for r in volunteer_details}
    cat_ids = {r["cat_id"] for r in help_categories}

    for r in states:
        if r["country_id"] not in country_ids:
            fail(f"states: orphan country_id {r['country_id']}", errors)
    for r in cities:
        if r["state_id"] not in state_ids:
            fail(f"cities: orphan state_id {r['state_id']}", errors)
    for r in users:
        if r["state_id"] not in state_ids:
            fail(f"users: orphan state_id {r['state_id']}", errors)
        if r["country_id"] not in country_ids:
            fail(f"users: orphan country_id {r['country_id']}", errors)
    for r in volunteer_details:
        if r["user_id"] not in user_ids:
            fail(f"volunteer_details: orphan user_id {r['user_id']}", errors)
    for r in user_skills:
        if r["user_id"] not in user_ids:
            fail(f"user_skills: orphan user_id {r['user_id']}", errors)
        if r["cat_id"] not in cat_ids:
            fail(f"user_skills: orphan cat_id {r['cat_id']}", errors)
    for r in volunteer_locations:
        if r["user_id"] not in volunteer_user_ids:
            fail(f"volunteer_locations: orphan user_id {r['user_id']} (not in volunteer_details)", errors)
    for r in user_locations:
        if r["user_id"] not in user_ids:
            fail(f"user_locations: orphan user_id {r['user_id']}", errors)
    for r in organizations:
        if r["state_id"] not in state_ids:
            fail(f"organizations: orphan state_id {r['state_id']}", errors)

    # --- Geo coordinates parse ---
    ewkt_re = re.compile(r"^SRID=4326;POINT\((-?\d+\.?\d*) (-?\d+\.?\d*)\)$")
    for table_name, rows in [("volunteer_locations", volunteer_locations), ("user_locations", user_locations)]:
        for r in rows:
            for col in ("prev_loc", "curr_loc"):
                val = r[col]
                if val and not ewkt_re.match(val):
                    fail(f"{table_name}: malformed EWKT in {col}: {val!r}", errors)

    # --- Date ordering: created_at <= last_updated_at where both exist ---
    for r in volunteer_details:
        if r["created_at"] and r["last_updated_at"] and r["created_at"] > r["last_updated_at"]:
            fail(f"volunteer_details: created_at after last_updated_at for {r['user_id']}", errors)
    for r in organizations:
        if r["created_at"] and r["last_updated_at"] and r["created_at"] > r["last_updated_at"]:
            fail(f"organizations: created_at after last_updated_at for {r['org_id']}", errors)

    # --- No real-looking contact info (basic sanity) ---
    for r in users:
        if "example-mock.org" not in r["primary_email_address"]:
            fail(f"users: email does not look synthetic: {r['primary_email_address']}", errors)

    print(f"Rows: countries={len(countries)} states={len(states)} cities={len(cities)} "
          f"users={len(users)} volunteer_details={len(volunteer_details)} "
          f"user_skills={len(user_skills)} volunteer_locations={len(volunteer_locations)} "
          f"user_locations={len(user_locations)} help_categories={len(help_categories)} "
          f"organizations={len(organizations)}")

    if errors:
        print(f"\n{len(errors)} VALIDATION ERRORS:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("\nAll validation checks passed: unique PKs, no orphan FKs, "
              "valid EWKT coordinates, valid date ordering, synthetic-only contacts.")


if __name__ == "__main__":
    main()