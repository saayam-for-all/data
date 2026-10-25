#!/usr/bin/env python3
"""Generate synthetic mock-data CSVs for the Virginia analytics tables.

Tables: countries, states, cities, help_categories, users, volunteer_details,
user_skills, volunteer_locations, user_locations, organizations.

Only the Python standard library is needed. Output is deterministic for a given
--seed / --as-of / row-count combination.

    python generate_mock_data.py                    # defaults: 400 users
    python generate_mock_data.py --users 5000       # scale everything up
    python generate_mock_data.py --users 100 --volunteers 30 --organizations 50

See readme.md for the full option list and the validation steps.
"""

import argparse
import json
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pools
import schema
from utils import (
    chance, ewkt_point, fictional_phone, jitter_point, pg_point, postal_code,
    rand_after, rand_datetime, read_reference_csv, weighted_choice, write_csv,
)

HERE = Path(__file__).resolve().parent
REFERENCE_DIR = HERE / "reference_data"

TIMELINE_START = datetime(2025, 1, 1)      # earliest user / volunteer activity
ORG_TIMELINE_START = datetime(2023, 1, 1)  # organizations pre-date most users
REFERENCE_UPDATED_RANGE = (datetime(2025, 1, 1), datetime(2025, 6, 30))  # lookup tables

# Share of users per country (ISO alpha-3, as in countries.country_code). Only
# countries that actually have cities in the reference data are used.
COUNTRY_WEIGHTS: Dict[str, float] = {"USA": 0.66, "IND": 0.15, "DEU": 0.08, "CAN": 0.06, "AUS": 0.05}

USER_STATUS_ACTIVE = 1  # the only user_status lookup value
SKILL_LEVEL_WEIGHTS = [("BEGINNER", 0.20), ("INTERMEDIATE", 0.35), ("ADVANCED", 0.30), ("EXPERT", 0.15)]
ORG_TYPE_WEIGHTS = [("non_profit", 0.85), ("for_profit", 0.15)]
ORG_SIZE_WEIGHTS = [("small", 0.50), ("medium", 0.32), ("large", 0.18)]
ORG_RATING_WEIGHTS = [(1, 0.03), (2, 0.07), (3, 0.20), (4, 0.40), (5, 0.30)]
GENERAL_CATEGORY_ID = "0.0.0.0.0"  # placeholder category, never assigned as a skill
MAX_USER_ID_NUMBER = 999_999


# --- Configuration ------------------------------------------------------------------
@dataclass
class Config:
    """Row counts and knobs. Anything left None is derived from `users`."""

    users: int = 400
    volunteers: Optional[int] = None            # default: users // 2
    user_skills: Optional[int] = None           # default: users
    organizations: Optional[int] = None         # default: users
    user_locations: Optional[int] = None        # default: every user with a city
    volunteer_locations: Optional[int] = None   # default: every volunteer with a city
    cities: Optional[int] = None                # default: every city in reference_data/cities.csv
    seed: int = 42
    as_of: datetime = datetime(2026, 9, 20)     # no generated timestamp is later than this
    incomplete_profile_rate: float = 0.0        # share of users with no state/city/address
    output_dir: Path = HERE

    def resolve(self) -> "Config":
        if self.users < 0 or self.users > MAX_USER_ID_NUMBER:
            raise ValueError(f"--users must be between 0 and {MAX_USER_ID_NUMBER}")
        if self.volunteers is None:
            self.volunteers = self.users // 2
        if self.user_skills is None:
            self.user_skills = self.users
        if self.organizations is None:
            self.organizations = self.users
        if self.volunteers > self.users:
            raise ValueError("--volunteers cannot exceed --users (every volunteer is a user)")
        if not 0.0 <= self.incomplete_profile_rate <= 1.0:
            raise ValueError("--incomplete-profile-rate must be between 0 and 1")
        return self


# --- Geography (countries / states / cities) -------------------------------------------
@dataclass
class Geography:
    countries: List[Dict[str, Any]]
    states: List[Dict[str, Any]]
    cities: List[Dict[str, Any]]           # CSV rows
    city_info: List[Dict[str, Any]]        # same order; adds country/state codes, zip prefix, tz
    country_by_code: Dict[str, Dict[str, Any]]
    cities_by_country: Dict[str, List[Dict[str, Any]]]
    cities_by_state: Dict[str, List[Dict[str, Any]]]


