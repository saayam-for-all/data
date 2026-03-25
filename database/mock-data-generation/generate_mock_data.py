from faker import Faker
import pandas as pd
import random

fake = Faker()
users = []

for i in range(1, 101):
    users.append({
        "user_id": i,
        "name": fake.name(),
        "email": fake.email(),
        "state_id": random.randint(1, 5),
        "country_id": random.randint(1, 3),
        "user_status_id": random.randint(1, 3),
        "user_category_id": random.randint(1, 3)
    })

users_df = pd.DataFrame(users)

requests = []

for i in range(1, 101):
    requests.append({
        "request_id": i,
        "req_user_id": random.randint(1, 100),  # FK to users
        "req_title": fake.sentence(nb_words=5),
        "req_description": fake.text(max_nb_chars=100),
        "req_cat_id": random.randint(1, 5),
        "req_priority_id": random.randint(1, 3),
        "req_status_id": random.randint(1, 3)
    })

request_df = pd.DataFrame(requests)

users_df.to_csv("../mock_db/users.csv", index=False)
request_df.to_csv("../mock_db/request.csv", index=False)

print("CSV files generated successfully!")