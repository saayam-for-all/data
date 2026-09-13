"""
Validates the generated CSV files against the schema-compliance,
FK-integrity, and consistency rules from issue #301.

Usage: python validate_mock_data.py [--dir OUTPUT_DIR]

Exits non-zero (and prints every failure) if any check fails.
"""

import argparse
import csv
import os
import re
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

EXPECTED_SCHEMAS = {
    "countries.csv": ["country_id", "country_name", "phone_code", "country_code", "last_updated_at", "is_eu_member"],
    "states.csv": ["state_id", "country_id", "state_name", "state_code", "last_updated_at"],
    "cities.csv": ["city_id", "state_id", "city_name", "lattitude", "longitude", "last_updated_at"],
    "help_categories.csv": ["cat_id", "cat_name", "cat_desc", "last_updated_at"],
    "users.csv": [
        "user_id", "state_id", "country_id", "user_status_id", "full_name", "first_name",
        "middle_name", "last_name", "primary_email_address", "primary_phone_number",
        "addr_ln1", "addr_ln2", "addr_ln3", "city_name", "zip_code", "last_location",
        "last_updated_at", "time_zone", "profile_picture_path", "gender", "language_1",
        "language_2", "language_3", "promotion_wizard_stage", "promotion_wizard_last_updated_at",
        "external_auth_provider", "dob", "is_eu",
    ],
    "volunteer_details.csv": [
        "user_id", "terms_and_conditions", "terms_accepted_at", "govt_id_path1", "govt_id_path2",
        "path1_updated_at", "path2_updated_at", "availability_days", "availability_times",
        "created_at", "last_updated_at",
    ],
    "user_skills.csv": ["user_id", "cat_id", "skill_level", "created_at", "last_updated_at"],
    "volunteer_locations.csv": ["user_id", "prev_loc", "curr_loc", "last_updated_at"],
    "user_locations.csv": ["user_id", "prev_loc", "curr_loc", "last_updated_at"],
    "organizations.csv": [
        "org_id", "org_name", "street", "city_name", "state_id", "zip_code", "mission",
        "web_url", "phone", "email", "org_type", "org_size", "org_rating", "is_collaborator",
        "is_contributor", "created_at", "last_updated_at",
    ],
}

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EWKT_RE = re.compile(r"^SRID=4326;POINT\(-?\d+(\.\d+)? -?\d+(\.\d+)?\)$")
PG_POINT_RE = re.compile(r"^\(-?\d+(\.\d+)?,-?\d+(\.\d+)?\)$")

errors = []


def fail(msg: str) -> None:
    errors.append(msg)


def load(directory: str, name: str):
    path = os.path.join(directory, name)
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def check_schema(name: str, rows: list) -> None:
    if not rows:
        fail(f"{name}: no rows loaded")
        return
    actual = list(rows[0].keys())
    expected = EXPECTED_SCHEMAS[name]
    if actual != expected:
        fail(f"{name}: header mismatch.\n  expected: {expected}\n  actual:   {actual}")


def check_pk_unique(name: str, rows: list, key_fields) -> None:
    if isinstance(key_fields, str):
        key_fields = [key_fields]
    seen = set()
    for row in rows:
        key = tuple(row[f] for f in key_fields)
        if key in seen:
            fail(f"{name}: duplicate primary key {key}")
        seen.add(key)


def check_fk(child_name: str, child_rows: list, child_field: str, parent_ids: set,
             nullable: bool = False) -> None:
    for row in child_rows:
        value = row[child_field]
        if value == "":
            if not nullable:
                fail(f"{child_name}: {child_field} is empty but column is NOT NULL")
            continue
        if value not in parent_ids:
            fail(f"{child_name}: orphan {child_field}={value!r} (no matching parent row)")


def check_timestamp_fields(name: str, rows: list, fields, nullable_fields=()) -> None:
    for row in rows:
        for field in fields:
            value = row.get(field, "")
            if value == "":
                if field not in nullable_fields:
                    fail(f"{name}: {field} is empty")
                continue
            if not TS_RE.match(value):
                fail(f"{name}: {field}={value!r} is not a valid 'YYYY-MM-DD HH:MM:SS' timestamp")