def build_geography(rng: random.Random, cfg: Config) -> Geography:
    lo, hi = REFERENCE_UPDATED_RANGE

    countries = []
    for r in read_reference_csv(REFERENCE_DIR / "countries.csv"):
        countries.append({
            "country_id": int(r["country_id"]),
            "country_name": r["country_name"],
            "phone_code": r["phone_code"],
            "country_code": r["country_code"],
            "last_updated_at": rand_datetime(rng, lo, hi),
            "is_eu_member": r["is_eu_member"] == "true",
        })
    country_by_code = {c["country_code"]: c for c in countries}
    country_by_id = {c["country_id"]: c for c in countries}

    states = []
    for r in read_reference_csv(REFERENCE_DIR / "states.csv"):
        if int(r["country_id"]) not in country_by_id:
            raise ValueError(f"state {r['state_id']} references unknown country_id {r['country_id']}")
        states.append({
            "state_id": r["state_id"],
            "country_id": int(r["country_id"]),
            "state_name": r["state_name"],
            "state_code": r["state_code"] or None,
            "last_updated_at": rand_datetime(rng, lo, hi),
        })
    state_by_key = {(country_by_id[s["country_id"]]["country_code"], s["state_code"]): s for s in states}

    seeds = read_reference_csv(REFERENCE_DIR / "cities.csv")
    if cfg.cities is not None and cfg.cities < len(seeds):
        keep = set(rng.sample(range(len(seeds)), cfg.cities))
        seeds = [s for i, s in enumerate(seeds) if i in keep]
    elif cfg.cities is not None and cfg.cities > len(seeds):
        warn(f"--cities {cfg.cities} exceeds the {len(seeds)} cities in reference_data/cities.csv; "
             f"generating {len(seeds)}")

    cities, city_info = [], []
    for i, s in enumerate(seeds, start=1):
        state = state_by_key.get((s["country_code"], s["state_code"]))
        if state is None:
            raise ValueError(f"city {s['city_name']!r}: no state {s['state_code']} in {s['country_code']}")
        row = {
            "city_id": i,
            "state_id": state["state_id"],
            "city_name": s["city_name"],
            "lattitude": f"{float(s['latitude']):.6f}",
            "longitude": f"{float(s['longitude']):.6f}",
            "last_updated_at": rand_datetime(rng, lo, hi),
        }
        cities.append(row)
        city_info.append({
            **row,
            "country_code": s["country_code"],
            "state_code": s["state_code"],
            "lat": float(s["latitude"]),
            "lon": float(s["longitude"]),
            "zip_prefix": s["zip_prefix"],
            "time_zone": s["time_zone"],
        })

    cities_by_country: Dict[str, List[Dict[str, Any]]] = {}
    cities_by_state: Dict[str, List[Dict[str, Any]]] = {}
    for c in city_info:
        cities_by_country.setdefault(c["country_code"], []).append(c)
        cities_by_state.setdefault(c["state_id"], []).append(c)

    return Geography(countries, states, cities, city_info, country_by_code, cities_by_country, cities_by_state)


def pick_city(rng: random.Random, geo: Geography) -> Dict[str, Any]:
    """Choose a country by COUNTRY_WEIGHTS, then a city uniformly within it."""
    options = [(cc, w) for cc, w in COUNTRY_WEIGHTS.items() if geo.cities_by_country.get(cc)]
    if not options:
        raise ValueError("no cities available for any weighted country")
    return rng.choice(geo.cities_by_country[weighted_choice(rng, options)])


# --- help_categories ----------------------------------------------------------------------
def build_help_categories(rng: random.Random) -> List[Dict[str, Any]]:
    lo, hi = REFERENCE_UPDATED_RANGE
    return [
        {**r, "last_updated_at": rand_datetime(rng, lo, hi)}
        for r in read_reference_csv(REFERENCE_DIR / "help_categories.csv")
    ]


# --- users ---------------------------------------------------------------------------------
def make_user_ids(rng: random.Random, count: int) -> List[str]:
    """Unique, obviously-mock IDs in the SID-xx-xxx-xxx-xxx shape. The group '99'
    (real IDs use '00') keeps them distinguishable from production IDs."""
    numbers = rng.sample(range(1, MAX_USER_ID_NUMBER + 1), count)
    return [f"SID-99-000-{n // 1000:03d}-{n % 1000:03d}" for n in numbers]


