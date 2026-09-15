"""Generate synthetic mock data CSVs for Saayam's Virginia analytics tables.

Issue: saayam-for-all/data#301

Produces 10 CSVs with valid foreign-key relationships and geographically
consistent coordinates, entirely from synthetic data - no real names,
emails, phone numbers, or addresses.

Usage:
    python generate_mock_data.py                # 100 users (default)
    python generate_mock_data.py --rows 400      # 400 users, scaled tables

Schema sources (see README.md "Schema Sources" section for full notes,
including real discrepancies found between these sources):
  - saayam-for-all/database wiki: "* Changes to the Database, Waiting for
    Microservice" (table/column DDL)
  - saayam-for-all/database wiki: "Importing CSV rows with geography
    parsing in cities table (EWKT / WKT / GeoJSON)" (coordinate format)
  - saayam-for-all/data: data-analytics/sql/*.csv (real current mock data,
    used to confirm actual-in-use column sets where they differ from DDL)
"""

from __future__ import annotations

import argparse
import random

import utils


def generate(num_users: int, seed: int) -> dict:
    utils.set_seed(seed)

    # ---------------- countries ----------------
    countries_rows = []
    country_id_by_code = {}
    for i, (name, phone_code, code, is_eu) in enumerate(utils.COUNTRIES, start=1):
        countries_rows.append([i, name, phone_code, code, utils.fmt_ts(utils.random_datetime(700, 400)), is_eu])
        country_id_by_code[code] = i
    us_country_id = country_id_by_code["US"]

    # ---------------- states (US only, tied to United States) ----------------
    states_rows = []
    state_ids = []
    for state_name, state_code in utils.US_STATES:
        states_rows.append([state_code, us_country_id, state_name, state_code,
                             utils.fmt_ts(utils.random_datetime(700, 400))])
        state_ids.append(state_code)

    # ---------------- cities ----------------
    cities_rows = []
    city_id_counter = 1
    cities_by_state_id = {}
    for state_code in state_ids:
        cities_by_state_id[state_code] = []
        for city_name, lat, lon in utils.CITIES_BY_STATE.get(state_code, []):
            cid = utils.make_city_id(city_id_counter)
            city_id_counter += 1
            cities_rows.append([cid, state_code, city_name, utils.jitter(lat, 0.02),
                                 utils.jitter(lon, 0.02),
                                 utils.fmt_ts(utils.random_datetime(700, 400))])
            cities_by_state_id[state_code].append((cid, city_name, lat, lon))

    # ---------------- users ----------------
    users_rows = []
    user_ids = []
    user_home = {}  # user_id -> (state_code, city_name, lat, lon)
    for i in range(1, num_users + 1):
        user_id = utils.make_user_id(i)
        state_code = random.choice(state_ids)
        city_id, city_name, lat, lon = random.choice(cities_by_state_id[state_code])
        u_lat, u_lon = utils.jitter(lat), utils.jitter(lon)
        first = random.choice(utils.FIRST_NAMES)
        last = random.choice(utils.LAST_NAMES)
        created, updated = utils.created_and_updated_pair(500)
        users_rows.append([
            user_id, state_code, us_country_id,
            random.choice([1, 2]),          # user_status_id (out-of-scope lookup; 1/2 placeholder)
            random.choice([1, 2, 3]),       # user_category_id (out-of-scope lookup; placeholder)
            f"{first} {last}", first, "", last,
            f"user{i}@example-mock.org", f"555-{100 + i:04d}",
            "", "", "",
            city_name, f"{10000 + i}",
            f"({u_lat}, {u_lon})",          # last_location - plain point per DDL example format
            updated,
            "America/New_York",
            "", random.choice(["M", "F", "Other"]),
            "", "", "",
            random.randint(0, 5), updated,
            "", "",
        ])
        user_ids.append(user_id)
        user_home[user_id] = (state_code, city_name, u_lat, u_lon)

    # ---------------- volunteer_details (subset of users) ----------------
    volunteer_ids = sorted(random.sample(user_ids, k=max(1, num_users // 2)))
    volunteer_details_rows = []
    for uid in volunteer_ids:
        created, updated = utils.created_and_updated_pair(400)
        volunteer_details_rows.append([
            uid, random.choice([True, False]), created,
            "", "", "", "",
            '["Mon","Wed","Fri"]', '{"start":"09:00","end":"17:00"}',
            created, updated, "", "", "", "",
        ])

    # ---------------- user_skills (each volunteer gets 1-4 skills) ----------------
    skill_choices = [c for c in utils.HELP_CATEGORIES if c[0] != "0.0.0.0.0"]
    user_skills_rows = []
    for uid in volunteer_ids:
        n_skills = random.randint(1, 4)
        picked = random.sample(skill_choices, k=min(n_skills, len(skill_choices)))
        for cat_id, _, _ in picked:
            created, updated = utils.created_and_updated_pair(300)
            user_skills_rows.append([uid, cat_id, created, updated])

    # ---------------- volunteer_locations (references volunteer_details.user_id) ----------------
    volunteer_locations_rows = []
    for uid in volunteer_ids:
        _, _, lat, lon = user_home[uid]
        prev = "" if random.random() < 0.3 else utils.to_ewkt(utils.jitter(lat, 0.05), utils.jitter(lon, 0.05))
        curr = utils.to_ewkt(utils.jitter(lat, 0.02), utils.jitter(lon, 0.02))
        _, updated = utils.created_and_updated_pair(200)
        volunteer_locations_rows.append([uid, prev, curr, updated])

    # ---------------- user_locations (references users.user_id directly) ----------------
    user_locations_rows = []
    for uid in user_ids:
        _, _, lat, lon = user_home[uid]
        prev = "" if random.random() < 0.3 else utils.to_ewkt(utils.jitter(lat, 0.05), utils.jitter(lon, 0.05))
        curr = utils.to_ewkt(utils.jitter(lat, 0.02), utils.jitter(lon, 0.02))
        _, updated = utils.created_and_updated_pair(200)
        user_locations_rows.append([uid, prev, curr, updated])

    # ---------------- help_categories (fixed lookup domain) ----------------
    help_categories_rows = [[cat_id, cat_name, cat_desc] for cat_id, cat_name, cat_desc in utils.HELP_CATEGORIES]

    # ---------------- organizations ----------------
    num_orgs = max(10, num_users // 2)
    organizations_rows = []
    used_org_names = set()
    for i in range(1, num_orgs + 1):
        org_id = utils.make_org_id(i)
        state_code = random.choice(state_ids)
        city_id, city_name, lat, lon = random.choice(cities_by_state_id[state_code])
        name = f"{random.choice(utils.ORG_NAME_PREFIXES)} {random.choice(utils.ORG_NAME_SUFFIXES)}"
        while name in used_org_names:
            name = f"{random.choice(utils.ORG_NAME_PREFIXES)} {random.choice(utils.ORG_NAME_SUFFIXES)} {i}"
        used_org_names.add(name)
        created, updated = utils.created_and_updated_pair(600)
        organizations_rows.append([
            org_id, name, f"{100 + i} Mock St", city_name, state_code, f"{20000 + i}",
            "Synthetic mission statement for mock/testing purposes only.",
            f"https://www.example-mock-{i}.org", f"555-{200 + i:04d}",
            f"contact{i}@example-mock.org",
            random.choice(utils.ORG_TYPES), random.choice(utils.ORG_SIZES),
            random.randint(1, 5), random.choice([True, False]), random.choice([True, False]),
            created, updated,
        ])

    return {
        "countries": (["country_id", "country_name", "phone_code", "country_code",
                        "last_update_date", "is_eu_member"], countries_rows),
        "states": (["state_id", "country_id", "state_name", "state_code", "last_update_date"], states_rows),
        "cities": (["city_id", "state_id", "city_name", "lattitude", "longitude", "last_updated_at"], cities_rows),
        "users": (["user_id", "state_id", "country_id", "user_status_id", "user_category_id",
                    "full_name", "first_name", "middle_name", "last_name",
                    "primary_email_address", "primary_phone_number",
                    "addr_ln1", "addr_ln2", "addr_ln3", "city_name", "zip_code",
                    "last_location", "last_update_date", "time_zone", "profile_picture_path",
                    "gender", "language_1", "language_2", "language_3",
                    "promotion_wizard_stage", "promotion_wizard_last_update_date",
                    "external_auth_provider", "dob"], users_rows),
        "volunteer_details": (["user_id", "terms_and_conditions", "terms_accepted_at",
                                 "govt_id_path1", "govt_id_path2", "path1_updated_at", "path2_updated_at",
                                 "availability_days", "availability_times", "created_at", "last_updated_at",
                                 "govt_id_expiry1", "govt_id_expiry2", "govt_id_name1", "govt_id_name2"],
                                volunteer_details_rows),
        "user_skills": (["user_id", "cat_id", "created_at", "last_updated_at"], user_skills_rows),
        "volunteer_locations": (["user_id", "prev_loc", "curr_loc", "last_updated_at"], volunteer_locations_rows),
        "user_locations": (["user_id", "prev_loc", "curr_loc", "last_updated_at"], user_locations_rows),
        "help_categories": (["cat_id", "cat_name", "cat_desc"], help_categories_rows),
        "organizations": (["org_id", "org_name", "street", "city_name", "state_id", "zip_code",
                             "mission", "web_url", "phone", "email", "org_type", "org_size",
                             "org_rating", "is_collaborator", "is_contributor",
                             "created_at", "last_updated_at"], organizations_rows),
    }


def main():
    parser = argparse.ArgumentParser(description="Generate Saayam mock data CSVs")
    parser.add_argument("--rows", type=int, default=100, help="Number of users to generate (default 100)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default 42)")
    parser.add_argument("--outdir", type=str, default=".", help="Output directory")
    args = parser.parse_args()

    tables = generate(args.rows, args.seed)
    for table_name, (header, rows) in tables.items():
        path = f"{args.outdir}/{table_name}.csv"
        utils.write_csv(path, header, rows)
        print(f"  {table_name}.csv: {len(rows)} rows")

    print(f"\nGenerated {len(tables)} CSV files from {args.rows} users (seed={args.seed}).")


if __name__ == "__main__":
    main()