import os
import json
import pandas as pd
import random
from faker import Faker

fake = Faker()

# Config
NUM_USERS = 40000
NUM_VOLUNTEERS_ASSIGNED = 25000
NUM_REQUESTS = 2000  # simulate request table

# -----------------------------
# Output Path (FIXED)
# -----------------------------
output_path = "mock_db"
os.makedirs(output_path, exist_ok=True)  # auto-create folder

# -----------------------------
# Generate Users (Reference)
# -----------------------------
users = pd.DataFrame({
    "user_id": range(1, NUM_USERS + 1),
    "name": [fake.name() for _ in range(NUM_USERS)],
    "email": [fake.unique.email() for _ in range(NUM_USERS)]
})

# -----------------------------
# Generate Requests (Reference)
# -----------------------------
requests = pd.DataFrame({
    "request_id": range(1, NUM_REQUESTS + 1),
    "request_date": [fake.date_between(start_date='-1y', end_date='today') for _ in range(NUM_REQUESTS)]
})

# -----------------------------
# Volunteer Details Table
# -----------------------------
volunteer_details = pd.DataFrame({
    "user_id": users["user_id"],
    "phone": [fake.phone_number() for _ in range(NUM_USERS)],
    "address": [fake.address().replace("\n", ", ") for _ in range(NUM_USERS)],
    "city": [fake.city() for _ in range(NUM_USERS)],
    "state": [fake.state() for _ in range(NUM_USERS)],
    "created_at": [fake.date_time_this_year() for _ in range(NUM_USERS)]
})

# -----------------------------
# Volunteers Assigned Table
# -----------------------------
volunteers_assigned = pd.DataFrame({
    "assignment_id": range(1, NUM_VOLUNTEERS_ASSIGNED + 1),
    "request_id": [random.choice(requests["request_id"]) for _ in range(NUM_VOLUNTEERS_ASSIGNED)],
    "volunteer_id": [random.choice(users["user_id"]) for _ in range(NUM_VOLUNTEERS_ASSIGNED)],
    "assigned_date": [fake.date_between(start_date='-1y', end_date='today') for _ in range(NUM_VOLUNTEERS_ASSIGNED)]
})

# -----------------------------
# Save CSVs (FIXED PATH)
# -----------------------------
volunteer_details.to_csv(f"{output_path}/volunteer_details.csv", index=False)
volunteers_assigned.to_csv(f"{output_path}/volunteers_assigned.csv", index=False)

print(" Mock data generated successfully!")