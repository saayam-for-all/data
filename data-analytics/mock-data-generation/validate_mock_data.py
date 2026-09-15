#!/usr/bin/env python3
"""
validate_mock_data.py
----------------------
Runs the data-quality checks listed in the task's acceptance criteria
against a directory of generated CSV files:

  - Primary keys unique per table
  - No orphan foreign keys (user_id, state_id, country_id, cat_id, etc.)
  - Geographic relationships logically consistent (state->country,
    city->state, org/user city_name actually belongs to their state)
  - created_at <= last_updated_at wherever both columns exist
  - Every file loads cleanly and has no empty required fields

Usage:
    python validate_mock_data.py --dir .
Exits non-zero if any check fails.
"""

import argparse
import csv
import os
import sys
from datetime import datetime

from utils import CITIES_BY_STATE

FAILURES = []


def fail(msg):
    FAILURES.append(msg)
    print(f"  [FAIL] {msg}")


def ok(msg):
    print(f"  [ OK ] {msg}")


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check_unique_pk(rows, pk_field, table_name):
    values = [r[pk_field] for r in rows]
    if len(values) == len(set(values)):
        ok(f"{table_name}.{pk_field} is unique ({len(values)} rows)")
    else:
        fail(f"{table_name}.{pk_field} has duplicate values")


def check_no_orphans(child_rows, child_fk_field, parent_ids, child_table, parent_table):
    orphans = [r for r in child_rows if r[child_fk_field] not in parent_ids]
    if not orphans:
        ok(f"No orphan {child_table}.{child_fk_field} values (all reference {parent_table})")
    else:
        fail(f"{len(orphans)} orphan {child_table}.{child_fk_field} values not found in {parent_table}")


def check_created_le_updated(rows, table_name, created_field="created_at", updated_field="last_updated_at"):
    if not rows or created_field not in rows[0] or updated_field not in rows[0]:
        return
    bad = 0
    fmt = "%Y-%m-%d %H:%M:%S"
    for r in rows:
        c = datetime.strptime(r[created_field], fmt)
        u = datetime.strptime(r[updated_field], fmt)
        if c > u:
            bad += 1
    if bad == 0:
        ok(f"{table_name}: created_at <= last_updated_at holds for all rows")
    else:
        fail(f"{table_name}: {bad} rows have created_at > last_updated_at")


def check_city_belongs_to_state(rows, table_name, state_id_to_name, city_field="city_name", state_field="state_id"):
    bad = 0
    for r in rows:
        state_name = state_id_to_name.get(r[state_field])
        valid_cities = {c[0] for c in CITIES_BY_STATE.get(state_name, [])}
        if r[city_field] not in valid_cities:
            bad += 1
    if bad == 0:
        ok(f"{table_name}: every city_name belongs to its state_id")
    else:
        fail(f"{table_name}: {bad} rows have a city_name that doesn't belong to their state_id")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=str, default=".", help="Directory containing the generated CSV files.")
    args = parser.parse_args()
    d = args.dir

    countries = read_csv(os.path.join(d, "countries.csv"))
    states = read_csv(os.path.join(d, "states.csv"))
    cities = read_csv(os.path.join(d, "cities.csv"))
    help_categories = read_csv(os.path.join(d, "help_categories.csv"))
    organizations = read_csv(os.path.join(d, "organizations.csv"))
    users = read_csv(os.path.join(d, "users.csv"))
    volunteer_details = read_csv(os.path.join(d, "volunteer_details.csv"))
    user_skills = read_csv(os.path.join(d, "user_skills.csv"))
    volunteer_locations = read_csv(os.path.join(d, "volunteer_locations.csv"))
    user_locations = read_csv(os.path.join(d, "user_locations.csv"))

    print("\n== Primary key uniqueness ==")
    check_unique_pk(countries, "country_id", "countries")
    check_unique_pk(states, "state_id", "states")
    check_unique_pk(cities, "city_id", "cities")
    check_unique_pk(help_categories, "cat_id", "help_categories")
    check_unique_pk(organizations, "org_id", "organizations")
    check_unique_pk(users, "user_id", "users")
    check_unique_pk(volunteer_details, "user_id", "volunteer_details")
    check_unique_pk(user_skills, "user_skill_id", "user_skills")
    check_unique_pk(volunteer_locations, "location_id", "volunteer_locations")
    check_unique_pk(user_locations, "location_id", "user_locations")

    print("\n== Foreign key integrity (no orphans) ==")
    country_ids = {c["country_id"] for c in countries}
    state_ids = {s["state_id"] for s in states}
    user_ids = {u["user_id"] for u in users}
    volunteer_user_ids = {v["user_id"] for v in volunteer_details}
    cat_ids = {c["cat_id"] for c in help_categories}

    check_no_orphans(states, "country_id", country_ids, "states", "countries")
    check_no_orphans(cities, "state_id", state_ids, "cities", "states")
    check_no_orphans(organizations, "state_id", state_ids, "organizations", "states")
    check_no_orphans(users, "country_id", country_ids, "users", "countries")
    check_no_orphans(users, "state_id", state_ids, "users", "states")
    check_no_orphans(volunteer_details, "user_id", user_ids, "volunteer_details", "users")
    check_no_orphans(user_skills, "user_id", user_ids, "user_skills", "users")
    check_no_orphans(user_skills, "cat_id", cat_ids, "user_skills", "help_categories")
    check_no_orphans(volunteer_locations, "user_id", volunteer_user_ids, "volunteer_locations", "volunteer_details")
    check_no_orphans(user_locations, "user_id", user_ids, "user_locations", "users")

    print("\n== Timestamp sanity ==")
    check_created_le_updated(organizations, "organizations")
    check_created_le_updated(users, "users")
    check_created_le_updated(volunteer_details, "volunteer_details")

    print("\n== Geographic consistency ==")
    state_id_to_name = {s["state_id"]: s["state_name"] for s in states}
    check_city_belongs_to_state(users, "users", state_id_to_name)
    check_city_belongs_to_state(organizations, "organizations", state_id_to_name)

    print("\n== Required-field completeness ==")
    for table_name, rows in [
        ("users", users),
        ("organizations", organizations),
        ("volunteer_details", volunteer_details),
    ]:
        blanks = sum(1 for r in rows for v in r.values() if v == "")
        if blanks == 0:
            ok(f"{table_name}: no blank required fields")
        else:
            fail(f"{table_name}: {blanks} blank field values found")

    print()
    if FAILURES:
        print(f"VALIDATION FAILED: {len(FAILURES)} issue(s) found.")
        sys.exit(1)
    else:
        print("VALIDATION PASSED: all checks green.")


if __name__ == "__main__":
    main()
