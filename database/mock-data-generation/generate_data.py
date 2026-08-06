import json
import random
import os
import pandas as pd
from faker import Faker

fake = Faker()

# Config
NUM_RECORDS = 100
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'mock_db')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Load schema
with open("db_info.json") as f:
    schema = json.load(f)["tables"]  # adjust if your JSON has a different top-level key

# Example lookup table IDs (update if you have real lookup CSVs)
category_ids = [1, 2, 3, 4, 5]  # example cat_ids

# Store created primary keys to use for foreign keys
generated_ids = {}

def generate_value(col_name, col_type, table_name):
    """Generate realistic value based on column name/type"""
    col_name_lower = col_name.lower()

    if "name" in col_name_lower:
        return fake.first_name() if "fname" in col_name_lower else fake.last_name() if "lname" in col_name_lower else fake.name()
    elif "email" in col_name_lower:
        return fake.email()
    elif "phone" in col_name_lower:
        return fake.phone_number()
    elif "address" in col_name_lower:
        return fake.address()
    elif "date" in col_name_lower:
        return fake.date()
    elif "id" in col_name_lower:
        # IDs will be assigned later if foreign key
        return None
    elif "age" in col_name_lower:
        return random.randint(18, 80)
    elif "gender" in col_name_lower:
        return random.choice(["Male", "Female", "Other"])
    elif "lang" in col_name_lower:
        return random.choice(["English", "Hindi", "Spanish", "French"])
    else:
        return fake.word()

def generate_table(table_name, table_schema):
    columns = table_schema["columns"]
    data = []

    # Determine primary key column
    pk_cols = [col["name"] for col in columns if col.get("primary_key")]

    for i in range(NUM_RECORDS):
        row = {}
        for col in columns:
            col_name = col["name"]
            value = generate_value(col_name, col["type"], table_name)

            # Handle foreign keys
            if col_name.lower() in ["req_id", "request_id"]:
                # Use previously generated IDs or generate new PK
                if col_name.lower() == "req_id":
                    value = i + 1  # simple sequential PK
                else:
                    value = random.choice(generated_ids.get("request_guest_details", [1]))
            elif col_name.lower() == "cat_id":
                value = random.choice(category_ids)

            row[col_name] = value

        data.append(row)

    # Store generated PKs for FK reference
    if pk_cols:
        for pk in pk_cols:
            generated_ids[table_name] = [row[pk] for row in data]

    df = pd.DataFrame(data)
    df.to_csv(os.path.join(OUTPUT_DIR, f"{table_name}.csv"), index=False)
    print(f"✅ {table_name}.csv generated with {NUM_RECORDS} rows!")

# Loop through all tables in schema
for table_name, table_schema in schema.items():
    generate_table(table_name, table_schema)