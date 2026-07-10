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
# field_id + field_name_key by cat_id
# ──────────────────────────────────────────────
def load_metadata():
    path = LOOKUP_DIR / "req_add_info_metadata.csv"

    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ Missing lookup file: {path}")

    df = pd.read_csv(path)
    df = df[df["status"] == "active"]

    # Group list of {field_id, field_name_key} by cat_id
    grouped = {}
    for _, row in df.iterrows():
        cat = row["cat_id"]
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append({
            "field_id":       row["field_id"],
            "field_name_key": row["field_name_key"],
            "field_type":     row["field_type"]
        })

    print(f"✅ Loaded metadata for {len(grouped)} categories from req_add_info_metadata.csv")
    return grouped

# ──────────────────────────────────────────────
# Load list_item_metadata and group
# valid item_values by field_id
# ──────────────────────────────────────────────
def load_list_items():
    path = LOOKUP_DIR / "list_item_metadata.csv"

    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ Missing lookup file: {path}")

    df = pd.read_csv(path)

    # Group item_values by field_id
    grouped = {}
    for _, row in df.iterrows():
        fid = row["field_id"]
        if fid not in grouped:
            grouped[fid] = []
        grouped[fid].append(str(row["item_value"]).strip())

    print(f"✅ Loaded list items for {len(grouped)} fields from list_item_metadata.csv")
    return grouped

# ──────────────────────────────────────────────
# Generate field_value based on field type
# and valid values from list_item_metadata
# ──────────────────────────────────────────────
def generate_field_value(field_id, field_name_key, field_type, list_items):
    field = field_name_key.upper()

    # If list/radiobutton/checkbox → use real values from list_item_metadata
    if field_type in ("list", "radiobutton", "checkbox"):
        if field_id in list_items:
            return random.choice(list_items[field_id])
        # checkbox fields not in list_item_metadata → boolean YES/NO
        if field_type == "checkbox":
            return random.choice(["YES", "NO"])

    # For date&time fields
    if field_type == "date&time" or "DATE" in field or "TIME" in field:
        return fake.date_time_between(
            start_date="-1y", end_date="now"
        ).strftime("%Y-%m-%d %H:%M:%S")

    # For integer fields
    if field_type == "integer" or "NUMBER" in field or "SIZE" in field or "QUANTITY" in field:
        return str(random.randint(1, 20))

    # For currency fields
    if field_type == "currency" or "BUDGET" in field or "RENT" in field or "FEE" in field:
        return str(random.randint(100, 5000))

    # For address/location fields
    if "ADDRESS" in field or "LOCATION" in field:
        return fake.street_address()

    # For name fields
    if "NAME" in field:
        return fake.name()

    # For language fields
    if "LANGUAGE" in field or "LANGUGAE" in field:
        return random.choice(["English", "Spanish", "Hindi", "French", "Telugu"])

    # For grocery/list type textbox fields
    if "GROCERY" in field or "LIST" in field:
        items = ["Milk, Bread, Eggs", "Rice, Lentils, Vegetables",
                 "Fruits, Yogurt, Juice", "Pasta, Sauce, Cheese"]
        return random.choice(items)

    # For prescription/insurance/vehicle checkbox fields
    if "PRESCRIPTION" in field or "INSURANCE" in field or "VEHICLE" in field:
        return random.choice(["YES", "NO"])

    # For appointment/event type textbox fields
    if "APPOINTMENT" in field or "EVENT" in field:
        return random.choice([
            "Doctor Visit", "Dental Checkup", "Bank Appointment",
            "Court Hearing", "Physical Therapy", "Eye Exam"
        ])

    # For topic/subject/field of study textbox fields
    if "TOPIC" in field or "SUBJECT" in field or "STUDY" in field or "FIELD" in field:
        return random.choice([
            "Computer Science", "Biology", "Mathematics",
            "Business Administration", "Nursing", "Engineering"
        ])

    # For information/description textbox fields
    if "INFO" in field or "DESC" in field or "DETAIL" in field:
        return fake.sentence(nb_words=6)

    # Default → short realistic phrase
    return random.choice(["YES", "NO", "N/A", "Other"])

# ──────────────────────────────────────────────
# Generate req_add_info rows
# ──────────────────────────────────────────────
def generate_req_add_info(request_ids, metadata, list_items):
    rows = []
    cat_ids = list(metadata.keys())

    for request_id in request_ids:
        # Pick a random category for this request
        cat_id = random.choice(cat_ids)

        # Get all fields for this category
        fields = metadata[cat_id]

        # Generate one row per field for this request
        for field in fields:
            rows.append({
                "request_id":     request_id,
                "cat_id":         cat_id,
                "field_name_key": field["field_name_key"][:100],
                "field_value":    generate_field_value(
                                    field["field_id"],
                                    field["field_name_key"],
                                    field["field_type"],
                                    list_items
                                  )
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

    # Load valid list values grouped by field_id
    list_items = load_list_items()

    # Generate rows
    rows = generate_req_add_info(request_ids, metadata, list_items)

    # Save to CSV
    write_csv("req_add_info.csv", rows)

if __name__ == "__main__":
    main()