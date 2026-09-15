"""Mock data generator for issue #301 - dashboard implementation & testing.

Generates 10 CSVs (countries, states, cities, users, organizations,
volunteer_details, user_skills, volunteer_locations, user_locations,
help_categories) with unique primary keys, valid foreign keys, and
geographically plausible coordinates. All data is synthetic; countries,
states, and help_categories are copied from the repo's existing public
reference data (see README "Design Decisions").

Usage:
    python generate_mock_data.py [--count N] [--seed S] [--output-dir DIR]
    python generate_mock_data.py --validate-only
"""
import argparse
import os
import random
import re
from datetime import datetime, timedelta

from utils import (
    AUTH_PROVIDERS,
    CITY_NAME_SUFFIXES,
    DEFAULT_COUNT,
    DEFAULT_SEED,
    FIRST_NAMES,
    GENDERS,
    GOVT_ID_NAMES,
    LAST_NAMES,
    MISSIONS,
    ORG_NAME_CORE,
    ORG_NAME_SUFFIX,
    ORG_SIZES,
    ORG_TYPES,
    SEED_CITIES,
    STATE_TIMEZONES,
    TABLE_FILENAMES,
    bool_str,
    created_and_updated,
    format_date,
    format_ts,
    jitter_point,
    json_text,
    load_all_csvs,
    load_reference_rows,
    make_org_id,
    make_user_id,
    random_datetime_between,
    set_seed,
    to_wkt_point,
    validate_all,
    write_csv,
)


def generate_countries(sql_dir):
    return load_reference_rows(os.path.join(sql_dir, "country.csv"))


def generate_help_categories(sql_dir):
    return load_reference_rows(os.path.join(sql_dir, "help_category.csv"))


def generate_states(sql_dir):
    rows = load_reference_rows(os.path.join(sql_dir, "state.csv"))
    for row in rows:
        # Bug fix: the sibling data has country_id=1 (Afghanistan) for every
        # US state; the real USA row in country.csv is country_id=233.
        row["country_id"] = "233"
    return rows


def generate_cities(states, count):
    candidates = []
    for state in states:
        sid = state["state_id"]
        for name, lat, lon in SEED_CITIES.get(sid, []):
            candidates.append((sid, name, lat, lon))
    random.shuffle(candidates)

    if count <= len(candidates):
        chosen = candidates[:count]
    else:
        chosen = list(candidates)
        idx = 0
        while len(chosen) < count:
            sid, name, lat, lon = candidates[idx % len(candidates)]
            new_lat, new_lon = jitter_point(lat, lon, max_delta=0.3)
            new_name = f"{name} {random.choice(CITY_NAME_SUFFIXES)}"
            chosen.append((sid, new_name, new_lat, new_lon))
            idx += 1

    rows = []
    for i, (sid, name, lat, lon) in enumerate(chosen, start=1):
        _, updated = created_and_updated()
        rows.append({
            "city_id": str(i),
            "state_id": sid,
            "city_name": name,
            "lattitude": f"{lat:.6f}",
            "longitude": f"{lon:.6f}",
            "last_update_date": format_ts(updated),
        })
    return rows


def build_city_by_state(cities):
    mapping = {}
    for row in cities:
        mapping.setdefault(row["state_id"], []).append(row)
    return mapping


