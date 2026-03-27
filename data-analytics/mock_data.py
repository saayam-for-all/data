# generate_mock_data.py

import pandas as pd
import numpy as np
from faker import Faker
from datetime import datetime, timedelta

fake = Faker()
np.random.seed(42)


# Paths
LOOKUP_PATH = "database/lookup_tables/"
OUTPUT_PATH = "database/mock_db/"


# Load Lookup Tables
state_df = pd.read_csv(LOOKUP_PATH + "state.csv")
country_df = pd.read_csv(LOOKUP_PATH + "country.csv")
user_status_df = pd.read_csv(LOOKUP_PATH + "user_status.csv")
user_category_df = pd.read_csv(LOOKUP_PATH + "user_category.csv")
request_for_df = pd.read_csv(LOOKUP_PATH + "request_for.csv")
request_islead_df = pd.read_csv(LOOKUP_PATH + "request_isleadvol.csv")
help_category_df = pd.read_csv(LOOKUP_PATH + "help_categories.csv")
request_type_df = pd.read_csv(LOOKUP_PATH + "request_type.csv")
request_priority_df = pd.read_csv(LOOKUP_PATH + "request_priority.csv")
request_status_df = pd.read_csv(LOOKUP_PATH + "request_status.csv")


# Generate Users Table
def generate_users(n=100):
    users = []
    for i in range(1, n+1):
        users.append({
            "user_id": i,
            "name": fake.name(),
            "email": fake.email(),
            "phone": fake.phone_number(),
            "state_id": np.random.choice(state_df["state_id"]),
            "country_id": np.random.choice(country_df["country_id"]),
            "user_status_id": np.random.choice(user_status_df["user_status_id"]),
            "user_category_id": np.random.choice(user_category_df["user_category_id"])
        })
    return pd.DataFrame(users)

users_df = generate_users()
users_df.to_csv(OUTPUT_PATH + "users.csv", index=False)
print("users.csv generated successfully!")


# Generate Requests Table
def generate_requests(n=100, users_df=users_df):
    requests = []
    for i in range(1, n+1):
        created = fake.date_time_this_year()
        resolved = fake.date_time_between(start_date=created)
        requests.append({
            "request_id": i,
            "req_user_id": np.random.choice(users_df["user_id"]),
            "req_for_id": np.random.choice(users_df["user_id"]),
            "req_islead_id": np.random.choice(request_islead_df["req_islead_id"]),
            "req_cat_id": np.random.choice(help_category_df["cat_id"]),
            "req_type_id": np.random.choice(request_type_df["req_type_id"]),
            "req_priority_id": np.random.choice(request_priority_df["req_priority_id"]),
            "req_status_id": np.random.choice(request_status_df["req_status_id"]),
            "created_at": created,
            "resolved_at": resolved,
            "resolution_time_hours": (resolved - created).total_seconds()/3600
        })
    return pd.DataFrame(requests)

request_df = generate_requests()
request_df.to_csv(OUTPUT_PATH + "request.csv", index=False)
print("request.csv generated successfully!")
