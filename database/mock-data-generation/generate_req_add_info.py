"""
generate_req_add_info.py
=========================
Generates synthetic CSV data for:
  - req_add_info  (PK: request_id, FK: request_id → request.req_id, cat_id → help_categories.cat_id)

Usage:
    python generate_req_add_info.py --rows 100
"""

import csv
import os
import random
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
# Load request_ids from already generated
# request_guest_details.csv (to maintain FK consistency)
# ──────────────────────────────────────────────
def load_request_ids():
    path = OUTPUT_DIR / "request_guest_details.csv"

    if not os.path.exists(path):
        raise FileNotFoundError(
            "❌ request_guest_details.csv not found in mock_db. "
            "Please run generate_request_guest_details.py first."
        )

    df = pd.read_csv(path)

    if "req_id" not in df.columns:
        raise ValueError("❌ 'req_id' column not found in request_guest_details.csv")

    request_ids = df["req_id"].dropna().unique().tolist()
    print(f"✅ Loaded {len(request_ids)} request IDs from request_guest_details.csv")
    return request_ids

# ──────────────────────────────────────────────
# Load req_add_info_metadata and group
# field_name_keys by cat_id
# ──────────────────────────────────────────────
def load_metadata():
    path = LOOKUP_DIR / "req_add_info_metadata.csv"

    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ Missing lookup file: {path}")

    df = pd.read_csv(path)

    # Only use active fields
    df = df[df["status"] == "active"]

    # Group field_name_key by cat_id
    grouped = {}
    for _, row in df.iterrows():
        cat = row["cat_id"]
        key = row["field_name_key"]
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(key)

    print(f"✅ Loaded metadata for {len(grouped)} categories from req_add_info_metadata.csv")
    return grouped

# ──────────────────────────────────────────────
# Generate realistic field_value based on field_name_key
# ──────────────────────────────────────────────
def generate_field_value(field_name_key):
    field = field_name_key.upper()

    if "EMAIL" in field:
        return fake.email()
    elif "PHONE" in field:
        return fake.numerify("###-###-####")
    elif "DATE" in field or "TIME" in field:
        return fake.date_time_between(start_date="-1y", end_date="now").strftime("%Y-%m-%d %H:%M:%S")
    elif "ADDRESS" in field or "LOCATION" in field:
        return fake.street_address()
    elif "NAME" in field:
        return fake.name()
    elif "SIZE" in field or "QUANTITY" in field or "NUMBER" in field:
        return str(random.randint(1, 20))
    elif "BUDGET" in field:
        return f"${random.randint(100, 5000)}"
    elif "URGENCY" in field:
        return random.choice(["Low", "Medium", "High", "Critical"])
    elif "GENDER" in field:
        return random.choice(["Male", "Female", "Non-binary", "Any"])
    elif "LANGUAGE" in field:
        return random.choice(["English", "Spanish", "Hindi", "French", "Telugu"])
    elif "FREQUENCY" in field:
        return random.choice(["Daily", "Weekly", "Monthly", "Once"])
    elif "TYPE" in field:
        return random.choice(["Standard", "Express", "Premium", "Basic"])
    elif "STATUS" in field:
        return random.choice(["Pending", "Active", "Completed", "Cancelled"])
    elif "SCHEDULE" in field:
        return random.choice(["Morning", "Afternoon", "Evening", "Flexible"])
    else:
        return fake.sentence(nb_words=5)

# ──────────────────────────────────────────────
# Generate req_add_info rows
# ──────────────────────────────────────────────
def generate_req_add_info(request_ids, metadata):
    rows = []
    cat_ids = list(metadata.keys())

    for request_id in request_ids:
        # Pick a random category for this request
        cat_id = random.choice(cat_ids)

        # Get all field_name_keys for this category
        field_keys = metadata[cat_id]

        # Generate one row per field_name_key for this request
        for field_name_key in field_keys:
            rows.append({
                "request_id":     request_id,
                "cat_id":         cat_id,
                "field_name_key": field_name_key[:100],
                "field_value":    generate_field_value(field_name_key)
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

    # Load request_ids from already generated request_guest_details.csv
    request_ids = load_request_ids()

    # Use only the number of rows requested
    request_ids = request_ids[:args.rows]

    # Load metadata grouped by cat_id
    metadata = load_metadata()

    # Generate rows
    rows = generate_req_add_info(request_ids, metadata)

    # Save to CSV
    write_csv("req_add_info.csv", rows)

if __name__ == "__main__":
    main()