def generate_users(states, city_by_state, count):
    eligible_states = [s for s in states if s["state_id"] in city_by_state]
    rows = []
    geo_by_user = {}
    for i in range(1, count + 1):
        state = random.choice(eligible_states)
        city = random.choice(city_by_state[state["state_id"]])
        lat, lon = jitter_point(float(city["lattitude"]), float(city["longitude"]), max_delta=0.05)
        user_id = make_user_id(i)

        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        middle = random.choice(LAST_NAMES) if random.random() < 0.3 else ""
        full_name = f"{first} {middle + ' ' if middle else ''}{last}".strip()

        _, updated = created_and_updated()
        dob = random_datetime_between(datetime(1955, 1, 1), datetime(2005, 12, 31))

        rows.append({
            "user_id": user_id,
            "state_id": state["state_id"],
            "country_id": "233",
            "user_status_id": str(random.randint(1, 3)),
            "user_category_id": str(random.randint(1, 3)),
            "full_name": full_name,
            "first_name": first,
            "middle_name": middle,
            "last_name": last,
            "primary_email_address": f"{first.lower()}.{last.lower()}{i}@mock.saayam.test",
            "primary_phone_number": f"+1555{i:06d}",
            "addr_ln1": f"{100 + i} Main St",
            "addr_ln2": "",
            "addr_ln3": "",
            "city_name": city["city_name"],
            "zip_code": f"{10000 + (i * 37) % 90000:05d}",
            "last_location": to_wkt_point(lat, lon),
            "last_update_date": format_ts(updated),
            "time_zone": STATE_TIMEZONES.get(state["state_id"], "America/New_York"),
            "profile_picture_path": f"/uploads/profile/{user_id}.jpg" if random.random() < 0.5 else "",
            "gender": random.choice(GENDERS),
            "language_1": "English",
            "language_2": random.choice(["", "Spanish", "Hindi", "Mandarin", "French"]),
            "language_3": "",
            "promotion_wizard_stage": str(random.randint(0, 5)),
            "promotion_wizard_last_update_date": format_ts(updated),
            "external_auth_provider": random.choice(AUTH_PROVIDERS),
            "dob": format_date(dob),
        })
        geo_by_user[user_id] = (lat, lon)
    return rows, geo_by_user


def generate_organizations(states, city_by_state, count):
    eligible_states = [s for s in states if s["state_id"] in city_by_state]
    rows = []
    for i in range(1, count + 1):
        state = random.choice(eligible_states)
        city = random.choice(city_by_state[state["state_id"]])
        org_name = f"{random.choice(ORG_NAME_CORE)} {random.choice(ORG_NAME_SUFFIX)}"
        slug = re.sub(r"[^a-z0-9]", "", org_name.lower())[:20] or f"org{i}"
        created, updated = created_and_updated()

        rows.append({
            "org_id": make_org_id(i),
            "org_name": org_name,
            "street": f"{200 + i} Liberty Ave",
            "city_name": city["city_name"],
            "state_id": state["state_id"],
            "zip_code": f"{20000 + (i * 53) % 79000:05d}",
            "mission": random.choice(MISSIONS),
            "web_url": f"https://www.{slug}.org",
            "phone": f"(555) {100 + i:03d}-{1000 + i:04d}",
            "email": f"contact@{slug}.org",
            "org_type": random.choice(ORG_TYPES),
            "org_size": random.choice(ORG_SIZES),
            "org_rating": str(random.randint(1, 5)),
            "is_collaborator": bool_str(random.random() < 0.5),
            "is_contributor": bool_str(random.random() < 0.5),
            "created_at": format_ts(created),
            "last_updated_at": format_ts(updated),
        })
    return rows


def generate_volunteer_details(users, ratio=0.6):
    selected = random.sample(users, k=max(1, int(len(users) * ratio)))
    rows = []
    for user in selected:
        created, updated = created_and_updated()
        has_path2 = random.random() < 0.5

        rows.append({
            "user_id": user["user_id"],
            "terms_and_conditions": bool_str(random.random() < 0.95),
            "terms_accepted_at": format_ts(created),
            "govt_id_path1": f"/uploads/govt_id/{user['user_id']}_1.pdf",
            "govt_id_path2": f"/uploads/govt_id/{user['user_id']}_2.pdf" if has_path2 else "",
            "path1_updated_at": format_ts(updated),
            "path2_updated_at": format_ts(updated) if has_path2 else "",
            "availability_days": json_text(
                random.sample(
                    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
                    k=random.randint(2, 4),
                )
            ),
            "availability_times": json_text({
                "weekdays": random.choice(["morning", "afternoon", "evening"]),
                "weekends": random.choice(["morning", "afternoon", "evening"]),
            }),
            "created_at": format_ts(created),
            "last_updated_at": format_ts(updated),
            "govt_id_expiry1": format_date(updated + timedelta(days=365 * 3)),
            "govt_id_expiry2": format_date(updated + timedelta(days=365 * 3)) if has_path2 else "",
            "govt_id_name1": random.choice(GOVT_ID_NAMES),
            "govt_id_name2": random.choice(GOVT_ID_NAMES) if has_path2 else "",
        })
    return rows


