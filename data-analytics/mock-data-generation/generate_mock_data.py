#!/usr/bin/env python3
"""
generate_mock_data.py
----------------------
Generates fully synthetic mock CSV data for the Virginia analytics
database tables used by Saayam For All (Task 301):

    countries, states, cities, help_categories, organizations,
    users, volunteer_details, user_skills, volunteer_locations,
    user_locations

Usage
-----
    python generate_mock_data.py
    python generate_mock_data.py --num-users 400 --seed 7
    python generate_mock_data.py --output-dir ./out

See README.md for full details on schema assumptions, row-count
configuration, and validation.
"""

import argparse
import csv
import os
import random
from datetime import datetime

from faker import Faker

from utils import (
    COUNTRIES,
    STATES_BY_COUNTRY,
    CITIES_BY_STATE,
    HELP_CATEGORY_NAMES,
    SKILL_PROFICIENCY_LEVELS,
    jitter_coordinate,
    created_and_updated,
)

EARLIEST = datetime(2025, 1, 1, 0, 0, 0)
LATEST = datetime(2026, 8, 31, 14, 30, 0)


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"  wrote {len(rows):>5} rows -> {path}")


def gen_countries():
    """countries: country_id (PK), country_name"""
    rows = []
    for i, name in enumerate(COUNTRIES, start=1):
        rows.append({"country_id": i, "country_name": name})
    return rows


def gen_states(countries_rows):
    """states: state_id (PK), state_name, state_code, country_id (FK, NOT NULL)"""
    country_id_by_name = {r["country_name"]: r["country_id"] for r in countries_rows}
    rows = []
    state_id = 1
    for country_name, state_names in STATES_BY_COUNTRY.items():
        country_id = country_id_by_name[country_name]
        for state_name in state_names:
            code = "".join(w[0] for w in state_name.split())[:3].upper()
            rows.append(
                {
                    "state_id": state_id,
                    "state_name": state_name,
                    "state_code": code,
                    "country_id": country_id,
                }
            )
            state_id += 1
    return rows


def gen_cities(states_rows):
    """cities: city_id (PK), city_name, state_id (FK), latitude, longitude"""
    state_id_by_name = {r["state_name"]: r["state_id"] for r in states_rows}
    rows = []
    city_id = 1
    for state_name, city_list in CITIES_BY_STATE.items():
        state_id = state_id_by_name[state_name]
        for city_name, lat, lng in city_list:
            rows.append(
                {
                    "city_id": city_id,
                    "city_name": city_name,
                    "state_id": state_id,
                    "latitude": lat,
                    "longitude": lng,
                }
            )
            city_id += 1
    return rows


def gen_help_categories():
    """help_categories: cat_id (PK), cat_name, description"""
    rows = []
    for i, name in enumerate(HELP_CATEGORY_NAMES, start=1):
        rows.append(
            {
                "cat_id": i,
                "cat_name": name,
                "description": f"Assistance and resources related to {name.lower()}.",
            }
        )
    return rows


def gen_organizations(states_rows, num_orgs, rng, faker):
    """organizations: org_id (PK), org_name, state_id (FK), city_name, created_at, last_updated_at"""
    # Build state_id -> (state_name, list of cities) lookup so the org's
    # city_name is geographically valid for its state_id.
    state_id_to_name = {r["state_id"]: r["state_name"] for r in states_rows}
    rows = []
    for i in range(1, num_orgs + 1):
        state_id = rng.choice(list(state_id_to_name.keys()))
        state_name = state_id_to_name[state_id]
        city_name = rng.choice(CITIES_BY_STATE[state_name])[0]
        created_at, updated_at = created_and_updated(rng, EARLIEST, LATEST)
        rows.append(
            {
                "org_id": i,
                "org_name": f"{faker.company()} {rng.choice(['Foundation', 'Alliance', 'Network', 'Initiative', 'Coalition'])}",
                "state_id": state_id,
                "city_name": city_name,
                "created_at": created_at,
                "last_updated_at": updated_at,
            }
        )
    return rows


def gen_users(states_rows, num_users, rng, faker):
    """
    users: user_id (PK), first_name, last_name, email, phone_number,
           country_id (FK), state_id (FK), city_name (free text, not a FK),
           created_at, last_updated_at
    """
    state_id_to_country = {}
    state_id_to_name = {}
    for r in states_rows:
        state_id_to_country[r["state_id"]] = r["country_id"]
        state_id_to_name[r["state_id"]] = r["state_name"]

    rows = []
    for user_id in range(1, num_users + 1):
        state_id = rng.choice(list(state_id_to_name.keys()))
        state_name = state_id_to_name[state_id]
        country_id = state_id_to_country[state_id]
        city_name = rng.choice(CITIES_BY_STATE[state_name])[0]
        first_name = faker.first_name()
        last_name = faker.last_name()
        created_at, updated_at = created_and_updated(rng, EARLIEST, LATEST)
        rows.append(
            {
                "user_id": user_id,
                "first_name": first_name,
                "last_name": last_name,
                "email": f"{first_name.lower()}.{last_name.lower()}{user_id}@example-mail.com",
                "phone_number": faker.numerify("###-###-####"),
                "country_id": country_id,
                "state_id": state_id,
                "city_name": city_name,
                "created_at": created_at,
                "last_updated_at": updated_at,
            }
        )
    return rows


