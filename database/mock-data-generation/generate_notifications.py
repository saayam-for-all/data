"""
generate_notifications.py
=========================
Generates synthetic mock data for the `notifications` table.

Schema:
    notification_id   : integer
    user_id           : character varying(255) → FK to users
    type_id           : integer → FK to notification_types
    channel_id        : integer → FK to notification_channels
    message           : text
    status            : USER-DEFINED enum (sent | delivered | read | failed)
    created_at        : timestamp without time zone
    last_update_date  : timestamp without time zone

Lookup references used:
    notification_types    : type_id 1–6
    notification_channels : channel_id 1–4

Usage:
    python generate_notifications.py [--rows 30000] [--output notifications.csv]

Dependencies:
    pip install faker pandas
"""

import argparse
import random
from datetime import datetime, timedelta

import pandas as pd
from faker import Faker

fake = Faker()
random.seed(42)
Faker.seed(42)

# ── Lookup table data (mirrors notification_types and notification_channels) ───
NOTIFICATION_TYPES = {
    1: "Volunteer Match",
    2: "Help Request Update",
    3: "System Alert",
    4: "New Message",
    5: "Account Activity",
    6: "Community Announcement",
}

NOTIFICATION_CHANNELS = {
    1: "Email",
    2: "SMS",
    3: "Push Notification",
    4: "In-App",
}

# ── Status enum (USER-DEFINED in DB) ──────────────────────────────────────────
STATUS_VALUES = ["sent", "delivered", "read", "failed"]
STATUS_WEIGHTS = [0.15, 0.25, 0.55, 0.05]   # most notifications get read

# ── Message templates by type_id ──────────────────────────────────────────────
MESSAGE_TEMPLATES = {
    1: [  # Volunteer Match
        "A volunteer has been matched to your request. Please check your dashboard.",
        "Great news! A nearby volunteer accepted your help request.",
        "Your request has been matched with a verified volunteer.",
        "Volunteer {name} is on their way to assist you.",
        "A volunteer match has been found for your recent submission.",
    ],
    2: [  # Help Request Update
        "Your help request status has been updated to 'In Progress'.",
        "Your request has been marked as completed. Please rate your experience.",
        "An update is available for your submitted help request.",
        "Your help request has been reviewed and is awaiting a volunteer.",
        "Status change: Your request is now under review by our team.",
    ],
    3: [  # System Alert
        "Scheduled maintenance is planned for tonight between 2–4 AM EST.",
        "Your account password was recently changed. Contact support if this wasn't you.",
        "System update complete. New features are now available.",
        "We detected a login from a new device. Please verify your identity.",
        "Your session has expired. Please log in again to continue.",
    ],
    4: [  # New Message
        "You have a new message from a volunteer regarding your request.",
        "A community member sent you a message. Tap to view.",
        "New message received from support team.",
        "Your volunteer has sent you an update message.",
        "You received a reply to your comment on a help request.",
    ],
    5: [  # Account Activity
        "Your profile was successfully updated.",
        "You have successfully completed the volunteer onboarding process.",
        "Your language preferences have been saved.",
        "Your account has been verified successfully.",
        "You have been promoted to a lead volunteer status.",
    ],
    6: [  # Community Announcement
        "A calamity relief drive is active in your area. Volunteers needed urgently.",
        "Saayam community meetup scheduled for next Saturday. Click to RSVP.",
        "New help categories are now available on the platform.",
        "Monthly volunteer recognition — thank you for your contributions!",
        "Saayam platform update: Improved matching algorithm is now live.",
    ],
}


def generate_user_ids(n=500):
    """Generate a consistent pool of user_ids matching the users table format."""
    return [f"usr-{fake.uuid4()[:8]}-{fake.uuid4()[:4]}" for _ in range(n)]


def generate_notifications(num_rows: int, user_pool: list) -> pd.DataFrame:
    start_date = datetime(2022, 1, 1)
    end_date = datetime(2025, 3, 31)
    date_range = (end_date - start_date).days

    type_ids = list(NOTIFICATION_TYPES.keys())
    channel_ids = list(NOTIFICATION_CHANNELS.keys())

    # Weighted distribution: in-app and push are more common
    channel_weights = [0.20, 0.15, 0.30, 0.35]

    records = []
    for i in range(1, num_rows + 1):
        type_id = random.choice(type_ids)
        channel_id = random.choices(channel_ids, weights=channel_weights, k=1)[0]
        status = random.choices(STATUS_VALUES, weights=STATUS_WEIGHTS, k=1)[0]

        # Pick a message template for the notification type
        template = random.choice(MESSAGE_TEMPLATES[type_id])
        # Fill in any placeholder
        message = template.replace("{name}", fake.first_name())

        created_at = start_date + timedelta(
            days=random.randint(0, date_range),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
            seconds=random.randint(0, 59),
        )

        # last_update_date is same or slightly after created_at
        update_offset_minutes = random.randint(0, 1440)  # up to 24h later
        last_update_date = created_at + timedelta(minutes=update_offset_minutes)

        records.append({
            "notification_id": i,
            "user_id": random.choice(user_pool),
            "type_id": type_id,
            "channel_id": channel_id,
            "message": message,
            "status": status,
            "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "last_update_date": last_update_date.strftime("%Y-%m-%d %H:%M:%S"),
        })

        if i % 5000 == 0:
            print(f"  ... generated {i} rows")

    return pd.DataFrame(records)


def main():
    parser = argparse.ArgumentParser(description="Generate notifications mock data")
    parser.add_argument("--rows", type=int, default=30000, help="Number of rows to generate")
    parser.add_argument("--output", type=str, default="notifications.csv", help="Output CSV file path")
    args = parser.parse_args()

    print(f"Generating {args.rows} rows for notifications...")
    user_pool = generate_user_ids(500)
    df = generate_notifications(args.rows, user_pool)
    df.to_csv(args.output, index=False)
    print(f"✅ Saved: {args.output}  ({len(df)} rows, {len(df.columns)} columns)")
    print(f"   Columns: {list(df.columns)}")


if __name__ == "__main__":
    main()