def street_address(rng: random.Random, country_code: str) -> str:
    if country_code == "DEU":
        return f"{rng.choice(pools.GERMAN_STREET_STEMS)}strasse {rng.randint(1, 150)}"
    if country_code == "IND":
        return f"{rng.randint(1, 999)}, {rng.choice(pools.STREET_NAMES)} Road"
    return f"{rng.randint(1, 9899)} {rng.choice(pools.STREET_NAMES)} {rng.choice(pools.STREET_SUFFIXES)}"


def pick_languages(rng: random.Random, country_code: str, state_code: Optional[str]) -> List[Optional[int]]:
    if (country_code == "IND" and state_code in pools.INDIA_STATE_LANGUAGE and chance(rng, 0.7)):
        first = pools.INDIA_STATE_LANGUAGE[state_code]
    else:
        first = weighted_choice(rng, pools.PRIMARY_LANGUAGES[country_code])
    langs: List[Optional[int]] = [first]
    for probability in (0.60, 0.25):
        options = [x for x in pools.SECONDARY_LANGUAGES[country_code] if x not in langs]
        if not options or not chance(rng, probability):
            break
        langs.append(rng.choice(options))
    return langs + [None] * (3 - len(langs))


def build_users(
    rng: random.Random, cfg: Config, geo: Geography, user_ids: List[str], volunteer_ids: set
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Returns (rows, user_id -> city_info for users that have a city)."""
    rows: List[Dict[str, Any]] = []
    user_city: Dict[str, Dict[str, Any]] = {}
    as_of_date = cfg.as_of.date()

    for i, uid in enumerate(user_ids, start=1):
        city = pick_city(rng, geo)
        cc = city["country_code"]
        country = geo.country_by_code[cc]
        group = pools.COUNTRY_NAME_GROUP[cc]
        incomplete = chance(rng, cfg.incomplete_profile_rate)

        gender = weighted_choice(rng, pools.GENDERS)
        name_pool = pools.FIRST_NAMES[group][gender if gender in ("Female", "Male") else rng.choice(["Female", "Male"])]
        first = rng.choice(name_pool)
        middle = rng.choice([n for n in name_pool if n != first]) if chance(rng, pools.MIDDLE_INITIAL_RATE) else None
        last = rng.choice(pools.LAST_NAMES[group])
        full_name = " ".join(p for p in (first, middle, last) if p)

        lang1, lang2, lang3 = pick_languages(rng, cc, None if incomplete else city["state_code"])
        last_updated = rand_datetime(rng, TIMELINE_START, cfg.as_of)
        is_volunteer = uid in volunteer_ids
        if is_volunteer:
            stage = rng.choice([2, 3, 4])
        else:
            stage = 1 if chance(rng, 0.15) else None

        row = {
            "user_id": uid,
            "state_id": None if incomplete else city["state_id"],
            "country_id": country["country_id"],
            "user_status_id": USER_STATUS_ACTIVE,
            "full_name": full_name,
            "first_name": first,
            "middle_name": middle,
            "last_name": last,
            "primary_email_address": f"{first}.{last}{i}@example.com".lower(),
            "primary_phone_number": fictional_phone(rng, country["phone_code"]),
            "addr_ln1": None if incomplete else street_address(rng, cc),
            "addr_ln2": (None if incomplete or not chance(rng, 0.15)
                         else rng.choice(pools.SECONDARY_ADDRESS).format(n=rng.randint(1, 60))),
            "addr_ln3": None,
            "city_name": None if incomplete else city["city_name"],
            "zip_code": None if incomplete else postal_code(rng, cc, city["zip_prefix"]),
            "last_location": None,  # filled from user_locations below
            "last_updated_at": last_updated,
            "time_zone": None if incomplete else city["time_zone"],
            "profile_picture_path": f"mock/profile_pictures/{uid}.jpg" if chance(rng, 0.40) else None,
            "gender": gender,
            "language_1": lang1,
            "language_2": lang2,
            "language_3": lang3,
            "promotion_wizard_stage": stage,
            "promotion_wizard_last_updated_at": (
                rand_datetime(rng, TIMELINE_START, last_updated) if stage is not None else None),
            "external_auth_provider": weighted_choice(rng, pools.AUTH_PROVIDERS + [(None, 0.25)]),
            "dob": as_of_date - timedelta(days=rng.randint(18 * 366, 80 * 365)),
            "is_eu": country["is_eu_member"],
        }
        rows.append(row)
        if not incomplete:
            user_city[uid] = city
    return rows, user_city


# --- volunteer_details -----------------------------------------------------------------------
def build_volunteer_details(
    rng: random.Random, cfg: Config, volunteer_ids: List[str]
) -> List[Dict[str, Any]]:
    rows = []
    for uid in volunteer_ids:
        created = rand_datetime(rng, TIMELINE_START, cfg.as_of - timedelta(days=1))
        accepted = chance(rng, 0.95)
        terms_at = rand_after(rng, created, timedelta(hours=48), cfg.as_of) if accepted else None

        has_id1 = chance(rng, 0.70)
        has_id2 = has_id1 and chance(rng, 0.40)
        path1_at = rand_after(rng, created, timedelta(days=14), cfg.as_of) if has_id1 else None
        path2_at = rand_after(rng, created, timedelta(days=30), cfg.as_of) if has_id2 else None

        touched = max(t for t in (created, terms_at, path1_at, path2_at) if t is not None)
        has_availability = chance(rng, 0.90)
        days = sorted(rng.sample(range(len(pools.DAYS)), rng.randint(1, 5)))
        slots = sorted(rng.sample(range(len(pools.TIME_SLOTS)), rng.randint(1, 3)))

        rows.append({
            "user_id": uid,
            "terms_and_conditions": accepted,
            "terms_accepted_at": terms_at,
            "govt_id_path1": f"mock/govt_ids/{uid}/id_1.pdf" if has_id1 else None,
            "govt_id_path2": f"mock/govt_ids/{uid}/id_2.pdf" if has_id2 else None,
            "path1_updated_at": path1_at,
            "path2_updated_at": path2_at,
            "availability_days": json.dumps([pools.DAYS[d] for d in days]) if has_availability else None,
            "availability_times": json.dumps([pools.TIME_SLOTS[s] for s in slots]) if has_availability else None,
            "created_at": created,
            "last_updated_at": rand_after(rng, touched, timedelta(days=30), cfg.as_of),
        })
    return rows


# --- user_skills -------------------------------------------------------------------------------
def build_user_skills(
    rng: random.Random, cfg: Config, volunteer_rows: List[Dict[str, Any]], categories: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """(user_id, cat_id) pairs for volunteers only: every volunteer gets at least one
    skill (when the target allows), the rest are spread at random."""
    cat_ids = [c["cat_id"] for c in categories if c["cat_id"] != GENERAL_CATEGORY_ID]
    cat_order = {c: i for i, c in enumerate(cat_ids)}
    created_by_user = {v["user_id"]: v["created_at"] for v in volunteer_rows}
    vol_ids = list(created_by_user)

    max_pairs = len(vol_ids) * len(cat_ids)
    target = min(cfg.user_skills, max_pairs)
    if cfg.user_skills > max_pairs:
        warn(f"--user-skills {cfg.user_skills} exceeds the {max_pairs} possible "
             f"volunteer x category pairs; generating {max_pairs}")

    if target * 2 > max_pairs:  # dense: sample from the full product to avoid rejection loops
        pairs = rng.sample([(u, c) for u in vol_ids for c in cat_ids], target)
    else:
        pairs = []
        seen = set()
        for uid in vol_ids[:target]:
            pair = (uid, rng.choice(cat_ids))
            seen.add(pair)
            pairs.append(pair)
        while len(pairs) < target:
            pair = (rng.choice(vol_ids), rng.choice(cat_ids))
            if pair not in seen:
                seen.add(pair)
                pairs.append(pair)

    user_order = {u: i for i, u in enumerate(vol_ids)}
    pairs.sort(key=lambda p: (user_order[p[0]], cat_order[p[1]]))

    rows = []
    for uid, cat_id in pairs:
        created = rand_datetime(rng, created_by_user[uid], cfg.as_of)
        rows.append({
            "user_id": uid,
            "cat_id": cat_id,
            "skill_level": weighted_choice(rng, SKILL_LEVEL_WEIGHTS),
            "created_at": created,
            "last_updated_at": rand_after(rng, created, timedelta(days=60), cfg.as_of),
        })
    return rows


# --- user_locations / volunteer_locations --------------------------------------------------------
def build_location_profiles(
    rng: random.Random, geo: Geography, user_ids: List[str], user_city: Dict[str, Dict[str, Any]]
) -> Dict[str, Tuple[Optional[Tuple[float, float]], Tuple[float, float]]]:
    """user_id -> (prev_loc, curr_loc) as (lat, lon). curr_loc is a point within ~15 km
    of the user's city centroid. prev_loc (75% of users) is either another point in that
    city or a point in another city of the same state. A user keeps one profile, so a
    volunteer has identical coordinates in user_locations and volunteer_locations."""
    profiles = {}
    for uid in user_ids:
        city = user_city.get(uid)
        if city is None:
            continue
        curr = jitter_point(rng, city["lat"], city["lon"])
        prev = None
        if chance(rng, 0.75):
            others = [c for c in geo.cities_by_state[city["state_id"]] if c is not city]
            anchor = rng.choice(others) if others and chance(rng, 0.5) else city
            prev = jitter_point(rng, anchor["lat"], anchor["lon"])
        profiles[uid] = (prev, curr)
    return profiles


def build_location_rows(
    rng: random.Random, cfg: Config, eligible: List[str], requested: Optional[int], label: str,
    profiles: Dict[str, Tuple[Optional[Tuple[float, float]], Tuple[float, float]]],
    earliest: Dict[str, datetime],
) -> List[Dict[str, Any]]:
    count = len(eligible) if requested is None else requested
    if count > len(eligible):
        warn(f"--{label} {count} exceeds the {len(eligible)} eligible users; generating {len(eligible)}")
        count = len(eligible)
    chosen = set(rng.sample(eligible, count))
    rows = []
    for uid in eligible:
        if uid not in chosen:
            continue
        prev, curr = profiles[uid]
        rows.append({
            "user_id": uid,
            "prev_loc": ewkt_point(*prev) if prev else None,
            "curr_loc": ewkt_point(*curr),
            "last_updated_at": rand_datetime(rng, earliest[uid], cfg.as_of),
        })
    return rows


# --- organizations ---------------------------------------------------------------------------------
def build_organizations(rng: random.Random, cfg: Config, geo: Geography) -> List[Dict[str, Any]]:
    rows = []
    used_names = set()
    for i in range(1, cfg.organizations + 1):
        city = pick_city(rng, geo)
        cc = city["country_code"]
        phone_code = geo.country_by_code[cc]["phone_code"]
        org_type = weighted_choice(rng, ORG_TYPE_WEIGHTS)
        kinds = pools.NON_PROFIT_KINDS if org_type == "non_profit" else pools.FOR_PROFIT_KINDS
        focus, mission = rng.choice(pools.ORG_FOCUS)

        name = f"{rng.choice(pools.ORG_PREFIXES)} {focus} {rng.choice(kinds)}"
        if name in used_names:
            name = f"{name} {i}"
        used_names.add(name)
        slug = re.sub(r"[^a-z0-9]", "", name.lower())[:40]

        created = rand_datetime(rng, ORG_TIMELINE_START, cfg.as_of - timedelta(days=1))
        rows.append({
            "org_id": f"ORG{i:05d}",
            "org_name": name,
            "street": street_address(rng, cc),
            "city_name": city["city_name"],
            "state_id": city["state_id"],
            "zip_code": postal_code(rng, cc, city["zip_prefix"]),
            "mission": mission.format(city=city["city_name"]),
            "web_url": f"https://www.{slug}.example.org" if chance(rng, 0.90) else None,
            "phone": fictional_phone(rng, phone_code) if chance(rng, 0.90) else None,
            "email": f"info@{slug}.example.org" if chance(rng, 0.90) else None,
            "org_type": org_type,
            "org_size": weighted_choice(rng, ORG_SIZE_WEIGHTS),
            "org_rating": weighted_choice(rng, ORG_RATING_WEIGHTS) if chance(rng, 0.90) else None,
            "is_collaborator": chance(rng, 0.40),
            "is_contributor": chance(rng, 0.30),
            "created_at": created,
            "last_updated_at": rand_datetime(rng, created, cfg.as_of),
        })
    return rows


# --- orchestration ------------------------------------------------------------------------------------
def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def generate(cfg: Config) -> Dict[str, List[Dict[str, Any]]]:
    """Build every table in memory (parents before children) and return
    {table_name: rows}."""
    cfg.resolve()
    rng = random.Random(cfg.seed)

    geo = build_geography(rng, cfg)
    categories = build_help_categories(rng)

    user_ids = make_user_ids(rng, cfg.users)
    volunteer_set = set(rng.sample(user_ids, cfg.volunteers))
    volunteer_ids = [u for u in user_ids if u in volunteer_set]  # keeps user order

    users, user_city = build_users(rng, cfg, geo, user_ids, volunteer_set)
    volunteer_details = build_volunteer_details(rng, cfg, volunteer_ids)
    user_skills = build_user_skills(rng, cfg, volunteer_details, categories)

    profiles = build_location_profiles(rng, geo, user_ids, user_city)
    volunteer_created = {v["user_id"]: v["created_at"] for v in volunteer_details}
    user_locations = build_location_rows(
        rng, cfg, [u for u in user_ids if u in profiles], cfg.user_locations, "user-locations",
        profiles, {u: TIMELINE_START for u in user_ids})
    volunteer_locations = build_location_rows(
        rng, cfg, [u for u in volunteer_ids if u in profiles], cfg.volunteer_locations, "volunteer-locations",
        profiles, volunteer_created)

    # users.last_location mirrors the user's current location, and a user row is
    # touched whenever that location changes.
    user_by_id = {u["user_id"]: u for u in users}
    for loc in user_locations:
        user = user_by_id[loc["user_id"]]
        lat, lon = profiles[loc["user_id"]][1]
        user["last_location"] = pg_point(lat, lon)
        user["last_updated_at"] = max(user["last_updated_at"], loc["last_updated_at"])

    organizations = build_organizations(rng, cfg, geo)

    return {
        "countries": geo.countries,
        "states": geo.states,
        "cities": geo.cities,
        "help_categories": categories,
        "users": users,
        "volunteer_details": volunteer_details,
        "user_skills": user_skills,
        "volunteer_locations": volunteer_locations,
        "user_locations": user_locations,
        "organizations": organizations,
    }


def write_all(cfg: Config, tables: Dict[str, List[Dict[str, Any]]]) -> None:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    for name, table in schema.TABLES.items():
        path = cfg.output_dir / f"{name}.csv"
        write_csv(path, table, tables[name])
        print(f"{name + '.csv':<26}{len(tables[name]):>6} rows")


def parse_args(argv: Optional[List[str]] = None) -> Tuple[Config, bool]:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--users", type=int, default=Config.users, help="number of users (drives the other defaults)")
    p.add_argument("--volunteers", type=int, help="volunteer_details rows [default: users // 2]")
    p.add_argument("--user-skills", type=int, help="user_skills rows [default: users]")
    p.add_argument("--organizations", type=int, help="organizations rows [default: users]")
    p.add_argument("--user-locations", type=int, help="user_locations rows [default: all users with a city]")
    p.add_argument("--volunteer-locations", type=int,
                   help="volunteer_locations rows [default: all volunteers with a city]")
    p.add_argument("--cities", type=int, help="cities rows [default: all of reference_data/cities.csv]")
    p.add_argument("--seed", type=int, default=Config.seed, help="random seed (same seed => same files)")
    p.add_argument("--as-of", type=datetime.fromisoformat, default=Config.as_of, metavar="YYYY-MM-DD",
                   help="latest timestamp any row may have")
    p.add_argument("--incomplete-profile-rate", type=float, default=Config.incomplete_profile_rate,
                   help="share of users generated without state/city/zip/address (exercises NULL handling)")
    p.add_argument("--output-dir", type=Path, default=HERE, help="where to write the CSVs")
    p.add_argument("--no-validate", action="store_true", help="skip the post-generation validation run")
    a = p.parse_args(argv)
    cfg = Config(users=a.users, volunteers=a.volunteers, user_skills=a.user_skills,
                 organizations=a.organizations, user_locations=a.user_locations,
                 volunteer_locations=a.volunteer_locations, cities=a.cities, seed=a.seed,
                 as_of=a.as_of, incomplete_profile_rate=a.incomplete_profile_rate,
                 output_dir=a.output_dir)
    try:
        cfg.resolve()
    except ValueError as exc:
        p.error(str(exc))
    return cfg, not a.no_validate


def main(argv: Optional[List[str]] = None) -> int:
    cfg, run_validation = parse_args(argv)
    write_all(cfg, generate(cfg))
    if not run_validation:
        return 0
    from validate_mock_data import validate_directory  # imported late: optional step
    print()
    return 0 if validate_directory(cfg.output_dir, reference_dir=REFERENCE_DIR) else 1


if __name__ == "__main__":
    sys.exit(main())
