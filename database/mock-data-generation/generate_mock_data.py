import argparse

import pandas as pd
import random
import uuid
from faker import Faker
from datetime import datetime, timedelta
import os
# Initialize Faker
fake = Faker()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_DIR = os.path.join(BASE_DIR, '..', 'mock_db')

def generate_users(num_records=500, output_filename='mock_users.csv'):
    print("Generating Users...")
    try:
        state_df = pd.read_csv(os.path.join(BASE_DIR, 'state.csv'))
        user_cat_df = pd.read_csv(os.path.join(BASE_DIR, 'user_category.csv'))
    except FileNotFoundError as e:
        print(f"Error loading lookup files for users: {e}")
        return None

    valid_category_ids = user_cat_df['user_category_id'].tolist()
    valid_states = state_df[['state_id', 'country_id']].dropna().to_dict('records')

    users_data = []

    for i in range(1, num_records + 1):
        location = random.choice(valid_states)
        state_id = str(location['state_id'])
        country_id = int(location['country_id'])
        
        first_name = fake.first_name()
        last_name = fake.last_name()
        middle_name = fake.first_name() if random.random() > 0.5 else ""
        full_name = f"{first_name} {middle_name} {last_name}".replace("  ", " ").strip()
        
        now = datetime.now()
        last_update = fake.date_time_between(start_date='-1y', end_date='now', tzinfo=None)
        dob = fake.date_of_birth(minimum_age=18, maximum_age=90)
        wizard_update = last_update - timedelta(days=random.randint(1, 30))

        user_record = {
            "user_id": f"U{i}", 
            "state_id": state_id,
            "country_id": country_id,
            "user_status_id": random.randint(1, 5),
            "user_category_id": random.choice(valid_category_ids),
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
            "zip_code": fake.postcode(),
            "last_location": f"{fake.latitude()},{fake.longitude()}",
            "last_update_date": last_update.isoformat(sep=' ') + '+00',
            "time_zone": fake.timezone(),
            "profile_picture_path": f"/images/profiles/{fake.uuid4()}.jpg", 
            "gender": random.choice(["Male", "Female", "Non-Binary", "Prefer not to say"]),
            "language_1": random.choice(["English", "Spanish", "French", "German", "Mandarin"]),
            "language_2": random.choice(["English", "Spanish", "French", "None", "None"]),
            "language_3": "None",
            "promotion_wizard_stage": random.randint(1, 4),
            "promotion_wizard_last_update_date": wizard_update.isoformat(sep=' ') + '+00',
            "external_auth_provider": random.choice(["Google", "Apple", "Facebook", "None", "None"]),
            "dob": dob.strftime('%Y-%m-%d')
        }
        users_data.append(user_record)

    users_df = pd.DataFrame(users_data)
    users_df.to_csv(os.path.join(OUTPUT_DIR, output_filename), index=False)
    print(f"-> Successfully generated {num_records} users. Saved to '{output_filename}'\n")
    return users_df


