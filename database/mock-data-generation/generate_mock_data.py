"""
generate_mock_data.py
=====================
Generates synthetic (mock) CSV data for the Saayam database tables:
  - users                   (generated first — required as FK source)
  - volunteer_applications  (2,000 rows, FK: user_id -> users)
  - user_skills             (5,000 rows, FK: user_id -> users, cat_id -> help_categories)

Usage
-----
    pip install faker pandas
    python generate_mock_data.py

    # Custom row counts
    python generate_mock_data.py --users 500 --vol-apps 2000 --user-skills 5000

Output
------
All CSVs are written to  ../mock_db/
    users.csv
    volunteer_applications.csv
    user_skills.csv

Notes
-----
- Run this script from inside the  database/mock-data-generation/  folder.
- The script reads db_info.json (in the same folder) for column names.
- If db_info.json is missing, built-in fallback schemas are used automatically.
- Lookup tables (states/cities/categories) are loaded from ../lookup_tables/ when present.
- Set RANDOM_SEED at the top for reproducible output.
"""

import argparse
import csv
import json
import os
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

# ── Config ────────────────────────────────────────────────────────────────────
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

fake = Faker("en_US")
Faker.seed(RANDOM_SEED)

# Paths (script lives in database/mock-data-generation/)
SCRIPT_DIR   = Path(__file__).parent
OUTPUT_DIR   = SCRIPT_DIR.parent / "mock_db"
LOOKUP_DIR   = SCRIPT_DIR.parent / "lookup_tables"
DB_INFO_FILE = SCRIPT_DIR / "db_info.json"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_db_info():
    """Load schema from db_info.json; return empty dict if file is missing."""
    if DB_INFO_FILE.exists():
        with open(DB_INFO_FILE) as f:
            return json.load(f)
    print(f"[WARN] db_info.json not found at {DB_INFO_FILE}. Using built-in schema.")
    return {}


def load_lookup_csv(filename):
    """Load a CSV from the lookup_tables folder; return list of dicts."""
    path = LOOKUP_DIR / filename
    if not path.exists():
        print(f"[WARN] Lookup file not found: {path}")
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def rand_date(start_years_ago=5, end_years_ago=0):
    """Return a random date string (YYYY-MM-DD) within the given range."""
    start = datetime.now() - timedelta(days=365 * start_years_ago)
    end   = datetime.now() - timedelta(days=365 * end_years_ago)
    delta = end - start
    return (start + timedelta(days=random.randint(0, delta.days))).strftime("%Y-%m-%d")


def rand_datetime(start_years_ago=5):
    """Return a random ISO datetime string."""
    start = datetime.now() - timedelta(days=365 * start_years_ago)
    delta = datetime.now() - start
    return (start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def write_csv(filepath, rows):
    """Write a list of dicts to a CSV file."""
    if not rows:
        print(f"[WARN] No rows to write for {filepath}")
        return
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OK]   Wrote {len(rows):,} rows → {filepath}")


# ── State / City lookup ───────────────────────────────────────────────────────

# Built-in fallback — a small but realistic US state→cities map
FALLBACK_STATE_CITIES = {
    "CA": ["Los Angeles", "San Francisco", "San Diego", "Sacramento", "Fresno"],
    "TX": ["Houston", "Dallas", "Austin", "San Antonio", "El Paso"],
    "NY": ["New York City", "Buffalo", "Albany", "Rochester", "Yonkers"],
    "FL": ["Miami", "Orlando", "Tampa", "Jacksonville", "Tallahassee"],
    "IL": ["Chicago", "Aurora", "Naperville", "Joliet", "Rockford"],
    "WA": ["Seattle", "Spokane", "Tacoma", "Vancouver", "Bellevue"],
    "GA": ["Atlanta", "Augusta", "Columbus", "Savannah", "Athens"],
    "NC": ["Charlotte", "Raleigh", "Greensboro", "Durham", "Winston-Salem"],
    "OH": ["Columbus", "Cleveland", "Cincinnati", "Toledo", "Akron"],
    "AZ": ["Phoenix", "Tucson", "Scottsdale", "Mesa", "Chandler"],
}


def build_state_city_map():
    """
    Try to build state→cities map from lookup CSVs.
    Falls back to FALLBACK_STATE_CITIES if lookup files are absent.
    Expected lookup file: us_cities.csv  with columns: state_code, city
    """
    rows = load_lookup_csv("us_cities.csv")
    if not rows:
        rows = load_lookup_csv("cities.csv")  # alternative name

    if rows:
        state_city = {}
        for r in rows:
            state = r.get("state_code") or r.get("state") or r.get("State", "")
            city  = r.get("city") or r.get("City", "")
            if state and city:
                state_city.setdefault(state.strip(), []).append(city.strip())
        if state_city:
            return state_city

    return FALLBACK_STATE_CITIES


