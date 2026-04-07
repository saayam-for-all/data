import pandas as pd
import random
import json
from datetime import datetime

random.seed(42)

def generate_applications():
    try:
        users_df = pd.read_csv('generated_users.csv')
        skills_df = pd.read_csv('generated_user_skills.csv')
    except FileNotFoundError:
        print("Error: Pre-requisite CSVs missing.")
        return

    volunteers = users_df[users_df['user_category_id'] == 2]['user_id'].tolist()
    apps = []

    for user_id in volunteers:
        # Get skills already assigned to this user
        user_skills = skills_df[skills_df['user_id'] == user_id]['cat_id'].tolist()
        
        availability = {
            "weekdays": random.choice([True, False]),
            "weekends": True,
            "evenings": random.choice([True, False])
        }

        apps.append({
            "user_id": user_id,
            "skill_codes": json.dumps(user_skills),
            "availability": json.dumps(availability),
            "application_status": random.choice(["APPROVED", "PENDING"]),
            "is_completed": True,
            "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

    df = pd.DataFrame(apps)
    df.to_csv("generated_volunteer_applications.csv", index=False, quoting=1)
    print(f"Generated {len(df)} applications to 'generated_volunteer_applications.csv'")

if __name__ == "__main__":
    generate_applications()