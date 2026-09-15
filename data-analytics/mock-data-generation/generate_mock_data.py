import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

from utils import (
    CATEGORY_IDS,
    LANGUAGE_IDS,
    ORG_SIZES,
    ORG_TYPES,
    SKILL_LEVELS,
    choose,
    format_date,
    format_datetime,
    point_near_city,
    postgres_point_near_city,
    read_csv,
    set_seed,
    unique_email,
    write_csv,
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = BASE_DIR / "output_csv_files"

NAME_POOL = [
    ("Alex", "James", "Bennett"),
    ("Jordan", "Lee", "Carter"),
    ("Taylor", "Morgan", "Reed"),
    ("Sam", "Daniel", "Brooks"),
    ("Avery", "Grace", "Mitchell"),
    ("Riley", "Noah", "Parker"),
    ("Casey", "Mia", "Turner"),
    ("Morgan", "Evan", "Hayes"),
    ("Cameron", "Rose", "Foster"),
    ("Drew", "Michael", "Cole"),
    ("Jamie", "Claire", "Ward"),
    ("Quinn", "Ryan", "Murphy"),
]

ORGANIZATION_NAMES = [
    "Harbor Alliance", "Bridgeway Collective", "Pathways Community Trust",
    "Northstar Support Network", "Community Reach Center", "Civic Hands Initiative",
    "Neighborhood Resource Hub", "Open Door Partners", "Lighthouse Service Group",
    "Shared Steps Foundation", "Community Link Network", "Helping Horizons",
]

MISSIONS = [
    "Connects residents with practical community assistance and local volunteer services.",
    "Supports community programs through coordinated volunteer and resource services.",
    "Improves access to local assistance, outreach programs, and neighborhood support.",
    "Builds partnerships that connect volunteers with community needs and services.",
]

USER_STATUSES = [1, 2, 3]
AUTH_PROVIDERS = ["Google", "Microsoft", "Apple", "Facebook", "Auth0"]
GENDERS = ["Female", "Male", "Non-Binary", "Prefer Not to Say"]


def canonical_user_id(number: int) -> str:
    return f"SID-00-{number // 1_000_000:03d}-{(number % 1_000_000) // 1000:03d}-{number % 1000:03d}"


def canonical_org_id(number: int) -> str:
    padded = f"{number:013d}"
    return f"ORG-{padded[:3]}-{padded[3:6]}-{padded[6:9]}-{padded[9:13]}"


def make_users(count: int, cities: list[dict[str, str]], states: list[dict[str, str]], countries: list[dict[str, str]], rng: random.Random) -> list[dict[str, str]]:
    state_lookup = {row["state_id"]: row for row in states}
    country_lookup = {row["country_id"]: row for row in countries}
    rows = []

    for i in range(1, count + 1):
        city = cities[(i - 1) % len(cities)]
        state = state_lookup[city["state_id"]]
        country = country_lookup[state["country_id"]]
        first, middle, last = NAME_POOL[(i - 1) % len(NAME_POOL)]
        user_id = canonical_user_id(i)
        created = datetime(2022, 1, 1, 8, 0, 0) + timedelta(
            days=i % 1400, hours=rng.randint(0, 8), minutes=rng.randint(0, 59)
        )

        rows.append({
            "user_id": user_id,
            "state_id": state["state_id"],
            "country_id": country["country_id"],
            "user_status_id": str(choose(USER_STATUSES, rng)),
            "full_name": f"{first} {middle} {last}",
            "first_name": first,
            "middle_name": middle,
            "last_name": last,
            "primary_email_address": unique_email(first, last, i),
            "primary_phone_number": f"+1-555-{100 + i // 1000:03d}-{i % 1000:04d}",
            "addr_ln1": f"{100 + i} Maple Street",
            "addr_ln2": f"Apt {1 + i % 40}",
            "addr_ln3": f"Unit {1 + i % 20}",
            "city_name": city["city_name"],
            "zip_code": f"{10000 + i % 89999:05d}",
            "last_location": postgres_point_near_city(
                float(city["lattitude"]), float(city["longitude"]), rng, 0.008
            ),
            "last_updated_at": format_datetime(created),
            "time_zone": "America/New_York",
            "profile_picture_path": f"/profiles/{user_id}.jpg",
            "gender": choose(GENDERS, rng),
            "language_1": "1",
            "language_2": str(choose([x for x in LANGUAGE_IDS if x != 1], rng)),
            "language_3": str(choose([x for x in LANGUAGE_IDS if x != 1], rng)),
            "promotion_wizard_stage": str(1 + i % 5),
            "promotion_wizard_last_updated_at": format_datetime(created),
            "external_auth_provider": choose(AUTH_PROVIDERS, rng),
            "dob": format_date(datetime(1970 + i % 35, 1 + i % 12, 1 + i % 28)),
            "is_eu": country["is_eu_member"],
        })
    return rows


def make_volunteer_details(users: list[dict[str, str]], count: int, rng: random.Random) -> list[dict[str, str]]:
    rows = []
    for user in users[:count]:
        created = datetime(2022, 1, 1, 8, 0, 0) + timedelta(
            days=rng.randint(0, 1400), hours=rng.randint(0, 8), minutes=rng.randint(0, 59)
        )
        accepted = created + timedelta(minutes=rng.randint(20, 240))
        last_updated = accepted + timedelta(days=rng.randint(0, 120), hours=rng.randint(0, 8))
        user_id = user["user_id"]
        rows.append({
            "user_id": user_id,
            "terms_and_conditions": "TRUE",
            "terms_accepted_at": format_datetime(accepted),
            "govt_id_path1": f"/documents/govt_id/{user_id}_driver_id.pdf",
            "govt_id_path2": f"/documents/govt_id/{user_id}_state_id.pdf",
            "path1_updated_at": format_datetime(accepted),
            "path2_updated_at": format_datetime(accepted + timedelta(days=1)),
            "availability_days": "MON,WED,FRI",
            "availability_times": "08:00-12:00",
            "created_at": format_datetime(created),
            "last_updated_at": format_datetime(last_updated),
            "govt_id_expiry1": format_date(accepted + timedelta(days=365)),
            "govt_id_expiry2": format_date(accepted + timedelta(days=730)),
            "govt_id_name1": "Driver ID",
            "govt_id_name2": "State ID",
        })
    return rows


def make_user_skills(users: list[dict[str, str]], categories: list[dict[str, str]], min_skills: int, max_skills: int, rng: random.Random) -> list[dict[str, str]]:
    category_ids = [row["cat_id"] for row in categories if row["cat_id"] in CATEGORY_IDS and row["cat_id"] != "0.0.0.0.0"]
    rows = []
    for i, user in enumerate(users):
        count = rng.randint(min_skills, max_skills)
        chosen = rng.sample(category_ids, min(count, len(category_ids)))
        base = datetime(2022, 1, 1, 7, 0, 0) + timedelta(
            days=(i * 3) % 1400, hours=rng.randint(0, 8), minutes=rng.randint(0, 59)
        )
        for j, cat_id in enumerate(chosen):
            created = base + timedelta(hours=j)
            rows.append({
                "user_id": user["user_id"],
                "cat_id": cat_id,
                "skill_level": choose(SKILL_LEVELS, rng),
                "created_at": format_datetime(created),
                "last_updated_at": format_datetime(created + timedelta(days=rng.randint(1, 30))),
            })
    return rows


def make_locations(users: list[dict[str, str]], city_lookup: dict[tuple[str, str], tuple[float, float]], rng: random.Random) -> list[dict[str, str]]:
    rows = []
    for i, user in enumerate(users):
        lat, lon = city_lookup[(user["state_id"], user["city_name"])]
        rows.append({
            "user_id": user["user_id"],
            "prev_loc": point_near_city(lat, lon, rng, 0.008),
            "curr_loc": point_near_city(lat, lon, rng, 0.008),
            "last_updated_at": format_datetime(
                datetime(2022, 1, 1, 8, 0, 0) + timedelta(
                    days=(i * 7) % 1400, hours=rng.randint(0, 8), minutes=rng.randint(0, 59)
                )
            ),
        })
    return rows


def make_organizations(count: int, cities: list[dict[str, str]], states: list[dict[str, str]], rng: random.Random) -> list[dict[str, str]]:
    state_lookup = {row["state_id"]: row for row in states}
    rows = []
    for i in range(1, count + 1):
        city = cities[(i - 1) % len(cities)]
        state = state_lookup[city["state_id"]]
        created = datetime(2023, 1, 1, 7, 0, 0) + timedelta(
            days=(i * 5) % 1000, hours=rng.randint(0, 8), minutes=rng.randint(0, 59)
        )
        rows.append({
            "org_id": canonical_org_id(i),
            "org_name": f"{ORGANIZATION_NAMES[(i - 1) % len(ORGANIZATION_NAMES)]} {i}",
            "street": f"{200 + i} Market Avenue",
            "city_name": city["city_name"],
            "state_id": state["state_id"],
            "zip_code": f"{20000 + i % 79999:05d}",
            "mission": MISSIONS[(i - 1) % len(MISSIONS)],
            "web_url": f"https://example.org/organizations/{i:06d}",
            "phone": f"+1-555-{200 + i // 1000:03d}-{i % 1000:04d}",
            "email": f"contact{i:03d}@example.org",
            "org_type": ORG_TYPES[(i - 1) % len(ORG_TYPES)],
            "org_size": ORG_SIZES[(i - 1) % len(ORG_SIZES)],
            "org_rating": str(1 + i % 5),
            "is_collaborator": "TRUE" if i % 2 == 0 else "FALSE",
            "is_contributor": "TRUE" if i % 3 == 0 else "FALSE",
            "created_at": format_datetime(created),
            "last_updated_at": format_datetime(created + timedelta(days=1 + i % 14)),
        })
    return rows


def copy_lookup(path: Path, output: Path) -> None:
    rows = read_csv(path)
    write_csv(output, rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate configurable mock data for Issue #301 dashboard testing.")
    parser.add_argument("--users", type=int, default=400)
    parser.add_argument("--volunteers", type=int, default=300)
    parser.add_argument("--organizations", type=int, default=400)
    parser.add_argument("--min-skills", type=int, default=1)
    parser.add_argument("--max-skills", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.users < 1:
        raise ValueError("--users must be at least 1")
    if args.volunteers < 0 or args.volunteers > args.users:
        raise ValueError("--volunteers must be between 0 and --users")
    if args.organizations < 1:
        raise ValueError("--organizations must be at least 1")
    if args.min_skills < 1 or args.max_skills < args.min_skills:
        raise ValueError("Invalid skill range")

    set_seed(args.seed)
    rng = random.Random(args.seed)
    args.output.mkdir(parents=True, exist_ok=True)

    countries = read_csv(BASE_DIR / "countries.csv")
    states = read_csv(BASE_DIR / "states.csv")
    cities = read_csv(BASE_DIR / "cities.csv")
    categories = read_csv(BASE_DIR / "help_categories.csv")

    users = make_users(args.users, cities, states, countries, rng)
    city_lookup = {
        (row["state_id"], row["city_name"]): (float(row["lattitude"]), float(row["longitude"]))
        for row in cities
    }
    volunteers = make_volunteer_details(users, args.volunteers, rng)
    user_skills = make_user_skills(users, categories, args.min_skills, args.max_skills, rng)
    user_locations = make_locations(users, city_lookup, rng)
    volunteer_locations = make_locations(users[: args.volunteers], city_lookup, rng)
    organizations = make_organizations(args.organizations, cities, states, rng)

    copy_lookup(BASE_DIR / "countries.csv", args.output / "countries.csv")
    copy_lookup(BASE_DIR / "states.csv", args.output / "states.csv")
    copy_lookup(BASE_DIR / "cities.csv", args.output / "cities.csv")
    copy_lookup(BASE_DIR / "help_categories.csv", args.output / "help_categories.csv")
    write_csv(args.output / "users.csv", users)
    write_csv(args.output / "volunteer_details.csv", volunteers)
    write_csv(args.output / "user_skills.csv", user_skills)
    write_csv(args.output / "user_locations.csv", user_locations)
    write_csv(args.output / "volunteer_locations.csv", volunteer_locations)
    write_csv(args.output / "organizations.csv", organizations)

    print(f"Generated 10 CSV files in {args.output}")
    print(
        f"users={len(users)}, volunteers={len(volunteers)}, user_skills={len(user_skills)}, "
        f"locations={len(user_locations)}, volunteer_locations={len(volunteer_locations)}, "
        f"organizations={len(organizations)}"
    )


if __name__ == "__main__":
    main()
