import pandas as pd
import random
from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)

def generate_users(num_beneficiaries=50, num_volunteers=100):
    try:
        states_df = pd.read_csv('state.csv')
    except FileNotFoundError:
        print("Error: state.csv not found in current directory.")
        return

    state_records = states_df[['state_id', 'country_id']].dropna().to_dict('records')
    total_users = num_beneficiaries + num_volunteers
    user_categories = [1] * num_beneficiaries + [2] * num_volunteers
    random.shuffle(user_categories)

    users = []
    for i, cat_id in enumerate(user_categories, 1):
        loc = random.choice(state_records)
        gender = random.choice(["Male", "Female", "Non-binary", "Prefer not to say"])
        first_name = fake.first_name_male() if gender == "Male" else fake.first_name_female()
        last_name = fake.last_name()
        
        users.append({
            "user_id": f"U{i:04d}",
            "state_id": loc['state_id'],
            "country_id": loc['country_id'],
            "user_category_id": cat_id,
            "full_name": f"{first_name} {last_name}",
            "primary_email_address": fake.unique.email(),
            "gender": gender,
            "dob": fake.date_of_birth(minimum_age=18, maximum_age=80).strftime('%Y-%m-%d')
        })
    
    df = pd.DataFrame(users)
    df.to_csv("generated_users.csv", index=False, quoting=1)
    print(f"Generated {len(df)} users to 'generated_users.csv'")
    return df

if __name__ == "__main__":
    generate_users()