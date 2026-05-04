import pandas as pd
import random
from faker import Faker
from datetime import datetime

fake = Faker()

# -----------------------------
# CONFIG
# -----------------------------
NUM_ROWS = 100   # keep small as per requirement

# Simulated foreign keys
user_ids = [f"user_{i}" for i in range(1, 501)]
request_ids = [f"req_{i}" for i in range(1, 1001)]

# -----------------------------
# request_comments
# -----------------------------
request_comments = []

for i in range(NUM_ROWS):
    created = fake.date_time_between(start_date='-1y', end_date='now')
    updated = fake.date_time_between(start_date=created, end_date='now')

    request_comments.append({
        "comment_id": i + 1,
        "req_id": random.choice(request_ids),
        "commenter_id": random.choice(user_ids),
        "comment_desc": fake.sentence(nb_words=12),
        "created_at": created,
        "last_updated_at": updated,
        "isdeleted": random.choice([True, False])
    })

request_comments_df = pd.DataFrame(request_comments)

# -----------------------------
# volunteer_rating
# -----------------------------
volunteer_rating = []

for i in range(NUM_ROWS):
    volunteer_rating.append({
        "volunteer_rating_id": i + 1,
        "user_id": random.choice(user_ids),
        "request_id": random.choice(request_ids),
        "rating": random.choice(["1", "2", "3", "4", "5"]),  # enum
        "feedback": fake.sentence(nb_words=10),
        "last_update_date": fake.date_time_between(start_date='-1y', end_date='now')
    })

volunteer_rating_df = pd.DataFrame(volunteer_rating)

# -----------------------------
# SAVE FILES
# -----------------------------
request_comments_df.to_csv("../mock_db/request_comments.csv", index=False)
volunteer_rating_df.to_csv("../mock_db/volunteer_rating.csv", index=False)

print("CSV files generated successfully!")