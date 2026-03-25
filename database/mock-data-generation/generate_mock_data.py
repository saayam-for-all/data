from faker import Faker
import pandas as pd
import random
import os

NUM_ROWS = 100

fake = Faker()

# ---------- USERS ----------
def generate_users(n):
    users = []
    for i in range(1, n + 1):
        users.append({
            "user_id": i,
            "name": fake.name(),
            "email": fake.email(),
            "state_id": random.randint(1, 5),
            "country_id": random.randint(1, 3),
            "user_status_id": random.randint(1, 3),
            "user_category_id": random.randint(1, 3)
        })
    return pd.DataFrame(users)


# REQUEST 
def generate_requests(n):
    requests = []
    for i in range(1, n + 1):
        requests.append({
            "request_id": i,
            "req_user_id": random.randint(1, n),
            "req_title": fake.sentence(nb_words=5),
            "req_description": fake.text(max_nb_chars=100),
            "req_cat_id": random.randint(1, 5),
            "req_priority_id": random.randint(1, 3),
            "req_status_id": random.randint(1, 3)
        })
    return pd.DataFrame(requests)


# VOLUNTEERS
def generate_volunteers(n):
    volunteers = []
    for i in range(1, n + 1):
        volunteers.append({
            "volunteer_id": i,
            "user_id": random.randint(1, n),
            "skills": fake.job(),
            "rating": round(random.uniform(1, 5), 2)
        })
    return pd.DataFrame(volunteers)


# COMMENTS 
def generate_comments(n):
    comments = []
    for i in range(1, n + 1):
        comments.append({
            "comment_id": i,
            "request_id": random.randint(1, n),
            "user_id": random.randint(1, n),
            "comment": fake.sentence(),
        })
    return pd.DataFrame(comments)


# MAIN 
def main():
    os.makedirs("../mock_db", exist_ok=True)

    users_df = generate_users(NUM_ROWS)
    request_df = generate_requests(NUM_ROWS)
    volunteers_df = generate_volunteers(NUM_ROWS)
    comments_df = generate_comments(NUM_ROWS)

    users_df.to_csv("../mock_db/users.csv", index=False)
    print("Generated users.csv")

    request_df.to_csv("../mock_db/request.csv", index=False)
    print("Generated request.csv")

    volunteers_df.to_csv("../mock_db/volunteer_details.csv", index=False)
    print("Generated volunteer_details.csv")

    comments_df.to_csv("../mock_db/request_comments.csv", index=False)
    print("Generated request_comments.csv")


if __name__ == "__main__":
    main()