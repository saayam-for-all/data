import os
import random

import pandas as pd
from faker import Faker

from common_utils import (
    load_lookup,
    get_id_values,
    random_datetime
)

print("SCRIPT STARTED")

fake = Faker()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LOOKUP_DIR = os.path.join(BASE_DIR, "lookup_tables")
OUTPUT_DIR = os.path.join(BASE_DIR, "mock_db")

os.makedirs(OUTPUT_DIR, exist_ok=True)

USERS_ROWS = 5000
REQUEST_ROWS = 20000


def generate_users():

    state_df = load_lookup(LOOKUP_DIR, "state.csv")
    country_df = load_lookup(LOOKUP_DIR, "country.csv")
    user_status_df = load_lookup(LOOKUP_DIR, "user_status.csv")
    user_category_df = load_lookup(LOOKUP_DIR, "user_category.csv")

    state_ids = get_id_values(state_df)
    country_ids = get_id_values(country_df)
    user_status_ids = get_id_values(user_status_df)
    user_category_ids = get_id_values(user_category_df)

    users = []

    genders = ["Male", "Female", "Other"]

    languages = ["English", "Spanish", "Hindi", "French"]

    for i in range(1, USERS_ROWS + 1):

        first_name = fake.first_name()
        middle_name = fake.first_name()
        last_name = fake.last_name()

        created_date = random_datetime()

        users.append({
            "user_id": f"USR{i:05}",
            "state_id": random.choice(state_ids),
            "country_id": random.choice(country_ids),
            "user_status_id": random.choice(user_status_ids),
            "user_category_id": random.choice(user_category_ids),

            "full_name": f"{first_name} {last_name}",
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,

            "primary_email_address": fake.unique.email(),
            "primary_phone_number": fake.phone_number(),

            "addr_ln1": fake.street_address(),
            "addr_ln2": fake.secondary_address(),
            "addr_ln3": "",

            "city_name": fake.city(),
            "zip_code": fake.postcode(),

            "last_location": fake.city(),

            "last_update_date": created_date,

            "time_zone": "UTC",

            "profile_picture_path": f"/images/profile_{i}.jpg",

            "gender": random.choice(genders),

            "language_1": random.choice(languages),
            "language_2": random.choice(languages),
            "language_3": random.choice(languages),

            "promotion_wizard_stage": random.randint(1, 5),

            "promotion_wizard_last_update_date": created_date,

            "external_auth_provider": random.choice(
                ["google", "facebook", "email"]
            ),

            "dob": fake.date_of_birth(
                minimum_age=18,
                maximum_age=80
            )
        })

    users_df = pd.DataFrame(users)

    users_path = os.path.join(
        OUTPUT_DIR,
        "users.csv"
    )

    users_df.to_csv(users_path, index=False)

    print(f"Generated users.csv with {len(users_df)} rows")

    return users_df


def generate_request(users_df):

    request_for_df = load_lookup(
        LOOKUP_DIR,
        "request_for.csv"
    )

    request_isleadvol_df = load_lookup(
        LOOKUP_DIR,
        "request_isleadvol.csv"
    )

    help_categories_df = load_lookup(
        LOOKUP_DIR,
        "help_categories.csv"
    )

    request_type_df = load_lookup(
        LOOKUP_DIR,
        "request_type.csv"
    )

    request_priority_df = load_lookup(
        LOOKUP_DIR,
        "request_priority.csv"
    )

    request_status_df = load_lookup(
        LOOKUP_DIR,
        "request_status.csv"
    )

    request_for_ids = get_id_values(request_for_df)

    request_islead_ids = get_id_values(
        request_isleadvol_df
    )

    help_category_ids = get_id_values(
        help_categories_df
    )

    request_type_ids = get_id_values(
        request_type_df
    )

    request_priority_ids = get_id_values(
        request_priority_df
    )

    request_status_ids = get_id_values(
        request_status_df
    )

    user_ids = users_df["user_id"].tolist()

    requests = []

    for i in range(1, REQUEST_ROWS + 1):

        submission_date = random_datetime()

        requests.append({

            "req_id": f"REQ{i:06}",

            "req_user_id": random.choice(user_ids),

            "req_for_id": random.choice(
                request_for_ids
            ),

            "req_islead_id": random.choice(
                request_islead_ids
            ),

            "req_cat_id": random.choice(
                help_category_ids
            ),

            "req_type_id": random.choice(
                request_type_ids
            ),

            "req_priority_id": random.choice(
                request_priority_ids
            ),

            "req_status_id": random.choice(
                request_status_ids
            ),

            "req_loc": fake.city(),

            "iscalamity": random.choice(
                [True, False]
            ),

            "req_subj": fake.sentence(nb_words=5),

            "req_desc": fake.text(max_nb_chars=200),

            "req_doc_link": fake.url(),

            "audio_req_desc": fake.file_name(
                extension="mp3"
            ),

            "submission_date": submission_date,

            "serviced_date": random_datetime(),

            "last_update_date": random_datetime(),

            "to_public": random.choice(
                [True, False]
            )
        })

    request_df = pd.DataFrame(requests)

    request_path = os.path.join(
        OUTPUT_DIR,
        "request.csv"
    )

    request_df.to_csv(request_path, index=False)

    print(
        f"Generated request.csv with "
        f"{len(request_df)} rows"
    )

    return request_df


def validate_data(users_df, request_df):

    print("Running validations...")

    assert users_df["user_id"].is_unique
    assert request_df["req_id"].is_unique

    invalid_users = request_df[
        ~request_df["req_user_id"].isin(
            users_df["user_id"]
        )
    ]

    assert len(invalid_users) == 0

    print("Validation successful")


def main():

    users_df = generate_users()

    request_df = generate_request(
        users_df
    )

    validate_data(
        users_df,
        request_df
    )


if __name__ == "__main__":
    main()