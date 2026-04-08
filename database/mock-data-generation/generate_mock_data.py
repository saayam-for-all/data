import pandas as pd
import random
import json
import os
from faker import Faker
from datetime import datetime, timedelta

# Initialize Faker
fake = Faker()
Faker.seed(42)
random.seed(42)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_DIR = os.path.join(BASE_DIR, '..', 'mock_db')
print(OUTPUT_DIR)
print(BASE_DIR)
# Configuration
NUM_BENEFICIARIES = 50
NUM_VOLUNTEERS = 100
TOTAL_USERS = NUM_BENEFICIARIES + NUM_VOLUNTEERS

def generate_data():
    print("Loading lookup files...")
    # Load Lookups
    try:
        states_df = pd.read_csv(os.path.join(BASE_DIR, 'state.csv'))
        categories_df = pd.read_csv(os.path.join(BASE_DIR, 'help_categories.csv'))
    except FileNotFoundError as e:
        print(f"Error: {e}. Files does not exist in directory!")
        return

    # Prepare lookup lists
    state_records = states_df[['state_id', 'country_id']].dropna().to_dict('records')
    # Filter out high-level categories (optional, to make skills more specific)
    sub_categories = categories_df[~categories_df['cat_id'].isin(['0.0.0.0.0', '1', '2', '3', '4', '5', '6'])]['cat_id'].tolist()
    
    users = []
    user_skills = []
    volunteer_applications = []

    print(f"Generating {TOTAL_USERS} users ({NUM_BENEFICIARIES} Beneficiaries, {NUM_VOLUNTEERS} Volunteers)...")
    
    # Create a list of user categories (50 Category 1, 100 Category 2)
    user_categories = [1] * NUM_BENEFICIARIES + [2] * NUM_VOLUNTEERS
    random.shuffle(user_categories) # Shuffle so they are mixed in the users table

    for i, cat_id in enumerate(user_categories, 1):
        user_id = f"U{i:04d}"
        
        # Pick random state and corresponding country
        loc = random.choice(state_records)
        state_id = loc['state_id']
        country_id = loc['country_id']
        
        # Fake personal details
        gender = random.choice(["Male", "Female", "Non-binary", "Prefer not to say"])
        first_name = fake.first_name_male() if gender == "Male" else fake.first_name_female()
        last_name = fake.last_name()
        middle_name = fake.first_name() if random.random() > 0.5 else ""
        full_name = f"{first_name} {middle_name} {last_name}".replace("  ", " ").strip()
        
        # Dates
        dob = fake.date_of_birth(minimum_age=18, maximum_age=80).strftime('%Y-%m-%d')
        last_update = fake.date_time_between(start_date='-1y', end_date='now')
        
        users.append({
            "user_id": user_id,
            "state_id": state_id,
            "country_id": country_id,
            "user_status_id": random.choice([1, 2]), 
            "user_category_id": cat_id,
            "full_name": full_name,
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,
            "primary_email_address": fake.unique.email(),
            "primary_phone_number": fake.phone_number()[:20],
            "addr_ln1": fake.street_address(),
            "addr_ln2": fake.secondary_address() if random.random() > 0.7 else "",
            "addr_ln3": "",
            "city_name": fake.city(),
            "zip_code": fake.postcode()[:20],
            "last_location": f"{fake.latitude()},{fake.longitude()}",
            "last_update_date": last_update.strftime('%Y-%m-%d %H:%M:%S'),
            "time_zone": fake.timezone(),
            "profile_picture_path": f"/assets/profiles/{user_id}.jpg",
            "gender": gender,
            "language_1": "English",
            "language_2": random.choice(["Spanish", "French", "German", "Hindi", "Mandarin", ""]),
            "language_3": "",
            "promotion_wizard_stage": random.randint(1, 4),
            "promotion_wizard_last_update_date": (last_update - timedelta(days=random.randint(1,30))).strftime('%Y-%m-%d %H:%M:%S'),
            "external_auth_provider": random.choice(["Google", "Facebook", "Email", "Apple"]),
            "dob": dob
        })

        # --- ONLY GENERATE SKILLS AND APPLICATIONS FOR VOLUNTEERS (Category 2) ---
        if cat_id == 2:
            # Generate 1 to 4 random skills for this volunteer
            assigned_skills = random.sample(sub_categories, k=random.randint(1, 4))
            
            app_created_date = last_update - timedelta(days=random.randint(30, 90))
            app_updated_date = app_created_date + timedelta(days=random.randint(1, 10))

            # 1. Add to user_skills
            for skill in assigned_skills:
                user_skills.append({
                    "user_id": user_id,
                    "cat_id": skill,
                    "created_date": app_created_date.strftime('%Y-%m-%d %H:%M:%S'),
                    "last_update_date": app_updated_date.strftime('%Y-%m-%d %H:%M:%S')
                })

            # 2. Add to volunteer_applications
            availability = {
                "weekdays": random.choice([True, False]),
                "weekends": random.choice([True, False]),
                "evenings": random.choice([True, False])
            }
            
            # Ensure at least one availability is true
            if not any(availability.values()):
                availability["weekends"] = True

            volunteer_applications.append({
                "user_id": user_id,
                "terms_and_conditions": True,
                "terms_accepted_at": app_created_date.strftime('%Y-%m-%d %H:%M:%S'),
                "govt_id_path": f"/secure/ids/{user_id}_id.pdf",
                "path_updated_at": app_created_date.strftime('%Y-%m-%d %H:%M:%S'),
                "skill_codes": json.dumps(assigned_skills),
                "availability": json.dumps(availability),
                "current_page": 4, # Assuming 4 is completed application
                "application_status": random.choice(["APPROVED", "PENDING", "UNDER_REVIEW"]),
                "is_completed": True,
                "created_at": app_created_date.strftime('%Y-%m-%d %H:%M:%S'),
                "last_updated_at": app_updated_date.strftime('%Y-%m-%d %H:%M:%S')
            })

    print("Converting to DataFrames and saving to CSVs...")
    
    # Convert to DataFrames
    df_users = pd.DataFrame(users)
    df_skills = pd.DataFrame(user_skills)
    df_apps = pd.DataFrame(volunteer_applications)

    def out_path(filename):
        return os.path.join(OUTPUT_DIR, filename)

    # Save to CSV
    df_users.to_csv(out_path("generated_users.csv")) # quoting=1 ensures strings with commas are wrapped in quotes
    df_skills.to_csv(out_path("generated_user_skills.csv"))
    df_apps.to_csv(out_path("generated_volunteer_applications.csv"))

    print(f"\nSuccess! Generated:")
    print(f"- {len(df_users)} total users ({NUM_BENEFICIARIES} Beneficiaries, {NUM_VOLUNTEERS} Volunteers) -> 'generated_users.csv'")
    print(f"- {len(df_skills)} user skills -> 'generated_user_skills.csv'")
    print(f"- {len(df_apps)} volunteer applications -> 'generated_volunteer_applications.csv'")

if __name__ == "__main__":
    generate_data()