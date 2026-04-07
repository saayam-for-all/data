import pandas as pd
import random
from datetime import datetime

random.seed(42)

def generate_skills():
    try:
        users_df = pd.read_csv('generated_users.csv')
        categories_df = pd.read_csv('help_categories.csv')
    except FileNotFoundError:
        print("Error: Ensure 'generated_users.csv' and 'help_categories.csv' exist.")
        return

    # Filter for Volunteers (Category 2)
    volunteers = users_df[users_df['user_category_id'] == 2]['user_id'].tolist()
    sub_categories = categories_df[~categories_df['cat_id'].isin(['0.0.0.0.0', '1', '2', '3', '4', '5', '6'])]['cat_id'].tolist()

    user_skills = []
    for user_id in volunteers:
        assigned = random.sample(sub_categories, k=random.randint(1, 4))
        for skill in assigned:
            user_skills.append({
                "user_id": user_id,
                "cat_id": skill,
                "created_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })

    df = pd.DataFrame(user_skills)
    df.to_csv("generated_user_skills.csv", index=False, quoting=1)
    print(f"Generated {len(df)} skill mappings to 'generated_user_skills.csv'")

if __name__ == "__main__":
    generate_skills()