def generate_user_skills(users, help_categories, ratio=0.7, min_skills=2, max_skills=4):
    cat_ids = [c["cat_id"] for c in help_categories]
    selected = random.sample(users, k=max(1, int(len(users) * ratio)))
    rows = []
    for user in selected:
        k = min(random.randint(min_skills, max_skills), len(cat_ids))
        created, updated = created_and_updated()
        for cat_id in random.sample(cat_ids, k=k):
            rows.append({
                "user_id": user["user_id"],
                "cat_id": cat_id,
                "created_at": format_ts(created),
                "last_updated_at": format_ts(updated),
            })
    return rows


def _generate_location_rows(entity_rows, geo_by_user):
    """Shared by volunteer_locations and user_locations - both are
    user_id + prev_loc/curr_loc/last_updated_at, just scoped to a
    different parent set of rows."""
    rows = []
    for entity in entity_rows:
        user_id = entity["user_id"]
        lat, lon = geo_by_user[user_id]
        prev_wkt = ""
        if random.random() < 0.8:
            prev_lat, prev_lon = jitter_point(lat, lon, max_delta=0.1)
            prev_wkt = to_wkt_point(prev_lat, prev_lon)
        curr_lat, curr_lon = jitter_point(lat, lon, max_delta=0.05)
        _, updated = created_and_updated()

        rows.append({
            "user_id": user_id,
            "prev_loc": prev_wkt,
            "curr_loc": to_wkt_point(curr_lat, curr_lon),
            "last_updated_at": format_ts(updated),
        })
    return rows


def generate_volunteer_locations(volunteer_details, geo_by_user):
    return _generate_location_rows(volunteer_details, geo_by_user)


def generate_user_locations(users, geo_by_user):
    return _generate_location_rows(users, geo_by_user)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT,
                         help="Row count for cities/users/organizations (default: 100)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                         help="Random seed for reproducibility (default: 42)")
    parser.add_argument("--output-dir", default=os.path.dirname(os.path.abspath(__file__)),
                         help="Directory to write CSVs into (default: this script's directory)")
    parser.add_argument("--validate-only", action="store_true",
                         help="Skip generation; validate existing CSVs in --output-dir")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.validate_only:
        tables = load_all_csvs(args.output_dir)
        errors = validate_all(tables)
        if errors:
            print(f"VALIDATION FAILED - {len(errors)} issue(s):")
            for error in errors:
                print(f"  - {error}")
            raise SystemExit(1)
        print("Validation passed - no issues found.")
        return

    set_seed(args.seed)
    os.makedirs(args.output_dir, exist_ok=True)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sql_dir = os.path.join(script_dir, "..", "sql")

    countries = generate_countries(sql_dir)
    help_categories = generate_help_categories(sql_dir)
    states = generate_states(sql_dir)
    cities = generate_cities(states, args.count)
    city_by_state = build_city_by_state(cities)
    users, geo_by_user = generate_users(states, city_by_state, args.count)
    organizations = generate_organizations(states, city_by_state, args.count)
    volunteer_details = generate_volunteer_details(users)
    user_skills = generate_user_skills(users, help_categories)
    volunteer_locations = generate_volunteer_locations(volunteer_details, geo_by_user)
    user_locations = generate_user_locations(users, geo_by_user)

    tables = {
        "countries": countries,
        "help_categories": help_categories,
        "states": states,
        "cities": cities,
        "users": users,
        "organizations": organizations,
        "volunteer_details": volunteer_details,
        "user_skills": user_skills,
        "volunteer_locations": volunteer_locations,
        "user_locations": user_locations,
    }

    for table, rows in tables.items():
        path = os.path.join(args.output_dir, TABLE_FILENAMES[table])
        write_csv(path, rows)
        print(f"Generated {len(rows)} {table} rows -> {TABLE_FILENAMES[table]}")

    errors = validate_all(tables)
    if errors:
        print(f"\nVALIDATION FAILED - {len(errors)} issue(s):")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)
    print("\nValidation passed - no issues found.")


if __name__ == "__main__":
    main()