def generate_notifications(users_df, num_records=100, output_filename='mock_notifications.csv'):
    print("Generating Notifications...")
    try:
        types_df = pd.read_csv(os.path.join(BASE_DIR, 'notification_types.csv'))
        channels_df = pd.read_csv(os.path.join(BASE_DIR, 'notification_channels.csv'))
    except FileNotFoundError as e:
        print(f"Error loading lookup files for notifications: {e}")
        return None

    valid_user_ids = users_df['user_id'].tolist()
    valid_type_ids = types_df['type_id'].tolist()
    valid_channel_ids = channels_df['channel_id'].tolist()
    valid_statuses = ['PENDING', 'SENT', 'DELIVERED', 'READ', 'FAILED']

    # Curated contextual messages mapped by notification type_id
    # 1: ALERT, 10: EVENT_REMINDER, 11: MESSAGE_RECEIVED, 12: APPLICATION_UPDATE, 13: MILESTONE_REACHED
    message_templates = {
        1: [
            "Action Required: Unusual login activity detected on your account.",
            "Urgent Alert: Platform maintenance is scheduled for tonight from 2AM to 4AM EST.",
            "Security Alert: Your password will expire in 3 days. Please update it.",
            "System Alert: We are experiencing delays in processing requests today."
        ],
        10: [
            "Reminder: Your registered volunteer shift starts tomorrow at 9:00 AM.",
            "Don't forget! You have an upcoming community event this weekend.",
            "Your scheduled assistance request is happening in 24 hours.",
            "Reminder: Please check-in via the app 15 minutes before your event starts."
        ],
        11: [
            "You have received a new direct message from a beneficiary.",
            "A volunteer has replied to your help request.",
            "You have unread messages in your inbox from a platform steward.",
            "New message received regarding your upcoming appointment."
        ],
        12: [
            "Great news! Your volunteer application has been approved.",
            "Your profile application is currently under review by our team.",
            "Action Required: We need a bit more information to complete your application.",
            "Your background check documentation has been successfully verified."
        ],
        13: [
            "Congratulations! You just surpassed 50 hours of volunteer service.",
            "Amazing work! You've earned the 'Community Hero' milestone badge.",
            "Thank you! Your recent help request marked your 10th successful match on the platform.",
            "Milestone Reached: You've been an active member of our community for 1 year!"
        ]
    }

    notifications_data = []

    for i in range(1, num_records + 1):
        created_at = fake.date_time_between(start_date='-6m', end_date='now')
        last_update_date = created_at + timedelta(minutes=random.randint(1, 1440))
        
        # Pick a random type_id
        selected_type_id = random.choice(valid_type_ids)
        
        # Get a relevant message for that type_id (fallback to generic if ID not in dict)
        if selected_type_id in message_templates:
            message = random.choice(message_templates[selected_type_id])
        else:
            message = "You have a new notification regarding your account."
        
        notification_record = {
            "notification_id": i,
            "user_id": random.choice(valid_user_ids),
            "type_id": selected_type_id,
            "channel_id": random.choice(valid_channel_ids),
            "message": message,
            "status": random.choice(valid_statuses),
            "created_at": created_at.strftime('%Y-%m-%d %H:%M:%S'),
            "last_update_date": last_update_date.strftime('%Y-%m-%d %H:%M:%S')
        }
        notifications_data.append(notification_record)

    notifications_df = pd.DataFrame(notifications_data)
    notifications_df.to_csv(os.path.join(OUTPUT_DIR, output_filename), index=False)
    print(f"-> Successfully generated {num_records} notifications. Saved to '{output_filename}'\n")
    return notifications_df


def generate_fraud_requests(users_df, num_records=50, output_filename='mock_fraud_requests.csv'):
    print("Generating Fraud Requests...")
    valid_user_ids = users_df['user_id'].tolist()
    
    fraud_reasons = [
        "Unauthorized transaction detected on my account.",
        "Another user requested sensitive financial information.",
        "The volunteer assigned to me asked for payment outside the platform.",
        "My account details were modified without my consent.",
        "Received suspicious phishing links in my direct messages.",
        "Service was marked as completed but the volunteer never arrived.",
        "Suspected identity theft; someone created a duplicate profile of me.",
        "User refused to provide the agreed-upon assistance after I provided details.",
        "Inappropriate or abusive behavior from a matched user.",
        "I believe this user profile is a bot or fake account."
    ]

    fraud_data = []

    for i in range(1, num_records + 1):
        request_datetime = fake.date_time_between(start_date='-3m', end_date='now')
        
        fraud_record = {
            "fraud_request_id": i,
            "user_id": random.choice(valid_user_ids),
            "request_datetime": request_datetime.strftime('%Y-%m-%d %H:%M:%S'),
            "reason": random.choice(fraud_reasons)
        }
        fraud_data.append(fraud_record)

    fraud_df = pd.DataFrame(fraud_data)
    fraud_df.to_csv(os.path.join(OUTPUT_DIR, output_filename), index=False)
    print(f"-> Successfully generated {num_records} fraud requests. Saved to '{output_filename}'\n")
    return fraud_df



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate mock tables, Generate user table first, default records are 100 for all tables")

    parser.add_argument("--users", type=int, default=100, help="Number of users to generate")

    parser.add_argument("--notifications", type=int, default=100, help="Number of notifications")

    parser.add_argument("--fraud", type=int, default=100, help="Number of fraud requests")
 
    args = parser.parse_args()

    # Generate tables
    users_df = generate_users(num_records=args.users)
    generate_notifications(users_df, num_records=args.notifications)
    generate_fraud_requests(users_df, num_records=args.fraud)
    