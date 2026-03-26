from faker import Faker
import pandas as pd
import random
import os

fake = Faker()


# CONFIG
NUM_ROWS = 100
OUTPUT_DIR = "../mock_db"

# Create output directory if not exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Country-State Mapping
country_state_map = {
    1: [1, 2],     # Country 1 → States 1,2
    2: [3, 4],     # Country 2 → States 3,4
    3: [5]         # Country 3 → State 5
}

def get_country_state():
    country_id = random.choice(list(country_state_map.keys()))
    state_id = random.choice(country_state_map[country_id])
    return country_id, state_id



# USERS TABLE
users = []

for i in range(1, NUM_ROWS + 1):
    country_id, state_id = get_country_state()  

    users.append({
        "user_id": i,
        "name": fake.name(),
        "email": fake.email(),
        "state_id": state_id,
        "country_id": country_id,
        "user_status_id": random.randint(1, 3),
        "user_category_id": random.randint(1, 3)
    })

users_df = pd.DataFrame(users)


# REQUEST TABLE
requests = []

for i in range(1, NUM_ROWS + 1):
    requests.append({
        "req_id": i,  
        "req_user_id": random.randint(1, NUM_ROWS),
        "req_subj": fake.sentence(nb_words=5), 
        "req_desc": fake.text(max_nb_chars=100),
        "req_cat_id": random.randint(1, 5),
        "req_priority_id": random.randint(1, 3),
        "req_status_id": random.randint(1, 3)
    })

request_df = pd.DataFrame(requests)

# VOLUNTEER DETAILS
volunteers = []

for i in range(1, NUM_ROWS + 1):
    volunteers.append({
        "volunteer_id": i,
        "user_id": random.randint(1, NUM_ROWS),  # FK to users
        "skills": fake.job(),
        "rating": round(random.uniform(1, 5), 2)
    })

volunteers_df = pd.DataFrame(volunteers)

# REQUEST COMMENTS
comments = []

for i in range(1, NUM_ROWS + 1):
    comments.append({
    "comment_id": i,
    "req_id": random.randint(1, NUM_ROWS),  
    "commenter_id": random.randint(1, NUM_ROWS), 
    "comment_desc": fake.sentence(),         
})

comments_df = pd.DataFrame(comments)

# SAVE FILES
users_df.to_csv(f"{OUTPUT_DIR}/users.csv", index=False)
request_df.to_csv(f"{OUTPUT_DIR}/request.csv", index=False)
volunteers_df.to_csv(f"{OUTPUT_DIR}/volunteer_details.csv", index=False)
comments_df.to_csv(f"{OUTPUT_DIR}/request_comments.csv", index=False)

print("CSV files generated successfully with consistent data!")