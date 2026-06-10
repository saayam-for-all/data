from pathlib import Path

import pandas as pd
import random
from faker import Faker
import os
import re
import sys

fake = Faker()

# -----------------------------
# CONFIG
# -----------------------------
BASE_SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
SCRIPT_DIR = Path(__file__).resolve().parent

LOOKUP_PATH = SCRIPT_DIR.parent / "lookup_tables"
OUTPUT_PATH = SCRIPT_DIR.parent / "mock_db"

os.makedirs(OUTPUT_PATH, exist_ok=True)

# -----------------------------
# LOAD CSV
# -----------------------------
def load_csv(table_name):
    path = os.path.join(LOOKUP_PATH, f"{table_name}.csv")

    if not os.path.exists(path):
        raise Exception(f"❌ Missing file: {table_name}.csv")

    df = pd.read_csv(path)

    if df.empty:
        raise Exception(f"❌ {table_name} is empty")

    return df


# -----------------------------
# COLUMN DETECTORS (SMART)
# -----------------------------
def detect_status_column(df):
    for col in df.columns:
        col_lower = col.lower()

        if "id" in col_lower:
            continue

        if "status" in col_lower:
            return col

    raise Exception("❌ No valid status column found (non-ID)")


def detect_cat_id_column(df):
    for col in df.columns:
        col_lower = col.lower()

        if "cat" in col_lower and "id" in col_lower:
            return col

    raise Exception("❌ No cat_id column found in help_categories")


# -----------------------------
# DATA HELPERS
# -----------------------------
def generate_clean_phone():
    return f"{random.randint(200,999)}-{random.randint(200,999)}-{random.randint(1000,9999)}"


def generate_clean_email(name):
    domains = ["gmail.com", "yahoo.com", "outlook.com"]
    clean_name = re.sub(r'[^a-zA-Z]', '', name).lower()
    return f"{clean_name}{random.randint(1,999)}@{random.choice(domains)}"


# -----------------------------
# DATA QUALITY CHECKS
# -----------------------------
def validate_no_nulls(df, table):
    if df.isnull().sum().sum() > 0:
        raise Exception(f"❌ Null values found in {table}")


def validate_unique(df, col, table):
    if df[col].duplicated().any():
        raise Exception(f"❌ Duplicate values in {table}.{col}")


# -----------------------------
# REQUEST TABLE
# -----------------------------
def generate_request_table(status_list):
    data = []

    for i in range(1, BASE_SIZE + 1):
        data.append({
            "request_id": i,
            "created_at": fake.date_time_this_year(),
            "status": random.choice(status_list)  # ✔ actual status value
        })

    df = pd.DataFrame(data)

    validate_no_nulls(df, "request")
    validate_unique(df, "request_id", "request")

    return df


# -----------------------------
# GUEST TABLE
# -----------------------------
def generate_guest_table(request_ids):
    rows = []

    for req_id in request_ids:
        for _ in range(random.randint(1, 3)):
            name = fake.name()
            rows.append({
                "guest_id": None,
                "req_id": req_id,
                "guest_name": name,
                "email": generate_clean_email(name),
                "phone": generate_clean_phone(),
                "city": fake.city(),
                "state": fake.state()
            })

    df = pd.DataFrame(rows)
    df["guest_id"] = range(1, len(df) + 1)

    validate_no_nulls(df, "request_guest_details")
    validate_unique(df, "guest_id", "request_guest_details")

    return df


# -----------------------------
# ADD INFO TABLE
# -----------------------------
def generate_add_info_table(request_ids, cat_ids):
    rows = []

    for req_id in request_ids:
        for _ in range(random.randint(0, 2)):
            rows.append({
                "add_info_id": None,
                "request_id": req_id,
                "cat_id": random.choice(cat_ids),  # ✔ strict FK
                "comments": fake.sentence()
            })

    df = pd.DataFrame(rows)

    if not df.empty:
        df["add_info_id"] = range(1, len(df) + 1)

        validate_no_nulls(df, "req_add_info")
        validate_unique(df, "add_info_id", "req_add_info")

    return df


# -----------------------------
# SAVE
# -----------------------------
def save_table(df, name):
    path = os.path.join(OUTPUT_PATH, f"{name}.csv")

    if os.path.exists(path):
        os.remove(path)

    df.to_csv(path, index=False)
    print(f"✅ {name}.csv → {len(df)} rows")


# -----------------------------
# MAIN
# -----------------------------
def main():
    print(f"\n🚀 Generating {BASE_SIZE} realistic records...\n")

    # -------------------------
    # LOAD LOOKUPS
    # -------------------------
    request_status_df = load_csv("request_status")
    help_categories_df = load_csv("help_categories")

    # detect correct columns
    status_col = detect_status_column(request_status_df)
    cat_col = detect_cat_id_column(help_categories_df)

    status_list = (
        request_status_df[status_col]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    cat_ids = (
        help_categories_df[cat_col]
        .dropna()
        .unique()
        .tolist()
    )

    # extra safety check (avoid ID column mistake)
    if all(str(x).isdigit() for x in status_list):
        raise Exception("❌ Wrong column selected: status looks numeric (ID)")

    # -------------------------
    # GENERATE TABLES
    # -------------------------
    request_df = generate_request_table(status_list)
    save_table(request_df, "request")

    guest_df = generate_guest_table(request_df["request_id"].tolist())
    save_table(guest_df, "request_guest_details")

    add_info_df = generate_add_info_table(
        request_df["request_id"].tolist(),
        cat_ids
    )
    save_table(add_info_df, "req_add_info")

    # -------------------------
    # FINAL VALIDATION
    # -------------------------
    assert set(request_df["status"]).issubset(set(status_list)), "❌ Invalid status"
    assert set(add_info_df["cat_id"]).issubset(set(cat_ids)), "❌ Invalid cat_id"

    print("\n🎯 Data Quality Checks Passed")
    print("✔ Status values (not IDs)")
    print("✔ FK integrity maintained")
    print("✔ No nulls / duplicates")
    print("✔ Lookup consistency")

    print(f"\n📁 Output location: {OUTPUT_PATH}")


# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    main()