def check_order(name: str, rows: list, earlier_field: str, later_field: str) -> None:
    for row in rows:
        earlier, later = row.get(earlier_field, ""), row.get(later_field, "")
        if not earlier or not later:
            continue
        try:
            e = datetime.strptime(earlier, "%Y-%m-%d %H:%M:%S")
            l = datetime.strptime(later, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if e > l:
            fail(f"{name}: {earlier_field} ({earlier}) > {later_field} ({later}) for row {row}")


def check_geo(name: str, rows: list, fields, nullable=True) -> None:
    for row in rows:
        for field in fields:
            value = row.get(field, "")
            if value == "":
                if not nullable:
                    fail(f"{name}: {field} is empty")
                continue
            if not EWKT_RE.match(value):
                fail(f"{name}: {field}={value!r} is not valid EWKT 'SRID=4326;POINT(lon lat)'")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=SCRIPT_DIR)
    args = parser.parse_args()

    countries = load(args.dir, "countries.csv")
    states = load(args.dir, "states.csv")
    cities = load(args.dir, "cities.csv")
    categories = load(args.dir, "help_categories.csv")
    users = load(args.dir, "users.csv")
    volunteer_details = load(args.dir, "volunteer_details.csv")
    user_skills = load(args.dir, "user_skills.csv")
    volunteer_locations = load(args.dir, "volunteer_locations.csv")
    user_locations = load(args.dir, "user_locations.csv")
    organizations = load(args.dir, "organizations.csv")

    all_tables = {
        "countries.csv": countries, "states.csv": states, "cities.csv": cities,
        "help_categories.csv": categories, "users.csv": users,
        "volunteer_details.csv": volunteer_details, "user_skills.csv": user_skills,
        "volunteer_locations.csv": volunteer_locations, "user_locations.csv": user_locations,
        "organizations.csv": organizations,
    }
    for name, rows in all_tables.items():
        check_schema(name, rows)

    # --- Primary keys -------------------------------------------------
    check_pk_unique("countries.csv", countries, "country_id")
    check_pk_unique("states.csv", states, "state_id")
    check_pk_unique("cities.csv", cities, "city_id")
    check_pk_unique("help_categories.csv", categories, "cat_id")
    check_pk_unique("users.csv", users, "user_id")
    check_pk_unique("volunteer_details.csv", volunteer_details, "user_id")
    check_pk_unique("user_skills.csv", user_skills, ["user_id", "cat_id"])
    check_pk_unique("volunteer_locations.csv", volunteer_locations, "user_id")
    check_pk_unique("user_locations.csv", user_locations, "user_id")
    check_pk_unique("organizations.csv", organizations, "org_id")

    # --- Foreign keys / no orphans --------------------------------------
    country_ids = {r["country_id"] for r in countries}
    state_ids = {r["state_id"] for r in states}
    user_ids = {r["user_id"] for r in users}
    volunteer_user_ids = {r["user_id"] for r in volunteer_details}
    cat_ids = {r["cat_id"] for r in categories}

    check_fk("states.csv", states, "country_id", country_ids, nullable=False)  # states.country_id NOT NULL
    check_fk("cities.csv", cities, "state_id", state_ids, nullable=False)
    check_fk("users.csv", users, "state_id", state_ids, nullable=True)
    check_fk("users.csv", users, "country_id", country_ids, nullable=True)
    check_fk("volunteer_details.csv", volunteer_details, "user_id", user_ids, nullable=False)
    check_fk("user_skills.csv", user_skills, "user_id", user_ids, nullable=False)
    check_fk("user_skills.csv", user_skills, "cat_id", cat_ids, nullable=False)
    check_fk("volunteer_locations.csv", volunteer_locations, "user_id", volunteer_user_ids, nullable=False)
    check_fk("user_locations.csv", user_locations, "user_id", user_ids, nullable=False)
    check_fk("organizations.csv", organizations, "state_id", state_ids, nullable=True)

    # --- Required (NOT NULL) fields --------------------------------------
    for row in countries:
        if not row["country_name"] or not row["phone_code"] or not row["country_code"]:
            fail(f"countries.csv: NOT NULL field empty in row {row}")
    for row in states:
        if not row["state_name"]:
            fail(f"states.csv: NOT NULL field empty in row {row}")
    for row in cities:
        if not row["city_name"]:
            fail(f"cities.csv: NOT NULL field empty in row {row}")
    for row in categories:
        if not row["cat_name"] or not row["cat_desc"]:
            fail(f"help_categories.csv: NOT NULL field empty in row {row}")
    for row in organizations:
        if not row["org_name"]:
            fail(f"organizations.csv: NOT NULL field empty in row {row}")
        if row["web_url"] and not row["web_url"].startswith("http"):
            fail(f"organizations.csv: web_url {row['web_url']!r} does not start with 'http'")
        if row["email"] and "@" not in row["email"]:
            fail(f"organizations.csv: email {row['email']!r} missing '@'")
        if row["org_rating"] and not (1 <= int(row["org_rating"]) <= 5):
            fail(f"organizations.csv: org_rating {row['org_rating']} out of range 1-5")
        if row["org_type"] not in {"non_profit", "for_profit"}:
            fail(f"organizations.csv: invalid org_type {row['org_type']!r}")
        if row["org_size"] not in {"small", "medium", "large"}:
            fail(f"organizations.csv: invalid org_size {row['org_size']!r}")

    for row in user_skills:
        if row["skill_level"] not in {"BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"}:
            fail(f"user_skills.csv: invalid skill_level {row['skill_level']!r}")

    # --- Timestamp / date validity --------------------------------------
    check_timestamp_fields("countries.csv", countries, ["last_updated_at"])
    check_timestamp_fields("states.csv", states, ["last_updated_at"])
    check_timestamp_fields("cities.csv", cities, ["last_updated_at"])
    check_timestamp_fields("help_categories.csv", categories, ["last_updated_at"])
    check_timestamp_fields("users.csv", users, ["last_updated_at"],
                            nullable_fields=[])
    check_timestamp_fields("users.csv", users, ["promotion_wizard_last_updated_at"],
                            nullable_fields=["promotion_wizard_last_updated_at"])
    check_timestamp_fields("volunteer_details.csv", volunteer_details, ["created_at", "last_updated_at"])
    check_timestamp_fields("volunteer_details.csv", volunteer_details,
                            ["terms_accepted_at", "path1_updated_at", "path2_updated_at"],
                            nullable_fields=["terms_accepted_at", "path1_updated_at", "path2_updated_at"])
    check_timestamp_fields("user_skills.csv", user_skills, ["created_at", "last_updated_at"])
    check_timestamp_fields("volunteer_locations.csv", volunteer_locations, ["last_updated_at"])
    check_timestamp_fields("user_locations.csv", user_locations, ["last_updated_at"])
    check_timestamp_fields("organizations.csv", organizations, ["created_at", "last_updated_at"])

    for row in users:
        if row["dob"] and not DATE_RE.match(row["dob"]):
            fail(f"users.csv: dob {row['dob']!r} is not a valid YYYY-MM-DD date")

    # created_at <= last_updated_at
    check_order("volunteer_details.csv", volunteer_details, "created_at", "last_updated_at")
    check_order("user_skills.csv", user_skills, "created_at", "last_updated_at")
    check_order("organizations.csv", organizations, "created_at", "last_updated_at")

    # --- Geography (EWKT) fields -----------------------------------------
    check_geo("volunteer_locations.csv", volunteer_locations, ["prev_loc", "curr_loc"])
    check_geo("user_locations.csv", user_locations, ["prev_loc", "curr_loc"])

    for row in users:
        if row["last_location"] and not PG_POINT_RE.match(row["last_location"]):
            fail(f"users.csv: last_location {row['last_location']!r} is not a valid '(lat,lon)' point")

    # --- Report -----------------------------------------------------------
    if errors:
        print(f"FAILED: {len(errors)} validation issue(s) found\n")
        for e in errors:
            print(f" - {e}")
        return 1

    print("All validation checks passed:")
    for name, rows in all_tables.items():
        print(f"  {name:<26} {len(rows):>5} rows OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
