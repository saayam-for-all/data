import argparse
import csv
import os
import random
from datetime import datetime, timedelta
from faker import Faker

fake = Faker()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DB_DIR     = os.path.join(REPO_ROOT, "database")
OUTPUT_DIR = os.path.join(DB_DIR, "mock_db")

os.makedirs(OUTPUT_DIR, exist_ok=True)

NOTIFICATION_TYPE_IDS    = [1, 10, 11, 12, 13]
NOTIFICATION_CHANNEL_IDS = [1, 2, 3, 4]
NOTIFICATION_STATUSES    = ["SENT", "DELIVERED", "FAILED", "PENDING", "READ"]

NOTIFICATION_MESSAGES = {
    1: [
        "A critical alert has been raised on your account. Please review immediately.",
        "Critical system alert: unusual activity detected. Please verify your account.",
        "Your account has been flagged for a critical security review.",
    ],
    10: [
        "Reminder: your upcoming volunteer event is scheduled for tomorrow.",
        "You have a registered volunteer event starting soon.",
        "Event reminder: please confirm your attendance for the upcoming session.",
    ],
    11: [
        "You have received a new direct message from another user.",
        "A Saayam member has sent you a message. Tap to read.",
        "New message received in your Saayam inbox.",
    ],
    12: [
        "Your volunteer application status has been updated. Please check your profile.",
        "There is an update regarding your volunteer application. Log in to review.",
        "Application update: your volunteer submission has moved to the next stage.",
    ],
    13: [
        "Congratulations! You have reached a new volunteer hour milestone.",
        "Amazing work - you have hit a volunteer hours goal. Keep it up!",
        "Milestone achieved: thank you for your continued dedication as a volunteer.",
    ],
}

FRAUD_REASONS = [
    "User submitted duplicate requests to obtain additional help",
    "Suspected identity theft - account credentials may be compromised",
    "Phishing attempt detected from this account",
    "User provided false information on their profile",
    "Unauthorized account access from an unrecognized device",
    "Reported for impersonating another verified user",
    "Suspicious pattern of repeated help request cancellations",
    "Payment or incentive fraud suspected",
    "Account created with a disposable email address",
    "Multiple accounts detected sharing the same device fingerprint",
    "User solicited off-platform transactions from volunteers",
    "Automated bot-like activity detected on the account",
]


def set_seed(seed=42):
    random.seed(seed)
    Faker.seed(seed)
    fake.seed_instance(seed)


def format_ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def random_created_at():
    start = datetime(2024, 1, 1)
    end   = datetime(2026, 4, 1)
    delta = end - start
    return start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))


def datetime_after(base, max_minutes=1440):
    return base + timedelta(minutes=random.randint(1, max_minutes))


def write_csv(filepath, rows):
    if not rows:
        raise ValueError(f"No rows to write for {filepath}")
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows):,} rows -> {filepath}")


def load_user_ids():
    path = os.path.join(OUTPUT_DIR, "mock_users.csv")
    if not os.path.exists(path):
        print("  [info] mock_users.csv not found - using stub user IDs U101-U200")
        return [f"U{i}" for i in range(101, 201)]
    user_ids = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            user_ids.append(row["user_id"])
    return user_ids


def generate_fraud_requests(count=100):
    print(f"Generating {count:,} fraud_requests ...")
    user_ids = load_user_ids()
    rows     = []

    for i in range(1, count + 1):
        rows.append({
            "fraud_request_id" : i,
            "user_id"          : random.choice(user_ids),
            "request_datetime" : format_ts(random_created_at()),
            "reason"           : random.choice(FRAUD_REASONS),
        })

    write_csv(os.path.join(OUTPUT_DIR, "mock_fraud_requests.csv"), rows)
    return rows


def generate_notifications(count=100):
    print(f"Generating {count:,} notifications ...")
    user_ids = load_user_ids()
    rows     = []

    for i in range(1, count + 1):
        type_id    = random.choice(NOTIFICATION_TYPE_IDS)
        created_at = random_created_at()
        updated_at = datetime_after(created_at, max_minutes=1440)

        rows.append({
            "notification_id" : i,
            "user_id"         : random.choice(user_ids),
            "type_id"         : type_id,
            "channel_id"      : random.choice(NOTIFICATION_CHANNEL_IDS),
            "message"         : random.choice(NOTIFICATION_MESSAGES[type_id]),
            "status"          : random.choice(NOTIFICATION_STATUSES),
            "created_at"      : format_ts(created_at),
            "last_update_date": format_ts(updated_at),
        })

    write_csv(os.path.join(OUTPUT_DIR, "mock_notifications.csv"), rows)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fraud",         type=int, default=100)
    parser.add_argument("--notifications", type=int, default=100)
    parser.add_argument("--seed",          type=int, default=42)
    args = parser.parse_args()
    set_seed(args.seed)
    generate_fraud_requests(count=args.fraud)
    generate_notifications(count=args.notifications)