STATE_CITY_MAP = build_state_city_map()
STATES = list(STATE_CITY_MAP.keys())


def rand_state_city():
    state = random.choice(STATES)
    city  = random.choice(STATE_CITY_MAP[state])
    return state, city


# ── Help categories lookup ────────────────────────────────────────────────────

FALLBACK_CATEGORIES = [
    {"cat_id": str(i), "category_name": name}
    for i, name in enumerate(
        [
            "Transportation", "Grocery & Errands", "Medical Assistance",
            "Home Repairs", "Childcare", "Elder Care", "Pet Care",
            "Technology Help", "Language Translation", "Mental Health Support",
            "Financial Guidance", "Legal Aid", "Education & Tutoring",
            "Food & Meals", "Housing Support",
        ],
        start=1,
    )
]


def load_categories():
    rows = load_lookup_csv("help_categories.csv")
    if not rows:
        rows = load_lookup_csv("categories.csv")
    if rows:
        return rows
    return FALLBACK_CATEGORIES


CATEGORIES     = load_categories()
CATEGORY_IDS   = [str(c.get("cat_id") or c.get("id") or c.get("category_id", "")) for c in CATEGORIES]
CATEGORY_IDS   = [c for c in CATEGORY_IDS if c]  # drop empties


# ── Table generators ──────────────────────────────────────────────────────────

GENDERS        = ["Male", "Female", "Non-binary", "Prefer not to say"]
LANGUAGES      = ["English", "Spanish", "Hindi", "Mandarin", "French", "Arabic", "Portuguese"]
APP_STATUSES   = ["pending", "approved", "rejected", "under_review"]
SKILL_LEVELS   = ["beginner", "intermediate", "advanced", "expert"]
AVAILABILITY   = ["weekdays", "weekends", "evenings", "flexible", "mornings"]
PHONE_TYPES    = ["mobile", "home", "work"]
TIMEZONES      = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "America/Phoenix"]


def generate_users(n=500):
    """
    Generate the users table.
    Columns follow the common Saayam user schema observed in the volunteer repo.
    Adjust column names below to exactly match your db_info.json if they differ.
    """
    rows = []
    used_emails = set()

    for i in range(1, n + 1):
        state, city = rand_state_city()

        # Guarantee unique email
        email = fake.email()
        while email in used_emails:
            email = fake.unique.email()
        used_emails.add(email)

        first_name = fake.first_name()
        last_name  = fake.last_name()
        created_at = rand_datetime(start_years_ago=4)

        rows.append({
            "user_id":          str(i),
            "first_name":       first_name,
            "last_name":        last_name,
            "email":            email,
            "phone_number":     fake.numerify("###-###-####"),
            "phone_type":       random.choice(PHONE_TYPES),
            "date_of_birth":    rand_date(start_years_ago=60, end_years_ago=18),
            "gender":           random.choice(GENDERS),
            "address_line1":    fake.street_address(),
            "address_line2":    random.choice(["", fake.secondary_address(), ""]),
            "city":             city,
            "state":            state,
            "zip_code":         fake.zipcode(),
            "country":          "US",
            "timezone":         random.choice(TIMEZONES),
            "preferred_language": random.choice(LANGUAGES),
            "profile_picture_url": f"https://randomuser.me/api/portraits/{'men' if random.random() > 0.5 else 'women'}/{random.randint(1, 99)}.jpg",
            "is_active":        random.choice([True, True, True, False]),
            "is_verified":      random.choice([True, True, False]),
            "created_at":       created_at,
            "updated_at":       rand_datetime(start_years_ago=1),
        })

    return rows


def generate_volunteer_applications(n=2000, user_ids=None):
    """
    Generate volunteer_applications rows.
    FK: user_id -> users.user_id
    Each user can have multiple applications (realistic — people may reapply).
    """
    if not user_ids:
        raise ValueError("user_ids list is required for volunteer_applications FK.")

    rows = []
    for i in range(1, n + 1):
        state, city       = rand_state_city()
        applied_at        = rand_datetime(start_years_ago=3)
        status            = random.choices(
            APP_STATUSES, weights=[20, 60, 15, 5], k=1
        )[0]
        reviewed_at       = rand_datetime(start_years_ago=2) if status != "pending" else ""
        approved_at       = rand_datetime(start_years_ago=1) if status == "approved" else ""

        rows.append({
            "application_id":         str(i),
            "user_id":                random.choice(user_ids),   # FK respected
            "status":                 status,
            "motivation":             fake.sentence(nb_words=random.randint(10, 25)),
            "availability":           random.choice(AVAILABILITY),
            "hours_per_week":         random.randint(2, 40),
            "preferred_categories":   ",".join(random.sample(CATEGORY_IDS, k=random.randint(1, 4))) if CATEGORY_IDS else "",
            "background_check_done":  random.choice([True, False]),
            "background_check_date":  rand_date(start_years_ago=2) if random.random() > 0.4 else "",
            "reference_name":         fake.name(),
            "reference_contact":      fake.email(),
            "city":                   city,
            "state":                  state,
            "zip_code":               fake.zipcode(),
            "applied_at":             applied_at,
            "reviewed_at":            reviewed_at,
            "approved_at":            approved_at,
            "reviewer_notes":         fake.sentence(nb_words=8) if reviewed_at else "",
            "created_at":             applied_at,
            "updated_at":             rand_datetime(start_years_ago=1),
        })

    return rows