def gen_volunteer_details(users_rows, volunteer_fraction, rng, faker):
    """
    volunteer_details: user_id (PK + FK -> users.user_id), availability_hours_per_week,
                        skills_summary, is_active, created_at, last_updated_at
    A subset of users are volunteers (1:1 with users.user_id).
    """
    volunteer_user_ids = sorted(
        rng.sample(
            [u["user_id"] for u in users_rows],
            k=max(1, int(len(users_rows) * volunteer_fraction)),
        )
    )
    rows = []
    for user_id in volunteer_user_ids:
        created_at, updated_at = created_and_updated(rng, EARLIEST, LATEST)
        rows.append(
            {
                "user_id": user_id,
                "availability_hours_per_week": rng.choice([5, 10, 15, 20, 25]),
                "skills_summary": faker.sentence(nb_words=8),
                "is_active": rng.choice([True, True, True, False]),
                "created_at": created_at,
                "last_updated_at": updated_at,
            }
        )
    return rows


def gen_user_skills(users_rows, help_categories_rows, rng):
    """
    user_skills: user_skill_id (PK), user_id (FK -> users.user_id),
                 cat_id (FK -> help_categories.cat_id),
                 proficiency_level, created_at
    Each user gets 1-3 skills, no duplicate (user_id, cat_id) pairs.
    """
    cat_ids = [c["cat_id"] for c in help_categories_rows]
    rows = []
    user_skill_id = 1
    for u in users_rows:
        num_skills = rng.randint(1, 3)
        chosen_cats = rng.sample(cat_ids, k=min(num_skills, len(cat_ids)))
        for cat_id in chosen_cats:
            created_at, _ = created_and_updated(rng, EARLIEST, LATEST)
            rows.append(
                {
                    "user_skill_id": user_skill_id,
                    "user_id": u["user_id"],
                    "cat_id": cat_id,
                    "proficiency_level": rng.choice(SKILL_PROFICIENCY_LEVELS),
                    "created_at": created_at,
                }
            )
            user_skill_id += 1
    return rows


def gen_volunteer_locations(volunteer_details_rows, users_rows, states_rows, location_fraction, rng):
    """
    volunteer_locations: location_id (PK), user_id (FK -> volunteer_details.user_id),
                          curr_lat, curr_lng, prev_lat, prev_lng, updated_at
    curr_loc / prev_loc are stored as separate lat/lng column pairs.
    Coordinates are derived from the volunteer's own state/city so they land
    near a real point inside that state.
    """
    users_by_id = {u["user_id"]: u for u in users_rows}
    state_id_to_name = {r["state_id"]: r["state_name"] for r in states_rows}

    eligible_user_ids = [vd["user_id"] for vd in volunteer_details_rows]
    chosen_user_ids = sorted(
        rng.sample(eligible_user_ids, k=max(1, int(len(eligible_user_ids) * location_fraction)))
    )

    rows = []
    for location_id, user_id in enumerate(chosen_user_ids, start=1):
        user = users_by_id[user_id]
        state_name = state_id_to_name[user["state_id"]]
        city_name = user["city_name"]
        # find the matching city's centroid
        centroid = next(
            (c for c in CITIES_BY_STATE[state_name] if c[0] == city_name),
            CITIES_BY_STATE[state_name][0],
        )
        _, base_lat, base_lng = centroid
        curr_lat, curr_lng = jitter_coordinate(base_lat, base_lng, rng)
        prev_lat, prev_lng = jitter_coordinate(base_lat, base_lng, rng, spread=0.08)
        _, updated_at = created_and_updated(rng, EARLIEST, LATEST)
        rows.append(
            {
                "location_id": location_id,
                "user_id": user_id,
                "curr_lat": curr_lat,
                "curr_lng": curr_lng,
                "prev_lat": prev_lat,
                "prev_lng": prev_lng,
                "updated_at": updated_at,
            }
        )
    return rows


