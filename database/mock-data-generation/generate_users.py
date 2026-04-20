import argparse
import csv
import os
import random
import sys
from datetime import datetime, timedelta
from faker import Faker

fake = Faker()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DB_DIR     = os.path.join(REPO_ROOT, "database")
OUTPUT_DIR = os.path.join(DB_DIR, "mock_db")
LOOKUP_DIR = os.path.join(DB_DIR, "lookup_tables")

os.makedirs(OUTPUT_DIR, exist_ok=True)

USER_CATEGORY_IDS = [1, 2, 3, 4, 5]
USER_STATUS_IDS   = [1]
LANGUAGE_IDS      = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
AUTH_PROVIDERS    = ["LOCAL", "GOOGLE", "FACEBOOK", "APPLE", "MICROSOFT"]
GENDERS           = ["M", "F", "O", "U"]
TIME_ZONES        = [
    "America/New_York", "America/Chicago", "America/Denver",
    "America/Los_Angeles", "America/Phoenix", "Europe/London",
    "Europe/Paris", "Asia/Tokyo", "Asia/Kolkata", "Asia/Dubai",
    "Australia/Sydney", "Pacific/Auckland",
]


def set_seed(seed=42):
    random.seed(seed)
    Faker.seed(seed)
    fake.seed_instance(seed)


def format_ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def format_date(d):
    return d.strftime("%Y-%m-%d")


def random_past_dt(days_back=365):
    base = datetime(2026, 1, 1, 9, 0, 0)
    return base - timedelta(
        days=random.randint(0, days_back),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )


def make_user_ids(count, start=101):
    return [f"U{start + i}" for i in range(count)]


def write_csv(filepath, rows):
    if not rows:
        raise ValueError(f"No rows to write for {filepath}")
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows):,} rows -> {filepath}")


def load_states():
    path = os.path.join(LOOKUP_DIR, "state.csv")
    if not os.path.exists(path):
        print(f"Error: state.csv not found at {path}")
        sys.exit(1)
    states = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["state_id"] and row["country_id"]:
                states.append({
                    "state_id"  : row["state_id"].strip('"'),
                    "country_id": int(float(row["country_id"].strip('"'))),
                })
    return states


def generate_users(count=100):
    print(f"Generating {count:,} users ...")
    states   = load_states()
    user_ids = make_user_ids(count, start=101)
    rows     = []

    for uid in user_ids:
        loc    = random.choice(states)
        first  = fake.first_name()
        last   = fake.last_name()
        middle = fake.first_name() if random.random() > 0.6 else ""
        full   = " ".join(p for p in [first, middle, last] if p)

        last_upd   = random_past_dt(days_back=365)
        wizard_upd = last_upd + timedelta(minutes=random.randint(0, 43200))

        lang1 = random.choice(LANGUAGE_IDS)
        lang2 = random.choice([l for l in LANGUAGE_IDS if l != lang1])
        lang3 = random.choice([l for l in LANGUAGE_IDS if l not in (lang1, lang2)])

        rows.append({
            "user_id"                           : uid,
            "state_id"                          : loc["state_id"],
            "country_id"                        : loc["country_id"],
            "user_status_id"                    : random.choice(USER_STATUS_IDS),
            "user_category_id"                  : random.choice(USER_CATEGORY_IDS),
            "full_name"                         : full,
            "first_name"                        : first,
            "middle_name"                       : middle,
            "last_name"                         : last,
            "primary_email_address"             : f"{first.lower()}.{last.lower()}{uid}@example.com",
            "primary_phone_number"              : fake.phone_number()[:20],
            "addr_ln1"                          : fake.street_address(),
            "addr_ln2"                          : fake.secondary_address() if random.random() > 0.7 else "",
            "addr_ln3"                          : "",
            "city_name"                         : fake.city(),
            "zip_code"                          : fake.postcode(),
            "last_location"                     : f"{round(random.uniform(24.0, 49.0), 6)},{round(random.uniform(-125.0, -66.0), 6)}",
            "last_update_date"                  : format_ts(last_upd) + "+00",
            "time_zone"                         : random.choice(TIME_ZONES),
            "profile_picture_path"              : f"/images/profiles/{uid}.jpg",
            "gender"                            : random.choice(GENDERS),
            "language_1"                        : lang1,
            "language_2"                        : lang2,
            "language_3"                        : lang3,
            "promotion_wizard_stage"            : random.randint(1, 4),
            "promotion_wizard_last_update_date" : format_ts(wizard_upd) + "+00",
            "external_auth_provider"            : random.choice(AUTH_PROVIDERS),
            "dob"                               : format_date(fake.date_of_birth(minimum_age=18, maximum_age=80)),
        })

    write_csv(os.path.join(OUTPUT_DIR, "mock_users.csv"), rows)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed",  type=int, default=42)
    args = parser.parse_args()
    set_seed(args.seed)
    generate_users(count=args.count)