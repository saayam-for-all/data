"""
generate_request_guest_details.py
==================================
Generates synthetic CSV data for:
  - request_guest_details  (PK/FK: req_id → request.req_id)

Usage:
    python generate_request_guest_details.py --rows 100
"""

import csv
import os
import random
import uuid
import argparse
import pandas as pd
from pathlib import Path
from faker import Faker

# ──────────────────────────────────────────────
# Setup
# ──────────────────────────────────────────────
fake = Faker("en_US")
random.seed(42)
Faker.seed(42)

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR.parent / "mock_db"
LOOKUP_DIR = SCRIPT_DIR.parent / "lookup_tables"

# ──────────────────────────────────────────────
# Reference values based on schema
# ──────────────────────────────────────────────
GENDERS = ["Male", "Female", "Non-binary", "Prefer not to say"]

# ──────────────────────────────────────────────
# Load supporting_languages from lookup CSV
# ──────────────────────────────────────────────
def load_languages():
    path = LOOKUP_DIR / "supporting_languages.csv"

    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ Missing lookup file: {path}")

    df = pd.read_csv(path)

    if "language_name" not in df.columns:
        raise ValueError("❌ 'language_name' column not found in supporting_languages.csv")

    languages = df["language_name"].dropna().unique().tolist()

    if not languages:
        raise ValueError("❌ No languages found in supporting_languages.csv")

    print(f"✅ Loaded {len(languages)} languages from supporting_languages.csv")
    return languages

# ──────────────────────────────────────────────
# Generate request_guest_details rows
# ──────────────────────────────────────────────
def generate_request_guest_details(request_ids, languages):
    rows = []
    for req_id in request_ids:
        rows.append({
            "req_id":        req_id,
            "req_fname":     fake.first_name()[:100],
            "req_lname":     fake.last_name()[:100],
            "req_email":     fake.email()[:100],
            "req_phone":     fake.numerify("###-###-####")[:20],
            "req_age":       random.randint(18, 80),
            "req_gender":    random.choice(GENDERS),
            "req_pref_lang": random.choice(languages)
        })
    return rows

# ──────────────────────────────────────────────
# Write to CSV
# ──────────────────────────────────────────────
def write_csv(filename, rows):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = OUTPUT_DIR / filename
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"✅ {filename} → {len(rows)} rows saved to {filepath}")

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100,
                        help="Number of rows to generate (default: 100)")
    args = parser.parse_args()

    # Load languages dynamically from lookup table
    languages = load_languages()

    # Generate a pool of unique request UUIDs (simulating parent request table)
    request_ids = [str(uuid.uuid4()) for _ in range(args.rows)]

    rows = generate_request_guest_details(request_ids, languages)
    write_csv("request_guest_details.csv", rows)

if __name__ == "__main__":
    main()