def gen_user_locations(users_rows, states_rows, location_fraction, rng):
    """
    user_locations: location_id (PK), user_id (FK -> users.user_id),
                     curr_lat, curr_lng, prev_lat, prev_lng, updated_at
    """
    state_id_to_name = {r["state_id"]: r["state_name"] for r in states_rows}
    chosen_users = sorted(
        rng.sample(users_rows, k=max(1, int(len(users_rows) * location_fraction))),
        key=lambda u: u["user_id"],
    )

    rows = []
    for location_id, user in enumerate(chosen_users, start=1):
        state_name = state_id_to_name[user["state_id"]]
        city_name = user["city_name"]
        centroid = next(
            (c for c in CITIES_BY_STATE[state_name] if c[0] == city_name),
            CITIES_BY_STATE[state_name][0],
        )
        _, base_lat, base_lng = centroid
        curr_lat, curr_lng = jitter_coordinate(base_lat, base_lng, rng)
        prev_lat, prev_lng = jitter_coordinate(base_lat, base_lng, rng, spread=0.08)
        _, updated_at = created_and_updated(rng, EARLIEST, LATEST)
        rows.append(
            {
                "location_id": location_id,
                "user_id": user["user_id"],
                "curr_lat": curr_lat,
                "curr_lng": curr_lng,
                "prev_lat": prev_lat,
                "prev_lng": prev_lng,
                "updated_at": updated_at,
            }
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic Virginia mock data CSVs.")
    parser.add_argument("--num-users", type=int, default=100, help="Number of user rows to generate (default: 100).")
    parser.add_argument("--num-orgs", type=int, default=100, help="Number of organization rows to generate (default: 100).")
    parser.add_argument("--volunteer-fraction", type=float, default=0.7, help="Fraction of users who are volunteers (default: 0.7).")
    parser.add_argument("--location-fraction", type=float, default=0.85, help="Fraction of eligible users who get a location row (default: 0.85).")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility (default: 42).")
    parser.add_argument("--output-dir", type=str, default=".", help="Directory to write CSV files to (default: current directory).")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    faker = Faker()
    Faker.seed(args.seed)

    os.makedirs(args.output_dir, exist_ok=True)

    print(f"Generating mock data (seed={args.seed}, num_users={args.num_users}, num_orgs={args.num_orgs}) ...")

    countries_rows = gen_countries()
    states_rows = gen_states(countries_rows)
    cities_rows = gen_cities(states_rows)
    help_categories_rows = gen_help_categories()
    organizations_rows = gen_organizations(states_rows, args.num_orgs, rng, faker)
    users_rows = gen_users(states_rows, args.num_users, rng, faker)
    volunteer_details_rows = gen_volunteer_details(users_rows, args.volunteer_fraction, rng, faker)
    user_skills_rows = gen_user_skills(users_rows, help_categories_rows, rng)
    volunteer_locations_rows = gen_volunteer_locations(
        volunteer_details_rows, users_rows, states_rows, args.location_fraction, rng
    )
    user_locations_rows = gen_user_locations(users_rows, states_rows, args.location_fraction, rng)

    out = args.output_dir
    write_csv(os.path.join(out, "countries.csv"), ["country_id", "country_name"], countries_rows)
    write_csv(os.path.join(out, "states.csv"), ["state_id", "state_name", "state_code", "country_id"], states_rows)
    write_csv(os.path.join(out, "cities.csv"), ["city_id", "city_name", "state_id", "latitude", "longitude"], cities_rows)
    write_csv(os.path.join(out, "help_categories.csv"), ["cat_id", "cat_name", "description"], help_categories_rows)
    write_csv(
        os.path.join(out, "organizations.csv"),
        ["org_id", "org_name", "state_id", "city_name", "created_at", "last_updated_at"],
        organizations_rows,
    )
    write_csv(
        os.path.join(out, "users.csv"),
        ["user_id", "first_name", "last_name", "email", "phone_number", "country_id", "state_id", "city_name", "created_at", "last_updated_at"],
        users_rows,
    )
    write_csv(
        os.path.join(out, "volunteer_details.csv"),
        ["user_id", "availability_hours_per_week", "skills_summary", "is_active", "created_at", "last_updated_at"],
        volunteer_details_rows,
    )
    write_csv(
        os.path.join(out, "user_skills.csv"),
        ["user_skill_id", "user_id", "cat_id", "proficiency_level", "created_at"],
        user_skills_rows,
    )
    write_csv(
        os.path.join(out, "volunteer_locations.csv"),
        ["location_id", "user_id", "curr_lat", "curr_lng", "prev_lat", "prev_lng", "updated_at"],
        volunteer_locations_rows,
    )
    write_csv(
        os.path.join(out, "user_locations.csv"),
        ["location_id", "user_id", "curr_lat", "curr_lng", "prev_lat", "prev_lng", "updated_at"],
        user_locations_rows,
    )

    print("Done.")


if __name__ == "__main__":
    main()