def generate_user_skills(n=5000, user_ids=None, category_ids=None):
    """
    Generate user_skills rows.
    FK: user_id -> users.user_id
        cat_id  -> help_categories.cat_id
    Combination of (user_id, cat_id) is kept unique per user to avoid duplicates.
    """
    if not user_ids:
        raise ValueError("user_ids list is required for user_skills FK.")
    if not category_ids:
        raise ValueError("category_ids list is required for user_skills FK.")

    used_pairs = set()
    rows       = []
    attempts   = 0
    max_attempts = n * 10  # safety cap to avoid infinite loop

    while len(rows) < n and attempts < max_attempts:
        attempts += 1
        uid = random.choice(user_ids)
        cid = random.choice(category_ids)
        pair = (uid, cid)

        if pair in used_pairs:
            continue
        used_pairs.add(pair)

        acquired_date = rand_date(start_years_ago=10)
        rows.append({
            "skill_id":          str(len(rows) + 1),
            "user_id":           uid,                          # FK respected
            "cat_id":            cid,                          # FK respected
            "skill_level":       random.choice(SKILL_LEVELS),
            "years_experience":  round(random.uniform(0.5, 20), 1),
            "is_verified":       random.choice([True, False]),
            "verified_by":       fake.name() if random.random() > 0.5 else "",
            "verified_date":     rand_date(start_years_ago=2) if random.random() > 0.5 else "",
            "description":       fake.sentence(nb_words=random.randint(8, 20)),
            "acquired_date":     acquired_date,
            "created_at":        acquired_date + " 00:00:00",
            "updated_at":        rand_datetime(start_years_ago=1),
        })

    if len(rows) < n:
        print(
            f"[WARN] Could only generate {len(rows):,} unique user_skills rows "
            f"(requested {n:,}). Increase user count or category count."
        )

    return rows


# ── Main ──────────────────────────────────────────────────────────────────────

def main(n_users=500, n_vol_apps=2000, n_user_skills=5000):
    print("\n=== Saayam Mock Data Generator ===\n")

    # Load schema (informational — used to validate column names if needed)
    db_info = load_db_info()
    if db_info:
        print(f"[OK]   Loaded db_info.json ({len(db_info)} table entries found)")

    # Step 1 — users (must be first; FK source for both other tables)
    print(f"\n[GEN]  Generating {n_users:,} users ...")
    users = generate_users(n=n_users)
    write_csv(OUTPUT_DIR / "users.csv", users)
    user_ids = [row["user_id"] for row in users]

    # Step 2 — volunteer_applications
    print(f"\n[GEN]  Generating {n_vol_apps:,} volunteer_applications ...")
    vol_apps = generate_volunteer_applications(n=n_vol_apps, user_ids=user_ids)
    write_csv(OUTPUT_DIR / "volunteer_applications.csv", vol_apps)

    # Step 3 — user_skills
    print(f"\n[GEN]  Generating {n_user_skills:,} user_skills ...")
    skills = generate_user_skills(
        n=n_user_skills,
        user_ids=user_ids,
        category_ids=CATEGORY_IDS,
    )
    write_csv(OUTPUT_DIR / "user_skills.csv", skills)

    print(f"\n=== Done! All files saved to: {OUTPUT_DIR.resolve()} ===\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Saayam mock CSV data.")
    parser.add_argument("--users",       type=int, default=500,   help="Number of users to generate (default: 500)")
    parser.add_argument("--vol-apps",    type=int, default=2000,  help="Number of volunteer_applications rows (default: 2000)")
    parser.add_argument("--user-skills", type=int, default=5000,  help="Number of user_skills rows (default: 5000)")
    args = parser.parse_args()

    main(
        n_users=args.users,
        n_vol_apps=args.vol_apps,
        n_user_skills=args.user_skills,
    )
