import os
import random
import pandas as pd
from faker import Faker

fake = Faker()
ROW_COUNT = 100
OUTPUT_DIR = "database/mock_db"


def generate_request_ids(count=100):
    return [f"REQ{i:03d}" for i in range(1, count + 1)]


def generate_request_guest_details(request_ids):
    rows = []
    for req_id in request_ids:
        rows.append({
            "req_id": req_id,
            "req_fname": fake.first_name()[:100],
            "req_lname": fake.last_name()[:100],
            "req_email": fake.email()[:100],
            "req_phone": fake.msisdn()[:20],
            "req_age": random.randint(18, 80),
            "req_gender": random.choice(["Male", "Female", "Other"]),
            "req_pref_lang": random.choice(["English", "Hindi", "Tamil", "Marathi"])
        })
    return rows


def generate_field_value(field_key):
    key = field_key.lower()

    if "income" in key:
        return str(random.randint(5000, 50000))
    elif "age" in key:
        return str(random.randint(18, 80))
    elif "phone" in key:
        return fake.msisdn()[:20]
    elif "email" in key:
        return fake.email()
    elif "name" in key:
        return fake.name()
    elif "occupation" in key:
        return fake.job()
    elif "gender" in key:
        return random.choice(["Male", "Female", "Other"])
    elif "lang" in key:
        return random.choice(["English", "Hindi", "Tamil", "Marathi"])
    else:
        return fake.word()


def generate_req_add_info(request_ids, cat_ids, field_keys):
    rows = []
    for req_id in request_ids:
        field_key = random.choice(field_keys)
        rows.append({
            "request_id": req_id,
            "cat_id": random.choice(cat_ids),
            "field_name_key": field_key,
            "field_value": generate_field_value(field_key)
        })
    return rows


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    help_categories = pd.read_csv("database/lookup_tables/help_categories.csv")
    req_add_info_metadata = pd.read_csv("database/lookup_tables/req_add_info_metadata.csv")

    request_csv_path = os.path.join(OUTPUT_DIR, "request.csv")
    if os.path.exists(request_csv_path):
        request_df = pd.read_csv(request_csv_path)
        request_ids = request_df["req_id"].dropna().astype(str).tolist()[:ROW_COUNT]
    else:
        request_ids = generate_request_ids(ROW_COUNT)

    cat_ids = help_categories["cat_id"].dropna().astype(str).tolist()
    field_keys = req_add_info_metadata["field_name_key"].dropna().astype(str).tolist()

    guest_rows = generate_request_guest_details(request_ids)
    add_info_rows = generate_req_add_info(request_ids, cat_ids, field_keys)

    guest_df = pd.DataFrame(guest_rows)
    add_info_df = pd.DataFrame(add_info_rows)

    guest_df = guest_df[
        ["req_id", "req_fname", "req_lname", "req_email", "req_phone", "req_age", "req_gender", "req_pref_lang"]
    ]

    add_info_df = add_info_df[
        ["request_id", "cat_id", "field_name_key", "field_value"]
    ]

    assert len(guest_df) <= 100
    assert len(add_info_df) <= 100

    assert guest_df["req_id"].notna().all()
    assert add_info_df["request_id"].notna().all()

    assert guest_df["req_fname"].str.len().max() <= 100
    assert guest_df["req_lname"].str.len().max() <= 100
    assert guest_df["req_email"].str.len().max() <= 100
    assert guest_df["req_phone"].str.len().max() <= 20

    assert set(guest_df["req_id"]).issubset(set(request_ids))
    assert set(add_info_df["request_id"]).issubset(set(request_ids))
    assert set(add_info_df["cat_id"]).issubset(set(cat_ids))

    guest_df.to_csv(f"{OUTPUT_DIR}/request_guest_details.csv", index=False)
    add_info_df.to_csv(f"{OUTPUT_DIR}/req_add_info.csv", index=False)

    print(f"Generated {len(guest_df)} request_guest_details rows")
    print(f"Generated {len(add_info_df)} req_add_info rows")
    print("Mock data generated successfully.")


if __name__ == "__main__":
    main()