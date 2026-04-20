import argparse
import csv
import os
import random
from datetime import datetime, timedelta
from faker import Faker

fake = Faker()

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DB_DIR      = os.path.join(REPO_ROOT, "database")
OUTPUT_DIR  = os.path.join(DB_DIR, "mock_db")

os.makedirs(OUTPUT_DIR, exist_ok=True)

NOTIFICATION_TYPE_IDS    = [1, 10, 11, 12, 13]
NOTIFICATION_CHANNEL_IDS = [1, 2, 3, 4]
NOTIFICATION_STATUSES    = ["SENT", "DELIVERED", "FAILED", "PENDING", "READ"]

NOTIFICATION_MESSAGES = {
    1: [
        "Action required: a critical alert has been raised on your account.",
        "Security notice: unusual activity was detected. Please verify your account.",
        "Your account has been temporarily flagged for a security review.",
    ],
    10: [
        "Just a reminder that your volunteer event is coming up tomorrow.",
        "Heads up - you have a volunteer event starting soon.",
        "Please confirm your attendance for your upcoming volunteer session.",
    ],
    11: [
        "Someone sent you a direct message on Saayam.",
        "You have a new message waiting in your Saayam inbox.",
        "A fellow Saayam member has reached out to you.",
    ],
    12: [
        "There has been an update to your volunteer application.",
        "Your application status has changed - log in to see the latest.",
        "Good news - your volunteer application has moved forward.",
    ],
    13: [
        "You have hit a new volunteer hours milestone - well done!",
        "Keep it up - you just reached a volunteer hours goal.",
        "Your dedication is paying off - new milestone unlocked!",
    ],
}

FRAUD_REASONS = [
    "Multiple help requests submitted to gain additional assistance",
    "Account shows signs of identity compromise",
    "Phishing links shared from this account",
    "Profile contains unverifiable or false information",
    "Login detected from an unrecognized device or location",
    "Account is impersonating a verified platform user",
    "Unusual pattern of creating and cancelling help requests",
    "Incentive or reward manipulation detected",
    "Registration email linked to a temporary mail service",
    "Same device fingerprint found across multiple accounts",
    "User attempting to move transactions outside the platform",
    "Account activity matches known bot behavior patterns",
]


def init_seed(seed=42):
    random.seed(seed)
    Faker.seed(seed)
    fake.seed_instance(seed)


def to_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def generate_random_ts():
    start = datetime(2023, 1, 1)
    end   = datetime(2025, 12, 31)
    delta = end - start
    return start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))


def ts_after(base, max_minutes=1440):
    return base + timedelta(minutes=random.randint(1, max_minutes))


def save_to_csv(filepath, rows):
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
        print("  [info] mock_users.csv not found - using stub user IDs USR-101 to USR-200")
        return [f"USR-{i}" for i in range(101, 201)]
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

    for i in range(0, count):
        rows.append({
            "fraud_request_id" : i + 1,
            "user_id"          : random.choice(user_ids),
            "request_datetime" : to_ts(generate_random_ts()),
            "reason"           : random.choice(FRAUD_REASONS),
        })

    save_to_csv(os.path.join(OUTPUT_DIR, "mock_fraud_requests.csv"), rows)
    return rows


def generate_notifications(count=100):
    print(f"Generating {count:,} notifications ...")
    user_ids = load_user_ids()
    rows     = []

    for i in range(0, count):
        type_id    = random.choice(NOTIFICATION_TYPE_IDS)
        created_at = generate_random_ts()
        updated_at = ts_after(created_at, max_minutes=1440)

        rows.append({
            "notification_id" : i + 1,
            "user_id"         : random.choice(user_ids),
            "type_id"         : type_id,
            "channel_id"      : random.choice(NOTIFICATION_CHANNEL_IDS),
            "message"         : random.choice(NOTIFICATION_MESSAGES[type_id]),
            "status"          : random.choice(NOTIFICATION_STATUSES),
            "created_at"      : to_ts(created_at),
            "last_update_date": to_ts(updated_at),
        })

    save_to_csv(os.path.join(OUTPUT_DIR, "mock_notifications.csv"), rows)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fraud",         type=int, default=100)
    parser.add_argument("--notifications", type=int, default=100)
    parser.add_argument("--seed",          type=int, default=42)
    args = parser.parse_args()
    init_seed(args.seed)
    generate_fraud_requests(count=args.fraud)
    generate_notifications(count=args.notifications)