#!/usr/bin/env python3
"""
Generate realistic synthetic mock data in CSV format for Virginia Analytics tables.
Adheres strictly to the Virginia database schema and referential integrity constraints.

Tables in Scope:
1. countries.csv
2. states.csv
3. cities.csv
4. users.csv
5. volunteer_details.csv
6. help_categories.csv
7. user_skills.csv
8. volunteer_locations.csv
9. user_locations.csv
10. organizations.csv
"""

import argparse
import os
import random
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

from geography import SEEDED_CITIES
from schema import BASE, DEFAULT_LOOKUP, EXPECTED_HEADERS
from utils import (
    AUTH_PROVIDERS,
    FIRST_NAMES,
    GENDERS,
    LAST_NAMES,
    MISSIONS,
    ORG_NAME_PREFIXES,
    ORG_NAME_SUFFIXES,
    ORG_SIZES,
    ORG_TYPES,
    SKILL_LEVELS,
    format_date,
    format_ts,
    generate_org_id,
    generate_sid,
    jitter_coordinates,
    json_text,
    point_pg,
    point_wkt,
    read_csv,
    set_seed,
    write_csv,
)

BASE_TIMESTAMP = datetime(2026, 1, 15, 8, 0, 0)


def get_random_timestamp_pair(base_offset_days: int = 0) -> Tuple[str, str]:
    """Generate a creation timestamp and an equal or later update timestamp."""
    created_dt = BASE_TIMESTAMP + timedelta(
        days=base_offset_days + random.randint(0, 100),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
        seconds=random.randint(0, 59),
    )
    update_delta_hours = random.randint(0, 720)  # up to 30 days later
    updated_dt = created_dt + timedelta(
        hours=update_delta_hours,
        minutes=random.randint(0, 59),
        seconds=random.randint(0, 59),
    )
    return format_ts(created_dt), format_ts(updated_dt)


def load_lookup_countries(lookup_path: str) -> List[Dict[str, Any]]:
    """Load and format countries lookup table matching latest Virginia schema."""
    countries_data = read_csv(lookup_path)
    if not countries_data:
        raise ValueError("Country lookup is empty")
    result = []
    for row in countries_data:
        is_eu = str(row.get("is_eu_member", "")).strip().lower() in ("true", "1", "t")
        result.append(
            {
                "country_id": int(row["country_id"]),
                "country_name": row["country_name"].strip(),
                "phone_code": row["phone_code"].strip(),
                "country_code": row["country_code"].strip(),
                "last_updated_at": format_ts(BASE_TIMESTAMP),
                "is_eu_member": is_eu,
            }
        )
    return result


def load_lookup_states(
    lookup_path: str, valid_country_ids: set
) -> List[Dict[str, Any]]:
    """Load and format states lookup table matching latest Virginia schema."""
    states_data = read_csv(lookup_path)
    if not states_data:
        raise ValueError("State lookup is empty")
    result = []
    for row in states_data:
        cid = int(row["country_id"])
        if cid not in valid_country_ids:
            raise ValueError(
                f"State {row['state_id']} references missing country {cid}"
            )
        result.append(
            {
                "state_id": row["state_id"].strip(),
                "country_id": cid,
                "state_name": row["state_name"].strip(),
                "state_code": row.get("state_code", "").strip() or "",
                "last_updated_at": format_ts(BASE_TIMESTAMP),
            }
        )
    return result


def load_lookup_categories(lookup_path: str) -> List[Dict[str, Any]]:
    """Load and format help_categories matching latest Virginia schema."""
    cat_data = read_csv(lookup_path)
    if not cat_data:
        raise ValueError("Help-category lookup is empty")
    result = []
    for row in cat_data:
        result.append(
            {
                "cat_id": row["cat_id"].strip(),
                "cat_name": row["cat_name"].strip(),
                "cat_desc": row["cat_desc"].strip(),
                "last_updated_at": format_ts(BASE_TIMESTAMP),
            }
        )
    return result


