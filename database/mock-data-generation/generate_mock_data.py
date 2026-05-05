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
            "req_fname": fake.first_name(),
            "req_lname": fake.last_name(),
            "req_email": fake.email(),
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
        rows.append({
            "request_id": req_id,
            "cat_id": random.choice(cat_ids),
            "field_name_key": random.choice(field_keys),
            "field_value": generate_field_value(random.choice(field_keys))
        })
    return rows


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    help_categories = pd.read_csv("database/lookup_tables/help_categories.csv")
    req_add_info_metadata = pd.read_csv("database/lookup_tables/req_add_info_metadata.csv")

    request_ids = generate_request_ids(ROW_COUNT)
    cat_ids = help_categories["cat_id"].dropna().astype(str).tolist()
    field_keys = req_add_info_metadata["field_name_key"].dropna().astype(str).tolist()

    guest_rows = generate_request_guest_details(request_ids)
    add_info_rows = generate_req_add_info(request_ids, cat_ids, field_keys)

    pd.DataFrame(guest_rows).to_csv(f"{OUTPUT_DIR}/request_guest_details.csv", index=False)
    pd.DataFrame(add_info_rows).to_csv(f"{OUTPUT_DIR}/req_add_info.csv", index=False)

    print("Generated request_guest_details and req_add_info successfully")


if __name__ == "__main__":
    main()