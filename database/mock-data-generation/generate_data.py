import os
import json
import pandas as pd
import random
from faker import Faker

fake = Faker()

# -------------------------
# ROW CONFIGURATION
# -------------------------
TABLE_ROW_COUNTS = {
    "users": 100,
    "request": 100
}


# -------------------------
# LOAD SCHEMA
# -------------------------
def load_schema():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    schema_path = os.path.join(base_dir, "db_info.json")

    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


# -------------------------
# OUTPUT FOLDER
# -------------------------
def setup_output_folder():
    """
    Save generated CSV files in mock_db folder in the project root
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "mock_db")

    os.makedirs(output_dir, exist_ok=True)
    return output_dir

# -------------------------
# LOAD LOOKUP TABLES
# -------------------------
def load_lookup_table(table_name):
    """
    Load CSV from lookup_tables folder in the project root
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    lookup_dir = os.path.join(base_dir, "lookup_tables")

    possible_files = [
        os.path.join(lookup_dir, f"{table_name}.csv"),
        os.path.join(lookup_dir, f"{table_name}.CSV")
    ]

    print(f"Looking for {table_name} in: {lookup_dir}")

    for file_path in possible_files:
        if os.path.exists(file_path):
            print(f"✅ Loaded lookup table: {table_name}")
            return pd.read_csv(file_path)

    raise FileNotFoundError(f"Lookup table file not found for {table_name} in {lookup_dir}")

# -------------------------
# GENERIC VALUE GENERATOR
# -------------------------
def generate_value_from_type(col_name, col_type, i):
    col = col_name.lower()
    dtype = col_type.lower()

    if col == "user_id":
        return f"USR{i:05d}"

    if col == "req_id":
        return f"REQ{i:06d}"

    if col.endswith("_id"):
        return i

    if col == "full_name":
        return fake.name()

    if col == "first_name":
        return fake.first_name()

    if col == "middle_name":
        return fake.first_name()

    if col == "last_name":
        return fake.last_name()

    if "email" in col:
        return fake.email()

    if "phone" in col:
        return fake.phone_number()

    if col == "gender":
        return random.choice(["Male", "Female", "Other"])

    if "city" in col:
        return fake.city()

    if "state" in col:
        return fake.state()

    if "country" in col:
        return fake.country()

    if "addr" in col:
        return fake.street_address()

    if "zip" in col:
        return fake.postcode()

    if "date" in col or "time" in col:
        return fake.date_time_this_decade().strftime("%Y-%m-%d %H:%M:%S")

    if "boolean" in dtype:
        return random.choice([True, False])

    if "int" in dtype:
        return random.randint(1, 100)

    if "numeric" in dtype:
        return round(random.uniform(1, 100), 2)

    if "json" in dtype:
        return "{}"

    if "text" in dtype:
        return fake.sentence()

    return fake.word()


# -------------------------
# GENERATE NORMAL TABLE
# -------------------------
def generate_table(table_name, tables):
    columns = tables[table_name]["columns"]
    rows = TABLE_ROW_COUNTS.get(table_name, 100)

    data = []

    for i in range(1, rows + 1):
        row = {}

        for col in columns:
            col_name = col["name"]
            col_type = col["type"]

            row[col_name] = generate_value_from_type(col_name, col_type, i)

        data.append(row)

    return pd.DataFrame(data)


# -------------------------
# HELPER
# -------------------------
def get_column_values(df, column_name):
    if column_name in df.columns:
        return df[column_name].dropna().tolist()
    return []


# -------------------------
# GENERATE USERS
# -------------------------
def generate_users_table(
    tables,
    country_df,
    state_df,
    user_status_df,
    user_category_df
):
    columns = tables["users"]["columns"]
    rows = TABLE_ROW_COUNTS.get("users", 100)

    country_ids = get_column_values(country_df, "country_id")
    state_ids = get_column_values(state_df, "state_id")
    status_ids = get_column_values(user_status_df, "user_status_id")
    category_ids = get_column_values(user_category_df, "user_category_id")

    data = []

    for i in range(1, rows + 1):
        row = {}

        first_name = fake.first_name()
        middle_name = fake.first_name()
        last_name = fake.last_name()

        for col in columns:
            col_name = col["name"]
            col_type = col["type"]

            if col_name == "user_id":
                row[col_name] = f"USR{i:05d}"

            elif col_name == "country_id":
                row[col_name] = random.choice(country_ids)

            elif col_name == "state_id":
                row[col_name] = random.choice(state_ids)

            elif col_name == "user_status_id":
                row[col_name] = random.choice(status_ids)

            elif col_name == "user_category_id":
                row[col_name] = random.choice(category_ids)

            elif col_name == "first_name":
                row[col_name] = first_name

            elif col_name == "middle_name":
                row[col_name] = middle_name

            elif col_name == "last_name":
                row[col_name] = last_name

            elif col_name == "full_name":
                row[col_name] = f"{first_name} {middle_name} {last_name}"

            else:
                row[col_name] = generate_value_from_type(col_name, col_type, i)

        data.append(row)

    return pd.DataFrame(data)