def generate_cities_data(
    count: int, states_list: List[Dict[str, Any]], state_id_to_country: Dict[str, int]
) -> List[Dict[str, Any]]:
    """
    Generate realistic cities with valid state_id foreign keys and accurate centroids.
    Schema columns: city_id, state_id, city_name, lattitude, longitude, last_updated_at
    """
    cities = []
    valid_state_ids = {s["state_id"]: s for s in states_list}

    # Confirm curated anchors still match the reference lookup identities.
    for seed in SEEDED_CITIES:
        state = valid_state_ids.get(seed["state_id"])
        if state and (
            state["state_code"] != seed["state_code"]
            or state_id_to_country[seed["state_id"]]
            != int(seed["state_id"].split(".")[0])
        ):
            raise ValueError(
                f"State lookup conflicts with city anchor: {seed['city_name']}"
            )

    # 1. First add the realistic seeded cities
    for seed in SEEDED_CITIES:
        if seed["state_id"] in valid_state_ids:
            city_id = len(cities) + 1
            cities.append(
                {
                    "city_id": city_id,
                    "state_id": seed["state_id"],
                    "city_name": seed["city_name"],
                    "lattitude": f"{seed['lat']:.6f}",
                    "longitude": f"{seed['lon']:.6f}",
                    "last_updated_at": format_ts(BASE_TIMESTAMP),
                    # Internal helper metadata for user generation
                    "_zip": seed.get("zip", "90001"),
                    "_tz": seed.get("tz", "UTC"),
                    "_lat_f": seed["lat"],
                    "_lon_f": seed["lon"],
                }
            )
            if len(cities) >= count:
                break

    # Lookup rows represent distinct places; do not pad them to an entity count.
    if not cities:
        raise ValueError("No supported city anchors match the state lookup")

    return cities


def generate_users_data(
    count: int,
    cities_list: List[Dict[str, Any]],
    state_id_to_country: Dict[str, int],
    country_id_to_obj: Dict[int, Dict[str, Any]],
    language_ids: List[int],
    status_ids: List[int],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Generate synthetic users complying with Virginia DB schema.
    Returns (users_rows, internal_user_metadata_with_coordinates).
    """
    users = []
    user_geo_metadata = []

    for i in range(1, count + 1):
        user_id = generate_sid(i)

        # Select city to anchor geographic consistency
        city = random.choice(cities_list)
        state_id = city["state_id"]
        country_id = state_id_to_country[state_id]
        country_obj = country_id_to_obj.get(country_id, {})
        is_eu = bool(country_obj.get("is_eu_member", False))

        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)
        middle_name = random.choice(FIRST_NAMES) if random.random() < 0.6 else ""
        full_name = " ".join(
            part for part in (first_name, middle_name, last_name) if part
        )

        email = f"{first_name.lower()}.{last_name.lower()}.{i}@example.com"
        phone_number = ""  # Nullable: no globally safe fictional phone range.

        addr_ln1 = f"Mock address {i:06d}, Synthetic Lane"
        addr_ln2 = f"Apt {random.randint(1, 99)}" if random.random() < 0.4 else ""
        addr_ln3 = ""

        city_name = city["city_name"]
        zip_code = city["_zip"]

        # User location near city centroid
        user_lat, user_lon = jitter_coordinates(
            city["_lat_f"], city["_lon_f"], radius_km=8.0
        )
        last_loc_pg = point_pg(user_lat, user_lon)

        created_at_str, updated_at_str = get_random_timestamp_pair(
            base_offset_days=i % 60
        )

        # Dates of birth span approximately 1960 through 2001.
        dob_dt = datetime(1960, 1, 1) + timedelta(days=random.randint(0, 15000))
        dob_str = format_date(dob_dt)

        selected_languages = random.sample(language_ids, min(3, len(language_ids)))
        lang1, lang2, lang3 = (selected_languages + [None] * 3)[:3]

        stage = random.randint(1, 5)
        promo_updated_at = updated_at_str
        auth_provider = random.choice(AUTH_PROVIDERS)
        gender = random.choice(GENDERS)
        tz = city["_tz"]
        profile_pic = f"https://example.com/profiles/user_{i:04d}.jpg"

        row = {
            "user_id": user_id,
            "state_id": state_id,
            "country_id": country_id,
            "user_status_id": random.choice(status_ids),
            "full_name": full_name,
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,
            "primary_email_address": email,
            "primary_phone_number": phone_number,
            "addr_ln1": addr_ln1,
            "addr_ln2": addr_ln2,
            "addr_ln3": addr_ln3,
            "city_name": city_name,
            "zip_code": zip_code,
            "last_location": last_loc_pg,
            "last_updated_at": updated_at_str,
            "time_zone": tz,
            "profile_picture_path": profile_pic,
            "gender": gender,
            "language_1": lang1,
            "language_2": lang2 if lang2 is not None else "",
            "language_3": lang3 if lang3 is not None else "",
            "promotion_wizard_stage": stage,
            "promotion_wizard_last_updated_at": promo_updated_at,
            "external_auth_provider": auth_provider,
            "dob": dob_str,
            "is_eu": is_eu,
        }
        users.append(row)

        user_geo_metadata.append(
            {
                "user_id": user_id,
                "lat": user_lat,
                "lon": user_lon,
                "city_name": city_name,
                "state_id": state_id,
                "country_id": country_id,
                "created_at": created_at_str,
                "last_updated_at": updated_at_str,
            }
        )

    return users, user_geo_metadata


def generate_volunteer_details_data(
    users_list: List[Dict[str, Any]],
    user_geo_metadata: List[Dict[str, Any]],
    count: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Generate volunteer_details records referencing valid users.
    Includes terms acceptance, document paths, availability, and timestamps.
            path1_updated_at, path2_updated_at, availability_days, availability_times,
            created_at, last_updated_at
    """
    volunteers = []
    volunteer_map = {}

    # Select subset or all users as volunteers
    target_count = min(count, len(users_list))
    selected_indices = random.sample(range(len(users_list)), target_count)

    days_options = [
        ["Monday", "Wednesday", "Friday"],
        ["Saturday", "Sunday"],
        ["Tuesday", "Thursday"],
        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        ["Saturday"],
        ["Sunday", "Monday"],
    ]

    times_options = [
        ["Morning (08:00 - 12:00)"],
        ["Afternoon (12:00 - 17:00)"],
        ["Evening (17:00 - 21:00)"],
        ["Morning (08:00 - 12:00)", "Evening (17:00 - 21:00)"],
        ["Flexible / On-Call"],
    ]

    for idx in selected_indices:
        u = users_list[idx]
        geo = user_geo_metadata[idx]
        user_id = u["user_id"]

        created_at_str, updated_at_str = get_random_timestamp_pair(
            base_offset_days=idx % 50
        )
        accepted_at_str = created_at_str
        path1_str = created_at_str
        path2_str = created_at_str

        doc1 = f"https://example.com/gov_ids/gov_doc1_{idx + 1:04d}.pdf"
        doc2 = (
            f"https://example.com/gov_ids/gov_doc2_{idx + 1:04d}.pdf"
            if random.random() < 0.5
            else ""
        )

        avail_days = random.choice(days_options)
        avail_times = random.choice(times_options)

        row = {
            "user_id": user_id,
            "terms_and_conditions": True,
            "terms_accepted_at": accepted_at_str,
            "govt_id_path1": doc1,
            "govt_id_path2": doc2,
            "path1_updated_at": path1_str,
            "path2_updated_at": path2_str if doc2 else "",
            "availability_days": json_text(avail_days),
            "availability_times": json_text(avail_times),
            "created_at": created_at_str,
            "last_updated_at": updated_at_str,
        }
        volunteers.append(row)
        volunteer_map[user_id] = geo

    return volunteers, volunteer_map


def generate_user_skills_data(
    users_list: List[Dict[str, Any]], categories_list: List[Dict[str, Any]], count: int
) -> List[Dict[str, Any]]:
    """
    Generate user_skills matching users and help categories.
    Schema: user_id, cat_id, skill_level, created_at, last_updated_at
    PK: (user_id, cat_id)
    """
    user_skills = []
    seen_pairs = set()

    cat_ids = [c["cat_id"] for c in categories_list if c["cat_id"] != "0.0.0.0.0"]
    if not cat_ids:
        cat_ids = [c["cat_id"] for c in categories_list]

    user_ids = [u["user_id"] for u in users_list]

    if count > len(user_ids) * len(cat_ids):
        raise ValueError("Requested skill count exceeds unique user/category pairs")

    # Distribute skills across users
    while len(user_skills) < count:
        uid = random.choice(user_ids)
        cid = random.choice(cat_ids)
        pair = (uid, cid)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        skill_lvl = random.choice(SKILL_LEVELS)
        created_at_str, updated_at_str = get_random_timestamp_pair()

        user_skills.append(
            {
                "user_id": uid,
                "cat_id": cid,
                "skill_level": skill_lvl,
                "created_at": created_at_str,
                "last_updated_at": updated_at_str,
            }
        )

    return user_skills


def generate_user_locations_data(
    user_geo_metadata: List[Dict[str, Any]], count: int
) -> List[Dict[str, Any]]:
    """
    Generate user_locations table rows.
    user_id references users.user_id directly.
    Both WKT geography points remain close to the user's city centroid.
    """
    user_locations = []
    target_count = min(count, len(user_geo_metadata))

    for geo in random.sample(user_geo_metadata, target_count):
        uid = geo["user_id"]

        lat = geo["lat"]
        lon = geo["lon"]

        # Offset the previous point by at most 2.5 km.
        prev_lat, prev_lon = jitter_coordinates(lat, lon, radius_km=2.5)
        # Offset the current point by at most 1 km.
        curr_lat, curr_lon = jitter_coordinates(lat, lon, radius_km=1.0)

        user_locations.append(
            {
                "user_id": uid,
                "prev_loc": point_wkt(prev_lon, prev_lat),
                "curr_loc": point_wkt(curr_lon, curr_lat),
                "last_updated_at": geo["last_updated_at"],
            }
        )

    return user_locations


def generate_volunteer_locations_data(
    volunteers_list: List[Dict[str, Any]],
    volunteer_geo_map: Dict[str, Dict[str, Any]],
    count: int,
) -> List[Dict[str, Any]]:
    """
    Generate volunteer_locations table rows.
    The user_id foreign key references volunteer_details, not users directly.
    """
    volunteer_locations = []
    target_count = min(count, len(volunteers_list))

    for idx in range(target_count):
        v = volunteers_list[idx]
        uid = v["user_id"]
        geo = volunteer_geo_map[uid]

        lat = geo["lat"]
        lon = geo["lon"]

        prev_lat, prev_lon = jitter_coordinates(lat, lon, radius_km=3.0)
        curr_lat, curr_lon = jitter_coordinates(lat, lon, radius_km=1.2)

        volunteer_locations.append(
            {
                "user_id": uid,
                "prev_loc": point_wkt(prev_lon, prev_lat),
                "curr_loc": point_wkt(curr_lon, curr_lat),
                "last_updated_at": v["last_updated_at"],
            }
        )

    return volunteer_locations


def generate_organizations_data(
    count: int, cities_list: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Generate organizations records adhering to Virginia DB schema and state references.
    Schema: org_id, org_name, street, city_name, state_id, zip_code, mission,
            web_url, phone, email, org_type, org_size, org_rating,
            is_collaborator, is_contributor, created_at, last_updated_at
    """
    orgs = []
    seen_names = set()

    for i in range(1, count + 1):
        org_id = generate_org_id(i)

        city = random.choice(cities_list)
        state_id = city["state_id"]
        city_name = city["city_name"]
        zip_code = city["_zip"]

        prefix = random.choice(ORG_NAME_PREFIXES)
        suffix = random.choice(ORG_NAME_SUFFIXES)
        org_name = f"{prefix} {suffix}"
        if org_name in seen_names:
            org_name = f"{prefix} {city_name} {suffix}"
        seen_names.add(org_name)
        org_name = org_name[:125]

        street = f"Mock organization {i:06d}, Synthetic Lane"
        mission = random.choice(MISSIONS)

        web_url = f"https://example.org/organizations/{i}"
        phone = ""
        email = f"organization{i}@example.org"

        org_type = random.choice(ORG_TYPES)
        org_size = random.choice(ORG_SIZES)
        org_rating = random.randint(1, 5)
        is_collab = random.choice([True, False])
        is_contrib = random.choice([True, False])

        created_at_str, updated_at_str = get_random_timestamp_pair(
            base_offset_days=i % 80
        )

        orgs.append(
            {
                "org_id": org_id,
                "org_name": org_name,
                "street": street,
                "city_name": city_name,
                "state_id": state_id,
                "zip_code": zip_code,
                "mission": mission,
                "web_url": web_url,
                "phone": phone,
                "email": email,
                "org_type": org_type,
                "org_size": org_size,
                "org_rating": org_rating,
                "is_collaborator": is_collab,
                "is_contributor": is_contrib,
                "created_at": created_at_str,
                "last_updated_at": updated_at_str,
            }
        )

    return orgs


def subset_count(total: int, fraction: float) -> int:
    """Round down a requested subset, retaining one row for positive fractions."""
    return max(1, int(total * fraction)) if fraction > 0 else 0


def main() -> None:
    """Generate, validate, and publish CSV fixtures from command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--count",
        type=int,
        default=400,
        help="Target row count for primary entity tables (default: 400)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic output (default: 42)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(BASE),
        help="Output directory for generated CSV files",
    )
    parser.add_argument(
        "--lookup-dir",
        type=str,
        default=str(DEFAULT_LOOKUP),
        help="Directory containing source lookup CSV files",
    )
    parser.add_argument(
        "--volunteer-fraction",
        type=float,
        default=0.6,
        help="Fraction of users with volunteer records, 0..1 (default: 0.6)",
    )
    parser.add_argument(
        "--user-location-fraction",
        type=float,
        default=0.8,
        help="Fraction of users with tracked locations, 0..1 (default: 0.8)",
    )
    args = parser.parse_args()
    for name in ("volunteer_fraction", "user_location_fraction"):
        if not 0 <= getattr(args, name) <= 1:
            parser.error(f"--{name.replace('_', '-')} must be between 0 and 1")

    set_seed(args.seed)
    output_dir = os.path.abspath(args.output_dir)
    lookup_dir = os.path.abspath(args.lookup_dir)
    if args.count <= 0:
        parser.error("--count must be a positive integer")
    required = (
        "country.csv",
        "state.csv",
        "help_categories.csv",
        "supporting_languages.csv",
        "user_status.csv",
    )
    for filename in required:
        if not os.path.isfile(os.path.join(lookup_dir, filename)):
            parser.error(
                f"Missing required lookup: {os.path.join(lookup_dir, filename)}"
            )
    language_ids = [
        int(r["language_id"])
        for r in read_csv(os.path.join(lookup_dir, "supporting_languages.csv"))
    ]
    status_ids = [
        int(r["user_status_id"])
        for r in read_csv(os.path.join(lookup_dir, "user_status.csv"))
    ]
    if not language_ids or not status_ids:
        parser.error("Language and user-status lookup tables must not be empty")

    os.makedirs(output_dir, exist_ok=True)
    print("=== Starting Virginia Mock Data Generation ===")
    print(f"Target count: {args.count} | Seed: {args.seed} | Output: {output_dir}")
    print(f"Lookup source: {lookup_dir}")

    # 1. Load / Generate Countries
    country_lookup = os.path.join(lookup_dir, "country.csv")
    countries = load_lookup_countries(country_lookup)

    valid_country_ids = {c["country_id"] for c in countries}
    country_id_to_obj = {c["country_id"]: c for c in countries}
    print(f"[1/10] Processed {len(countries)} countries")

    # 2. Load / Generate States
    state_lookup = os.path.join(lookup_dir, "state.csv")
    states = load_lookup_states(state_lookup, valid_country_ids)

    state_id_to_country = {s["state_id"]: s["country_id"] for s in states}
    print(f"[2/10] Processed {len(states)} states")

    # 3. Generate Cities
    cities = generate_cities_data(args.count, states, state_id_to_country)
    # Strip internal helper fields before writing
    clean_cities = [
        {
            "city_id": c["city_id"],
            "state_id": c["state_id"],
            "city_name": c["city_name"],
            "lattitude": c["lattitude"],
            "longitude": c["longitude"],
            "last_updated_at": c["last_updated_at"],
        }
        for c in cities
    ]
    print(f"[3/10] Generated {len(clean_cities)} cities")

    # 4. Generate Users
    users, user_geo_metadata = generate_users_data(
        args.count,
        cities,
        state_id_to_country,
        country_id_to_obj,
        language_ids,
        status_ids,
    )
    print(f"[4/10] Generated {len(users)} users")

    # 5. Generate Volunteer Details
    volunteer_details, volunteer_geo_map = generate_volunteer_details_data(
        users, user_geo_metadata, subset_count(args.count, args.volunteer_fraction)
    )
    print(f"[5/10] Generated {len(volunteer_details)} volunteer_details")

    # 6. Load Help Categories
    cat_lookup = os.path.join(lookup_dir, "help_categories.csv")
    help_categories = load_lookup_categories(cat_lookup)

    print(f"[6/10] Processed {len(help_categories)} help_categories")

    # 7. Generate User Skills
    user_skills = generate_user_skills_data(users, help_categories, args.count)
    print(f"[7/10] Generated {len(user_skills)} user_skills")

    # 8. Generate Volunteer Locations
    volunteer_locations = generate_volunteer_locations_data(
        volunteer_details, volunteer_geo_map, args.count
    )
    print(f"[8/10] Generated {len(volunteer_locations)} volunteer_locations")

    # 9. Generate User Locations
    user_locations = generate_user_locations_data(
        user_geo_metadata, subset_count(args.count, args.user_location_fraction)
    )
    print(f"[9/10] Generated {len(user_locations)} user_locations")

    # 10. Generate Organizations
    organizations = generate_organizations_data(args.count, cities)
    print(f"[10/10] Generated {len(organizations)} organizations")

    datasets = {
        "countries.csv": countries,
        "states.csv": states,
        "cities.csv": clean_cities,
        "users.csv": users,
        "volunteer_details.csv": volunteer_details,
        "help_categories.csv": help_categories,
        "user_skills.csv": user_skills,
        "user_locations.csv": user_locations,
        "volunteer_locations.csv": volunteer_locations,
        "organizations.csv": organizations,
    }
    # Validate every table before touching previously generated output files.
    with tempfile.TemporaryDirectory(prefix="saayam-mock-") as staging_dir:
        for filename, rows in datasets.items():
            write_csv(
                os.path.join(staging_dir, filename),
                rows,
                fieldnames=EXPECTED_HEADERS[filename],
            )
        from validate_mock_data import validate_dataset

        if not validate_dataset(staging_dir, lookup_dir):
            raise ValueError(
                "Generated data failed validation; existing output was preserved"
            )
        for filename in datasets:
            Path(output_dir, filename).write_bytes(
                Path(staging_dir, filename).read_bytes()
            )
    print(f"\n[SUCCESS] All 10 CSV files generated in {output_dir}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        raise SystemExit(f"Generation failed: {exc}") from None