# -------------------------
# GENERATE REQUEST
# -------------------------
def generate_request_table(
    tables,
    users_df,
    request_for_df,
    request_isleadvol_df,
    help_categories_df,
    request_type_df,
    request_priority_df,
    request_status_df
):
    columns = tables["request"]["columns"]
    rows = TABLE_ROW_COUNTS.get("request", 100)

    user_ids = get_column_values(users_df, "user_id")
    req_for_ids = get_column_values(request_for_df, "req_for_id")
    lead_ids = get_column_values(request_isleadvol_df, "req_islead_id")
    cat_ids = get_column_values(help_categories_df, "cat_id")
    type_ids = get_column_values(request_type_df, "req_type_id")
    priority_ids = get_column_values(request_priority_df, "req_priority_id")
    status_ids = get_column_values(request_status_df, "req_status_id")

    data = []

    for i in range(1, rows + 1):
        row = {}

        for col in columns:
            col_name = col["name"]
            col_type = col["type"]

            if col_name == "req_id":
                row[col_name] = f"REQ{i:06d}"

            elif col_name == "req_user_id":
                row[col_name] = random.choice(user_ids)

            elif col_name == "req_for_id":
                row[col_name] = random.choice(req_for_ids)

            elif col_name == "req_islead_id":
                row[col_name] = random.choice(lead_ids)

            elif col_name == "req_cat_id":
                row[col_name] = random.choice(cat_ids)

            elif col_name == "req_type_id":
                row[col_name] = random.choice(type_ids)

            elif col_name == "req_priority_id":
                row[col_name] = random.choice(priority_ids)

            elif col_name == "req_status_id":
                row[col_name] = random.choice(status_ids)

            else:
                row[col_name] = generate_value_from_type(col_name, col_type, i)

        data.append(row)

    return pd.DataFrame(data)


# -------------------------
# VALIDATION
# -------------------------
def validate_fk(child_df, child_col, parent_df, parent_col):
    invalid = child_df[~child_df[child_col].isin(parent_df[parent_col])]

    if len(invalid) == 0:
        print(f"✅ FK OK: {child_col} -> {parent_col}")
    else:
        print(f"❌ FK FAIL: {child_col} -> {parent_col} ({len(invalid)} invalid rows)")


def run_validations(generated_tables):
    print("\n🔍 Running Foreign Key Validations...\n")

    validate_fk(
        generated_tables["users"],
        "country_id",
        generated_tables["country"],
        "country_id"
    )

    validate_fk(
        generated_tables["users"],
        "state_id",
        generated_tables["state"],
        "state_id"
    )

    validate_fk(
        generated_tables["request"],
        "req_user_id",
        generated_tables["users"],
        "user_id"
    )


# -------------------------
# MAIN
# -------------------------
def main():
    print("🚀 ENGINE STARTED")

    schema = load_schema()
    tables = schema["tables"]

    output_dir = setup_output_folder()

    generated_tables = {}

    # -------------------------
    # LOOKUP TABLES
    # -------------------------
    lookup_first = [
        "country",
        "state",
        "user_status",
        "user_category",
        "request_for",
        "request_isleadvol",
        "request_priority",
        "request_status",
        "request_type",
        "help_categories"
    ]

    for table_name in lookup_first:
        if table_name in tables:
            df = load_lookup_table(table_name)
            generated_tables[table_name] = df

    # -------------------------
    # USERS
    # -------------------------
    users_df = generate_users_table(
        tables,
        generated_tables["country"],
        generated_tables["state"],
        generated_tables["user_status"],
        generated_tables["user_category"]
    )

    generated_tables["users"] = users_df
    print("✅ users created")

    # -------------------------
    # REQUEST
    # -------------------------
    request_df = generate_request_table(
        tables,
        generated_tables["users"],
        generated_tables["request_for"],
        generated_tables["request_isleadvol"],
        generated_tables["help_categories"],
        generated_tables["request_type"],
        generated_tables["request_priority"],
        generated_tables["request_status"]
    )

    generated_tables["request"] = request_df
    print("✅ request created")

    # -------------------------
    # OTHER TABLES
    # -------------------------
    already_done = set(generated_tables.keys())

    for table_name in tables:
        if table_name not in already_done:
            df = generate_table(table_name, tables)
            generated_tables[table_name] = df
            print(f"✅ {table_name} created")

    # -------------------------
    # VALIDATE
    # -------------------------
    run_validations(generated_tables)

    # -------------------------
    # SAVE CSV
    # -------------------------
    for table_name, df in generated_tables.items():
        output_file = os.path.join(output_dir, f"{table_name}.csv")
        df.to_csv(output_file, index=False)
        print(f"💾 Saved: {table_name}.csv")

    print("\n🎉 ALL TABLES GENERATED SUCCESSFULLY")


if __name__ == "__main__":
    main()
